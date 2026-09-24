"""OpenAI Gymnasium Reinforcement Learning Adapter for Gaming MCP Server.

Provides a unified Model Context Protocol interface for OpenAI Gymnasium and legacy Gym
environments, supporting deterministic step/reset cycles, observation vector serialization,
space introspection, RGB visual frame rendering, and live state telemetry resources.

Includes capability probing with automatic fallback to a high-fidelity simulated CartPole-v1
physics environment when Gymnasium is not installed on the host.
"""

from __future__ import annotations

import importlib
import json
import logging
import math
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.config import GamingMCPConfig, GymnasiumConfig
from gaming_mcp.core.exceptions import AdapterError
from gaming_mcp.utils.image import encode_image, image_to_base64

if TYPE_CHECKING:
    from collections.abc import Callable

    from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry

logger = logging.getLogger("gaming_mcp.adapters.gymnasium")


# -----------------------------------------------------------------------------
# Capability Probing
# -----------------------------------------------------------------------------


def probe_gymnasium_backend(mock_mode: bool = False) -> str:
    """Probe host environment for Gymnasium or Gym availability.

    Returns:
        'simulated' if mock_mode is requested or neither package is installed.
        'gymnasium' if the gymnasium package is importable.
        'gym' if legacy gym is importable.
    """
    if mock_mode:
        return "simulated"

    try:
        importlib.import_module("gymnasium")
        return "gymnasium"
    except ImportError:
        pass

    try:
        importlib.import_module("gym")
        return "gym"
    except ImportError:
        pass

    return "simulated"


def _to_json_serializable(val: Any) -> Any:
    """Recursively convert NumPy structures and non-finite floats to JSON-serializable types."""
    if isinstance(val, np.ndarray):
        return [_to_json_serializable(x) for x in val.tolist()]
    if isinstance(val, (np.floating, float)):
        if math.isnan(val):
            return "NaN"
        if math.isinf(val):
            return "Infinity" if val > 0 else "-Infinity"
        return float(val)
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, (list, tuple)):
        return [_to_json_serializable(x) for x in val]
    if isinstance(val, dict):
        return {str(k): _to_json_serializable(v) for k, v in val.items()}
    return val


# -----------------------------------------------------------------------------
# Tool Input Schemas
# -----------------------------------------------------------------------------


class GymStepInput(BaseModel):
    """Input parameters for gym_step tool."""

    action: int | list[float] | list[int] = Field(
        ...,
        description=(
            "Action to execute in environment (discrete integer or continuous action vector)"
        ),
    )


class GymResetInput(BaseModel):
    """Input parameters for gym_reset tool."""

    seed: int | None = Field(
        default=None,
        description="Optional random seed for reproducible environment initialization",
    )


class GymActionSpaceInput(BaseModel):
    """Input parameters for gym_action_space tool."""


class GymObservationSpaceInput(BaseModel):
    """Input parameters for gym_observation_space tool."""


class GymRenderInput(BaseModel):
    """Input parameters for gym_render tool."""

    format: Literal["png", "jpeg"] = Field(
        default="png",
        description="Image compression format ('png' or 'jpeg')",
    )


# -----------------------------------------------------------------------------
# High-Fidelity Simulated CartPole-v1 Environment
# -----------------------------------------------------------------------------


class SimulatedCartPoleEnv:
    """High-fidelity simulated CartPole-v1 environment implementing classical dynamics.

    Adheres strictly to the standard CartPole-v1 specification (Barto, Sutton, and Anderson, 1983):
    State vector: [cart_position, cart_velocity, pole_angle, pole_angular_velocity]
    Actions: 0 (Push cart to left), 1 (Push cart to right)
    """

    def __init__(self, max_episode_steps: int = 500) -> None:
        self.gravity: float = 9.8
        self.masscart: float = 1.0
        self.masspole: float = 0.1
        self.total_mass: float = self.masscart + self.masspole
        self.length: float = 0.5  # half-length of pole
        self.polemass_length: float = self.masspole * self.length
        self.force_mag: float = 10.0
        self.tau: float = 0.02  # seconds between state updates

        # Termination thresholds
        self.theta_threshold_radians: float = 12.0 * 2.0 * math.pi / 360.0  # ~0.2094 rad (12 deg)
        self.x_threshold: float = 2.4
        self.max_episode_steps: int = max_episode_steps

        # State and accounting
        self.state: list[float] | None = None
        self.step_count: int = 0
        self.cumulative_reward: float = 0.0
        self._rng: np.random.Generator = np.random.default_rng()

    def reset(self, seed: int | None = None) -> tuple[list[float], dict[str, Any]]:
        """Reset environment to random uniform state within [-0.05, 0.05]."""
        if seed is not None:
            self._rng = np.random.default_rng(seed)

        initial = self._rng.uniform(low=-0.05, high=0.05, size=4)
        self.state = [float(x) for x in initial]
        self.step_count = 0
        self.cumulative_reward = 0.0

        info: dict[str, Any] = {
            "seed": seed,
            "simulated": True,
            "env_id": "CartPole-v1",
        }
        return list(self.state), info

    def step(
        self, action: int | list[float] | list[int]
    ) -> tuple[list[float], float, bool, bool, dict[str, Any]]:
        """Advance physical dynamics by one timestep."""
        if self.state is None:
            raise AdapterError("Environment has not been reset. Call gym_reset() first.")

        # Parse and validate discrete action
        act: int
        if isinstance(action, (int, np.integer)):
            act = int(action)
        elif isinstance(action, (list, tuple)):
            if len(action) == 1 and isinstance(action[0], (int, float, np.integer, np.floating)):
                act = int(action[0])
            else:
                raise AdapterError(
                    f"Invalid action format for CartPole-v1: {action}. "
                    "Expected discrete action 0 or 1."
                )
        else:
            raise AdapterError(
                f"Invalid action type {type(action).__name__}. Expected discrete action 0 or 1."
            )

        if act not in (0, 1):
            raise AdapterError(
                f"Action {act} out of bounds for Discrete(2) space. "
                "Valid actions are 0 (push left) or 1 (push right)."
            )

        x, x_dot, theta, theta_dot = self.state
        force = self.force_mag if act == 1 else -self.force_mag
        costheta = math.cos(theta)
        sintheta = math.sin(theta)

        temp = (force + self.polemass_length * (theta_dot**2) * sintheta) / self.total_mass
        thetaacc = (self.gravity * sintheta - costheta * temp) / (
            self.length * (4.0 / 3.0 - self.masspole * (costheta**2) / self.total_mass)
        )
        xacc = temp - self.polemass_length * thetaacc * costheta / self.total_mass

        # Semi-implicit Euler integration
        x = x + self.tau * x_dot
        x_dot = x_dot + self.tau * xacc
        theta = theta + self.tau * theta_dot
        theta_dot = theta_dot + self.tau * thetaacc

        self.state = [float(x), float(x_dot), float(theta), float(theta_dot)]
        self.step_count += 1
        reward = 1.0
        self.cumulative_reward += reward

        terminated = bool(
            x < -self.x_threshold
            or x > self.x_threshold
            or theta < -self.theta_threshold_radians
            or theta > self.theta_threshold_radians
        )
        truncated = bool(self.step_count >= self.max_episode_steps and not terminated)

        info: dict[str, Any] = {
            "step_count": self.step_count,
            "cumulative_reward": self.cumulative_reward,
            "simulated": True,
        }
        return list(self.state), reward, terminated, truncated, info

    def action_space_info(self) -> dict[str, Any]:
        """Return action space specification."""
        return {
            "type": "Discrete",
            "n": 2,
            "start": 0,
            "shape": [],
            "dtype": "int64",
            "description": "Discrete(2): 0=Push cart to left, 1=Push cart to right",
        }

    def observation_space_info(self) -> dict[str, Any]:
        """Return observation space specification."""
        high_theta = float(round(self.theta_threshold_radians * 2, 6))
        return {
            "type": "Box",
            "shape": [4],
            "dtype": "float32",
            "low": [-4.8, -float("inf"), -high_theta, -float("inf")],
            "high": [4.8, float("inf"), high_theta, float("inf")],
            "names": [
                "cart_position",
                "cart_velocity",
                "pole_angle",
                "pole_angular_velocity",
            ],
            "descriptions": [
                "Cart position on rail (-2.4 to 2.4 nominal limits)",
                "Cart horizontal velocity",
                "Pole angle in radians (-0.2095 to 0.2095 nominal limits)",
                "Pole angular velocity",
            ],
        }

    def render(self) -> np.ndarray:
        """Render RGB visualization of current CartPole state."""
        width = 600
        height = 400
        img = Image.new("RGB", (width, height), (248, 249, 252))
        draw = ImageDraw.Draw(img)

        # Coordinate parameters
        track_y = 300
        world_width = 4.8
        scale = width / world_width  # pixels per meter (~125 px/m)

        # Draw track line
        draw.line([(0, track_y), (width, track_y)], fill=(120, 130, 145), width=3)

        # Determine cart coordinates
        x = self.state[0] if self.state is not None else 0.0
        theta = self.state[2] if self.state is not None else 0.0

        cart_x = width / 2.0 + x * scale
        cart_y = track_y - 20
        cart_w = 70.0
        cart_h = 36.0

        # Draw cart body
        cart_left = cart_x - cart_w / 2.0
        cart_top = cart_y - cart_h / 2.0
        cart_right = cart_x + cart_w / 2.0
        cart_bottom = cart_y + cart_h / 2.0
        draw.rectangle(
            [(cart_left, cart_top), (cart_right, cart_bottom)],
            fill=(45, 55, 72),
            outline=(26, 32, 44),
            width=2,
        )

        # Draw wheels
        wheel_radius = 6.0
        wheel_y = track_y - wheel_radius
        for wx in (cart_left + 14, cart_right - 14):
            draw.ellipse(
                [
                    (wx - wheel_radius, wheel_y - wheel_radius),
                    (wx + wheel_radius, wheel_y + wheel_radius),
                ],
                fill=(20, 24, 30),
            )

        # Draw pole
        pole_len = 120.0
        pole_width = 8.0
        pivot_x = cart_x
        pivot_y = cart_y - cart_h / 2.0 + 2.0

        tip_x = pivot_x + pole_len * math.sin(theta)
        tip_y = pivot_y - pole_len * math.cos(theta)

        draw.line(
            [(pivot_x, pivot_y), (tip_x, tip_y)], fill=(205, 92, 92), width=int(pole_width)
        )

        # Draw pivot pin
        pin_radius = 5.0
        draw.ellipse(
            [
                (pivot_x - pin_radius, pivot_y - pin_radius),
                (pivot_x + pin_radius, pivot_y + pin_radius),
            ],
            fill=(230, 180, 50),
            outline=(100, 70, 20),
            width=1,
        )

        # Draw text HUD
        font = ImageFont.load_default()
        hud_lines = [
            f"Env: CartPole-v1 (Simulated) | Step: {self.step_count}/{self.max_episode_steps}",
            (
                f"Position: {x:+.3f} m | "
                f"Velocity: {self.state[1] if self.state else 0.0:+.3f} m/s"
            ),
            (
                f"Angle: {theta:+.3f} rad ({math.degrees(theta):+.1f} deg) | "
                f"Angular Vel: {self.state[3] if self.state else 0.0:+.3f} rad/s"
            ),
            f"Cumulative Reward: {self.cumulative_reward:.1f}",
        ]
        for idx, line in enumerate(hud_lines):
            draw.text((15, 12 + idx * 16), line, fill=(30, 41, 59), font=font)

        return np.asarray(img, dtype=np.uint8)

    def close(self) -> None:
        """Release environment resources."""
        self.state = None


# -----------------------------------------------------------------------------
# Native Gymnasium Environment Wrapper
# -----------------------------------------------------------------------------


class NativeGymnasiumEnv:
    """Wrapper interfacing with official Gymnasium or legacy Gym library."""

    def __init__(
        self,
        env_id: str = "CartPole-v1",
        render_mode: str = "rgb_array",
        max_episode_steps: int | None = None,
    ) -> None:
        self.env_id = env_id
        self.render_mode = render_mode
        self.max_episode_steps = max_episode_steps

        # Dynamically import gymnasium or gym
        self._gym: Any
        try:
            self._gym = importlib.import_module("gymnasium")
        except ImportError:
            self._gym = importlib.import_module("gym")

        make_kwargs: dict[str, Any] = {}
        if render_mode:
            make_kwargs["render_mode"] = render_mode
        if max_episode_steps is not None:
            make_kwargs["max_episode_steps"] = max_episode_steps

        try:
            self.env: Any = self._gym.make(env_id, **make_kwargs)
        except TypeError:
            # Legacy Gym make might not accept render_mode
            make_kwargs.pop("render_mode", None)
            self.env = self._gym.make(env_id, **make_kwargs)

    def reset(self, seed: int | None = None) -> tuple[Any, dict[str, Any]]:
        """Reset native environment with optional seed."""
        res: Any
        if seed is not None:
            try:
                res = self.env.reset(seed=seed)
            except TypeError:
                res = self.env.reset()
        else:
            res = self.env.reset()

        if isinstance(res, tuple) and len(res) == 2:
            obs, info = res
        else:
            obs = res
            info = {}

        return _to_json_serializable(obs), _to_json_serializable(info)

    def step(
        self, action: int | list[float] | list[int]
    ) -> tuple[Any, float, bool, bool, dict[str, Any]]:
        """Execute action in native environment."""
        parsed_action: Any = action
        action_space = getattr(self.env, "action_space", None)

        if action_space is not None:
            space_type = type(action_space).__name__
            if space_type == "Discrete":
                parsed_action = (
                    int(action[0]) if isinstance(action, (list, tuple)) else int(action)
                )
            elif space_type == "Box":
                if isinstance(action, (int, float)):
                    parsed_action = np.array([action], dtype=action_space.dtype)
                else:
                    parsed_action = np.array(action, dtype=action_space.dtype)

        res = self.env.step(parsed_action)

        # Gymnasium returns 5 elements; legacy Gym returns 4 elements
        if len(res) == 5:
            obs, reward, terminated, truncated, info = res
        elif len(res) == 4:
            obs, reward, done, info = res
            terminated = done
            truncated = False
        else:
            raise AdapterError(f"Unexpected return structure from env.step: {len(res)} elements")

        return (
            _to_json_serializable(obs),
            float(reward),
            bool(terminated),
            bool(truncated),
            _to_json_serializable(info),
        )

    def action_space_info(self) -> dict[str, Any]:
        """Inspect and return action space structure."""
        space = getattr(self.env, "action_space", None)
        if space is None:
            return {"type": "Unknown"}

        space_type = type(space).__name__
        info: dict[str, Any] = {
            "type": space_type,
            "shape": list(space.shape) if hasattr(space, "shape") and space.shape else [],
            "dtype": str(getattr(space, "dtype", "unknown")),
        }
        if hasattr(space, "n"):
            info["n"] = int(space.n)
        if hasattr(space, "low") and hasattr(space, "high"):
            info["low"] = _to_json_serializable(space.low)
            info["high"] = _to_json_serializable(space.high)

        return info

    def observation_space_info(self) -> dict[str, Any]:
        """Inspect and return observation space structure."""
        space = getattr(self.env, "observation_space", None)
        if space is None:
            return {"type": "Unknown"}

        space_type = type(space).__name__
        info: dict[str, Any] = {
            "type": space_type,
            "shape": list(space.shape) if hasattr(space, "shape") and space.shape else [],
            "dtype": str(getattr(space, "dtype", "unknown")),
        }
        if hasattr(space, "low") and hasattr(space, "high"):
            info["low"] = _to_json_serializable(space.low)
            info["high"] = _to_json_serializable(space.high)
        if hasattr(space, "n"):
            info["n"] = int(space.n)

        return info

    def render(self) -> np.ndarray:
        """Render RGB array from native environment."""
        frame: Any = self.env.render()
        if isinstance(frame, np.ndarray) and frame.ndim == 3:
            return frame.astype(np.uint8)

        # Fallback frame when render returns None or non-array
        fallback = Image.new("RGB", (400, 300), (30, 30, 30))
        draw = ImageDraw.Draw(fallback)
        font = ImageFont.load_default()
        draw.text(
            (20, 140),
            f"Env: {self.env_id}\nRender mode: {self.render_mode}",
            fill=(220, 220, 220),
            font=font,
        )
        return np.asarray(fallback, dtype=np.uint8)

    def close(self) -> None:
        """Close native environment."""
        self.env.close()


# -----------------------------------------------------------------------------
# GymnasiumAdapter Implementation
# -----------------------------------------------------------------------------


class GymnasiumAdapter(GameAdapter):
    """OpenAI Gymnasium Reinforcement Learning MCP Adapter.

    Implements the GameAdapter SPI, offering full control over RL environments
    with observation vector streaming, discrete/continuous actuation, space introspection,
    rendered visual frames, and live state telemetry resources.
    """

    def __init__(
        self,
        config: GamingMCPConfig | None = None,
        custom_env: Any | None = None,
    ) -> None:
        super().__init__(config=config or GamingMCPConfig())
        self._custom_env = custom_env
        self._env: Any = None
        self._backend: str = "unknown"
        self._env_id: str = "CartPole-v1"

        # Cached telemetry state
        self.last_observation: Any = None
        self.last_reward: float = 0.0
        self.last_terminated: bool = False
        self.last_truncated: bool = False
        self.step_count: int = 0
        self.cumulative_reward: float = 0.0
        self.episode_count: int = 0

        # Reactive subscriptions
        self._subscriptions: dict[str, set[Callable[[str, dict[str, Any]], None]]] = {
            "gym://observation": set(),
            "gym://state": set(),
        }

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            id="gymnasium",
            display_name="OpenAI Gymnasium RL Adapter",
            version="0.1.0",
            description=(
                "OpenAI Gymnasium reinforcement learning environment adapter supporting "
                "standard observation vectors, discrete/continuous actions, step/reset dynamics, "
                "visual rendering, and simulated CartPole-v1 fallback."
            ),
            supported_platforms=["win32", "linux", "darwin"],
            requires_display=False,
            requires_admin_privileges=False,
        )

    @property
    def is_simulated(self) -> bool:
        """Return True if active environment is running in simulation mode."""
        return self._backend == "simulated"

    @property
    def backend(self) -> str:
        """Return active execution backend ('gymnasium', 'gym', 'simulated', or 'custom')."""
        return self._backend

    @property
    def env_id(self) -> str:
        """Return target environment identifier."""
        return self._env_id

    async def initialize(self) -> None:
        """Initialize Gymnasium environment or high-fidelity simulation."""
        if self.is_initialized:
            return

        gym_config = (
            self.config.adapters.gymnasium
            if self.config and self.config.adapters and self.config.adapters.gymnasium
            else GymnasiumConfig()
        )
        self._env_id = gym_config.env_id

        if self._custom_env is not None:
            self._env = self._custom_env
            self._backend = "custom"
            logger.info(
                "GymnasiumAdapter initialized with custom environment: %s",
                type(self._custom_env).__name__,
            )
        elif gym_config.mock_mode:
            self._env = SimulatedCartPoleEnv(max_episode_steps=gym_config.max_episode_steps or 500)
            self._backend = "simulated"
            logger.info("GymnasiumAdapter initialized in mock mode with SimulatedCartPoleEnv")
        else:
            detected_backend = probe_gymnasium_backend()
            if detected_backend in ("gymnasium", "gym"):
                try:
                    self._env = NativeGymnasiumEnv(
                        env_id=gym_config.env_id,
                        render_mode=gym_config.render_mode,
                        max_episode_steps=gym_config.max_episode_steps,
                    )
                    self._backend = detected_backend
                    logger.info(
                        "GymnasiumAdapter initialized with native backend: %s (%s)",
                        detected_backend,
                        gym_config.env_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Native %s environment '%s' failed to initialize: %s. "
                        "Falling back to SimulatedCartPoleEnv.",
                        detected_backend,
                        gym_config.env_id,
                        exc,
                    )
                    self._env = SimulatedCartPoleEnv(
                        max_episode_steps=gym_config.max_episode_steps or 500
                    )
                    self._backend = "simulated"
            else:
                self._env = SimulatedCartPoleEnv(
                    max_episode_steps=gym_config.max_episode_steps or 500
                )
                self._backend = "simulated"
                logger.info(
                    "Gymnasium / Gym not installed; seamlessly operating in "
                    "SimulatedCartPoleEnv mode"
                )

        self.is_initialized = True
        logger.info("GymnasiumAdapter initialized successfully (backend=%s)", self._backend)

    async def shutdown(self) -> None:
        """Gracefully release environment resources."""
        if not self.is_initialized:
            return

        if self._env is not None and hasattr(self._env, "close"):
            try:
                self._env.close()
            except Exception as exc:
                logger.warning("Error closing environment during shutdown: %s", exc)

        self._env = None
        self.is_initialized = False
        logger.info("GymnasiumAdapter shut down cleanly")

    async def health_check(self) -> dict[str, Any]:
        """Probe environment health and execution metrics."""
        return {
            "adapter_id": self.metadata.id,
            "status": "healthy" if self.is_initialized else "uninitialized",
            "backend": self._backend,
            "is_simulated": self.is_simulated,
            "env_id": self._env_id,
            "step_count": self.step_count,
            "episode_count": self.episode_count,
            "cumulative_reward": self.cumulative_reward,
            "last_reward": self.last_reward,
            "terminated": self.last_terminated,
            "truncated": self.last_truncated,
        }

    # -------------------------------------------------------------------------
    # Reactive Subscriptions
    # -------------------------------------------------------------------------

    def subscribe_resource(
        self, uri: str, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Register a reactive listener callback for resource updates."""
        if uri not in self._subscriptions:
            self._subscriptions[uri] = set()
        self._subscriptions[uri].add(callback)

    def unsubscribe_resource(
        self, uri: str, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Unregister a reactive listener callback."""
        if uri in self._subscriptions:
            self._subscriptions[uri].discard(callback)

    def _notify_resource_subscribers(self, uri: str, payload: dict[str, Any]) -> None:
        """Deliver pushed update to all subscribed callbacks."""
        listeners = list(self._subscriptions.get(uri, set()))
        for listener in listeners:
            try:
                listener(uri, payload)
            except Exception as exc:
                logger.warning("Error notifying subscriber for %s: %s", uri, exc)

    def _get_observation_payload(self) -> dict[str, Any]:
        """Construct payload for gym://observation resource."""
        return {
            "observation": self.last_observation,
            "env_id": self._env_id,
            "step_count": self.step_count,
            "episode_count": self.episode_count,
            "terminated": self.last_terminated,
            "truncated": self.last_truncated,
        }

    def _get_state_payload(self) -> dict[str, Any]:
        """Construct payload for gym://state resource."""
        return {
            "env_id": self._env_id,
            "backend": self._backend,
            "is_simulated": self.is_simulated,
            "episode_count": self.episode_count,
            "step_count": self.step_count,
            "cumulative_reward": self.cumulative_reward,
            "last_reward": self.last_reward,
            "terminated": self.last_terminated,
            "truncated": self.last_truncated,
            "action_space": self._env.action_space_info() if self._env else None,
            "observation_space": self._env.observation_space_info() if self._env else None,
        }

    # -------------------------------------------------------------------------
    # Tool Implementations
    # -------------------------------------------------------------------------

    async def _tool_gym_step(
        self, action: int | list[float] | list[int]
    ) -> dict[str, Any]:
        """Step the active Gymnasium environment by executing an action."""
        if not self.is_initialized or self._env is None:
            raise AdapterError("GymnasiumAdapter is not initialized. Call initialize() first.")

        obs, reward, terminated, truncated, info = self._env.step(action)

        self.last_observation = obs
        self.last_reward = float(reward)
        self.last_terminated = bool(terminated)
        self.last_truncated = bool(truncated)
        self.step_count += 1
        self.cumulative_reward += float(reward)

        obs_payload = self._get_observation_payload()
        state_payload = self._get_state_payload()
        self._notify_resource_subscribers("gym://observation", obs_payload)
        self._notify_resource_subscribers("gym://state", state_payload)

        result_payload = {
            "observation": obs,
            "reward": float(reward),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "info": info,
        }

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result_payload, indent=2),
                }
            ],
            **result_payload,
        }

    async def _tool_gym_reset(self, seed: int | None = None) -> dict[str, Any]:
        """Reset the Gymnasium environment to its initial state."""
        if not self.is_initialized or self._env is None:
            raise AdapterError("GymnasiumAdapter is not initialized. Call initialize() first.")

        obs, info = self._env.reset(seed=seed)

        self.last_observation = obs
        self.last_reward = 0.0
        self.last_terminated = False
        self.last_truncated = False
        self.step_count = 0
        self.cumulative_reward = 0.0
        self.episode_count += 1

        obs_payload = self._get_observation_payload()
        state_payload = self._get_state_payload()
        self._notify_resource_subscribers("gym://observation", obs_payload)
        self._notify_resource_subscribers("gym://state", state_payload)

        result_payload = {
            "observation": obs,
            "info": info,
        }

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result_payload, indent=2),
                }
            ],
            **result_payload,
        }

    async def _tool_gym_action_space(self) -> dict[str, Any]:
        """Retrieve action space specification and boundaries."""
        if not self.is_initialized or self._env is None:
            raise AdapterError("GymnasiumAdapter is not initialized. Call initialize() first.")

        space_info = self._env.action_space_info()
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(space_info, indent=2),
                }
            ],
            "action_space": space_info,
        }

    async def _tool_gym_observation_space(self) -> dict[str, Any]:
        """Retrieve observation space specification and boundaries."""
        if not self.is_initialized or self._env is None:
            raise AdapterError("GymnasiumAdapter is not initialized. Call initialize() first.")

        space_info = self._env.observation_space_info()
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(space_info, indent=2),
                }
            ],
            "observation_space": space_info,
        }

    async def _tool_gym_render(
        self, format: Literal["png", "jpeg"] = "png"  # noqa: A002
    ) -> dict[str, Any]:
        """Render current environment frame and return as base64 image."""
        if not self.is_initialized or self._env is None:
            raise AdapterError("GymnasiumAdapter is not initialized. Call initialize() first.")

        frame = self._env.render()
        image_bytes = encode_image(frame, image_format=format)
        b64_str = image_to_base64(image_bytes)
        mime_type = f"image/{format}"

        return {
            "isError": False,
            "content": [
                {
                    "type": "image",
                    "data": b64_str,
                    "mimeType": mime_type,
                }
            ],
            "image_base64": b64_str,
            "mime_type": mime_type,
        }

    # -------------------------------------------------------------------------
    # Resource Readers
    # -------------------------------------------------------------------------

    async def _resource_observation(self) -> dict[str, Any]:
        """Resource reader for gym://observation."""
        return self._get_observation_payload()

    async def _resource_state(self) -> dict[str, Any]:
        """Resource reader for gym://state."""
        return self._get_state_payload()

    # -------------------------------------------------------------------------
    # Prompt Generator
    # -------------------------------------------------------------------------

    async def _prompt_gym_policy_optimization(
        self,
        env_id: str = "CartPole-v1",
        objective: str = "Maximize cumulative episode reward while avoiding termination",
    ) -> list[dict[str, Any]]:
        """Prompt generator for gym_policy_optimization."""
        prompt_text = (
            "You are an autonomous reinforcement learning policy optimization agent controlling a "
            f"Gymnasium environment.\nEnvironment: {env_id}\nObjective: {objective}\n\n"
            "Operational Protocol:\n"
            "1. Introspection: Call `gym_action_space()` and `gym_observation_space()` to inspect "
            "action types, valid bounds, and observation vector definitions.\n"
            "2. Episode Initialization: Call `gym_reset(seed=...)` to begin an episode and obtain "
            "the initial observation state vector.\n"
            "3. Decision Loop:\n"
            "   a. Inspect current observation vector via tool return or `gym://observation`.\n"
            "   b. Read cumulative metrics, step count, and spaces via `gym://state`.\n"
            "   c. Select action based on physics principles, heuristics, or policy optimization.\n"
            "   d. Call `gym_step(action)` to execute transition and obtain next observation, "
            "reward, and status flags.\n"
            "4. Termination Handling: If `terminated` is true (failure or goal achieved) or "
            "`truncated` is true (step limit reached), log metrics and call `gym_reset()`.\n"
            "5. Visual Verification: Call `gym_render(format='png')` when visual grounding "
            "is needed.\n"
            "6. CartPole-v1 Dynamics Guide: Observation is [cart_position, cart_velocity, "
            "pole_angle, pole_angular_velocity]. Actions are 0 (push left) and 1 (push right). "
            "Balance the pole by pushing the cart toward the pole's tilt direction."
        )
        return [{"role": "user", "content": {"type": "text", "text": prompt_text}}]

    # -------------------------------------------------------------------------
    # Registry Bindings
    # -------------------------------------------------------------------------

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register Gymnasium action, reset, space, and render tools."""
        registry.register(
            name="gym_step",
            handler=self._tool_gym_step,
            description=(
                "Step the active Gymnasium environment by executing an action, returning "
                "observation vector, scalar reward, terminated flag, truncated flag, and info."
            ),
            input_model=GymStepInput,
        )
        registry.register(
            name="gym_reset",
            handler=self._tool_gym_reset,
            description=(
                "Reset the Gymnasium environment to its initial state, returning the initial "
                "observation vector and state info."
            ),
            input_model=GymResetInput,
        )
        registry.register(
            name="gym_action_space",
            handler=self._tool_gym_action_space,
            description=(
                "Retrieve the specification, bounds, shape, and type of the environment "
                "action space."
            ),
            input_model=GymActionSpaceInput,
        )
        registry.register(
            name="gym_observation_space",
            handler=self._tool_gym_observation_space,
            description=(
                "Retrieve the specification, bounds, shape, and type of the environment "
                "observation space."
            ),
            input_model=GymObservationSpaceInput,
        )
        registry.register(
            name="gym_render",
            handler=self._tool_gym_render,
            description=(
                "Render current environment state and return frame as base64 encoded image."
            ),
            input_model=GymRenderInput,
        )

    def register_resources(self, registry: ResourceRegistry) -> None:
        """Register live reactive resources for observation and state telemetry."""
        registry.register(
            uri="gym://observation",
            reader=self._resource_observation,
            name="Gymnasium Current Observation",
            description=(
                "Real-time observation vector and state metadata from current environment step"
            ),
            mime_type="application/json",
        )
        registry.register(
            uri="gym://state",
            reader=self._resource_state,
            name="Gymnasium Environment State",
            description=(
                "Detailed environment metrics including episode count, step count, "
                "cumulative reward, and spaces"
            ),
            mime_type="application/json",
        )

    def register_prompts(self, registry: PromptRegistry) -> None:
        """Register strategic reinforcement learning scaffolding prompts."""
        registry.register(
            name="gym_policy_optimization",
            generator=self._prompt_gym_policy_optimization,
            description=(
                "Strategic reinforcement learning scaffold for policy optimization and action "
                "selection"
            ),
            arguments=[
                {
                    "name": "env_id",
                    "description": "Environment identifier (e.g. 'CartPole-v1')",
                    "required": False,
                },
                {
                    "name": "objective",
                    "description": "RL optimization objective or performance target",
                    "required": False,
                },
            ],
        )
