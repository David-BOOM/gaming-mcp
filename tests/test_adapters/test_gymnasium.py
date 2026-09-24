"""Comprehensive test suite for GymnasiumAdapter and SimulatedCartPoleEnv."""

from __future__ import annotations

import base64
import io
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from gaming_mcp.adapters.gymnasium import (
    GymnasiumAdapter,
    SimulatedCartPoleEnv,
    probe_gymnasium_backend,
)
from gaming_mcp.config import GamingMCPConfig, GymnasiumConfig
from gaming_mcp.core.exceptions import AdapterError
from gaming_mcp.server import GamingMCPServer

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def sim_adapter() -> GymnasiumAdapter:
    """Fixture providing an uninitialized GymnasiumAdapter in simulated mode."""
    config = GamingMCPConfig()
    config.adapters.gymnasium = GymnasiumConfig(
        env_id="CartPole-v1",
        render_mode="rgb_array",
        max_episode_steps=100,
        mock_mode=True,
    )
    return GymnasiumAdapter(config=config)


# -----------------------------------------------------------------------------
# Metadata & Initialization Tests
# -----------------------------------------------------------------------------


def test_gymnasium_adapter_metadata() -> None:
    """Verify GymnasiumAdapter metadata conforms to SPI standards."""
    adapter = GymnasiumAdapter()
    meta = adapter.metadata
    assert meta.id == "gymnasium"
    assert meta.display_name == "OpenAI Gymnasium RL Adapter"
    assert meta.version == "0.1.0"
    assert meta.requires_display is False
    assert meta.requires_admin_privileges is False
    assert "win32" in meta.supported_platforms
    assert "linux" in meta.supported_platforms
    assert "darwin" in meta.supported_platforms


@pytest.mark.asyncio
async def test_gymnasium_initialization_simulated_mode(sim_adapter: GymnasiumAdapter) -> None:
    """Verify initialization in simulated / mock mode."""
    assert sim_adapter.is_initialized is False
    await sim_adapter.initialize()
    assert sim_adapter.is_initialized is True
    assert sim_adapter.is_simulated is True
    assert sim_adapter.backend == "simulated"
    assert sim_adapter.env_id == "CartPole-v1"

    health = await sim_adapter.health_check()
    assert health["adapter_id"] == "gymnasium"
    assert health["status"] == "healthy"
    assert health["backend"] == "simulated"
    assert health["is_simulated"] is True
    assert health["step_count"] == 0
    assert health["cumulative_reward"] == 0.0

    await sim_adapter.shutdown()
    assert sim_adapter.is_initialized is False


@pytest.mark.asyncio
async def test_gymnasium_custom_environment_injection() -> None:
    """Verify initialization with an externally injected custom environment."""
    mock_env = MagicMock()
    mock_env.reset.return_value = ([0.0, 0.0, 0.0, 0.0], {"custom": True})
    mock_env.step.return_value = ([0.1, 0.0, 0.1, 0.0], 1.0, False, False, {})
    mock_env.action_space_info.return_value = {"type": "Discrete", "n": 2}
    mock_env.observation_space_info.return_value = {"type": "Box", "shape": [4]}
    mock_env.render.return_value = np.zeros((100, 100, 3), dtype=np.uint8)

    adapter = GymnasiumAdapter(custom_env=mock_env)
    await adapter.initialize()
    assert adapter.is_initialized is True
    assert adapter.backend == "custom"
    assert adapter.is_simulated is False

    reset_res = await adapter._tool_gym_reset(seed=99)
    assert reset_res["observation"] == [0.0, 0.0, 0.0, 0.0]
    assert reset_res["info"] == {"custom": True}

    step_res = await adapter._tool_gym_step(action=1)
    assert step_res["reward"] == 1.0
    assert step_res["observation"] == [0.1, 0.0, 0.1, 0.0]

    await adapter.shutdown()
    mock_env.close.assert_called_once()


# -----------------------------------------------------------------------------
# Simulated CartPole-v1 Unit Tests
# -----------------------------------------------------------------------------


def test_simulated_cartpole_reset_and_determinism() -> None:
    """Verify reset reproducibility with seeds and bounds compliance."""
    env = SimulatedCartPoleEnv(max_episode_steps=50)

    # Deterministic reset with identical seeds
    obs1, info1 = env.reset(seed=42)
    obs2, _info2 = env.reset(seed=42)
    assert obs1 == obs2
    assert info1.get("seed") == 42
    assert len(obs1) == 4
    for val in obs1:
        assert -0.05 <= val <= 0.05

    # Reset with different seeds should vary
    obs3, _ = env.reset(seed=999)
    assert obs1 != obs3


def test_simulated_cartpole_step_physics() -> None:
    """Verify CartPole physics calculations for discrete push actions."""
    env = SimulatedCartPoleEnv(max_episode_steps=100)
    _obs_init, _ = env.reset(seed=123)

    # Step action 1 (push right: positive force)
    obs_step1, reward1, term1, trunc1, info1 = env.step(1)
    assert len(obs_step1) == 4
    assert reward1 == 1.0
    assert term1 is False
    assert trunc1 is False
    assert info1["step_count"] == 1
    assert info1["cumulative_reward"] == 1.0

    # Step action 0 (push left: negative force)
    _obs_step2, reward2, _term2, _trunc2, info2 = env.step(0)
    assert reward2 == 1.0
    assert info2["step_count"] == 2
    assert info2["cumulative_reward"] == 2.0


def test_simulated_cartpole_termination_and_truncation() -> None:
    """Verify termination thresholds (position and angle) and truncation limits."""
    env = SimulatedCartPoleEnv(max_episode_steps=5)
    env.reset(seed=1)

    # Force position out of bounds (> 2.4)
    env.state = [2.5, 0.0, 0.0, 0.0]
    _obs, _reward, terminated, truncated, _ = env.step(0)
    assert terminated is True
    assert truncated is False

    # Force pole angle out of bounds (> 12 degrees ~ 0.2094 rad)
    env.reset(seed=1)
    env.state = [0.0, 0.0, 0.25, 0.0]
    _obs, _reward, terminated, _truncated, _ = env.step(0)
    assert terminated is True

    # Truncation when reaching max_episode_steps without falling
    env = SimulatedCartPoleEnv(max_episode_steps=3)
    env.reset(seed=1)
    env.state = [0.0, 0.0, 0.0, 0.0]

    _, _, term, trunc, _ = env.step(0)
    assert term is False and trunc is False
    _, _, term, trunc, _ = env.step(1)
    assert term is False and trunc is False
    _, _, term, trunc, info = env.step(0)
    assert trunc is True
    assert term is False
    assert info["step_count"] == 3


def test_simulated_cartpole_invalid_actions() -> None:
    """Verify rejection of invalid actions."""
    env = SimulatedCartPoleEnv()

    # Step before reset
    with pytest.raises(AdapterError, match="Environment has not been reset"):
        env.step(0)

    env.reset()

    # Invalid action integer
    with pytest.raises(AdapterError, match="out of bounds"):
        env.step(2)

    # Invalid action type
    with pytest.raises(AdapterError, match="Invalid action"):
        env.step([1, 2, 3])


def test_simulated_cartpole_rendering() -> None:
    """Verify simulated CartPole render produces a valid RGB image array."""
    env = SimulatedCartPoleEnv()
    env.reset(seed=42)
    frame = env.render()
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (400, 600, 3)
    assert frame.dtype == np.uint8


# -----------------------------------------------------------------------------
# Adapter Tool Execution Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_tool_spaces(sim_adapter: GymnasiumAdapter) -> None:
    """Verify gym_action_space and gym_observation_space tool handlers."""
    await sim_adapter.initialize()

    # Action space
    action_space_res = await sim_adapter._tool_gym_action_space()
    assert action_space_res["isError"] is False
    act_spec = action_space_res["action_space"]
    assert act_spec["type"] == "Discrete"
    assert act_spec["n"] == 2
    assert "content" in action_space_res

    # Observation space
    obs_space_res = await sim_adapter._tool_gym_observation_space()
    assert obs_space_res["isError"] is False
    obs_spec = obs_space_res["observation_space"]
    assert obs_spec["type"] == "Box"
    assert obs_spec["shape"] == [4]
    assert len(obs_spec["low"]) == 4
    assert len(obs_spec["high"]) == 4
    assert "cart_position" in obs_spec["names"]

    await sim_adapter.shutdown()


@pytest.mark.asyncio
async def test_adapter_tool_reset_and_step_cycle(sim_adapter: GymnasiumAdapter) -> None:
    """Verify reset and step tool workflows."""
    await sim_adapter.initialize()

    # Reset
    reset_res = await sim_adapter._tool_gym_reset(seed=100)
    assert reset_res["isError"] is False
    assert len(reset_res["observation"]) == 4
    assert sim_adapter.last_observation == reset_res["observation"]
    assert sim_adapter.episode_count == 1
    assert sim_adapter.step_count == 0

    # Step with integer action
    step1_res = await sim_adapter._tool_gym_step(action=1)
    assert step1_res["isError"] is False
    assert step1_res["reward"] == 1.0
    assert step1_res["terminated"] is False
    assert sim_adapter.step_count == 1
    assert sim_adapter.cumulative_reward == 1.0

    # Step with single-element list action
    step2_res = await sim_adapter._tool_gym_step(action=[0])
    assert step2_res["isError"] is False
    assert step2_res["reward"] == 1.0
    assert sim_adapter.step_count == 2
    assert sim_adapter.cumulative_reward == 2.0

    await sim_adapter.shutdown()


@pytest.mark.asyncio
async def test_adapter_tool_render_png_and_jpeg(sim_adapter: GymnasiumAdapter) -> None:
    """Verify gym_render tool produces valid base64 PNG and JPEG representations."""
    await sim_adapter.initialize()
    await sim_adapter._tool_gym_reset(seed=55)

    # PNG render
    png_res = await sim_adapter._tool_gym_render(format="png")
    assert png_res["isError"] is False
    assert png_res["mime_type"] == "image/png"
    b64_png = png_res["image_base64"]
    assert isinstance(b64_png, str) and len(b64_png) > 100

    # Verify PNG decodable
    png_bytes = base64.b64decode(b64_png)
    img_png = Image.open(io.BytesIO(png_bytes))
    assert img_png.size == (600, 400)
    assert img_png.format == "PNG"

    # JPEG render
    jpeg_res = await sim_adapter._tool_gym_render(format="jpeg")
    assert jpeg_res["isError"] is False
    assert jpeg_res["mime_type"] == "image/jpeg"
    b64_jpeg = jpeg_res["image_base64"]
    jpeg_bytes = base64.b64decode(b64_jpeg)
    img_jpeg = Image.open(io.BytesIO(jpeg_bytes))
    assert img_jpeg.size == (600, 400)
    assert img_jpeg.format == "JPEG"

    await sim_adapter.shutdown()


# -----------------------------------------------------------------------------
# Resources & Prompts Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_resources_and_prompts(sim_adapter: GymnasiumAdapter) -> None:
    """Verify resource readers and prompt generation."""
    await sim_adapter.initialize()
    await sim_adapter._tool_gym_reset(seed=12)
    await sim_adapter._tool_gym_step(action=1)

    # gym://observation resource
    obs_payload = await sim_adapter._resource_observation()
    assert obs_payload["env_id"] == "CartPole-v1"
    assert len(obs_payload["observation"]) == 4
    assert obs_payload["step_count"] == 1
    assert obs_payload["episode_count"] == 1

    # gym://state resource
    state_payload = await sim_adapter._resource_state()
    assert state_payload["env_id"] == "CartPole-v1"
    assert state_payload["backend"] == "simulated"
    assert state_payload["is_simulated"] is True
    assert state_payload["step_count"] == 1
    assert state_payload["cumulative_reward"] == 1.0
    assert state_payload["action_space"]["type"] == "Discrete"
    assert state_payload["observation_space"]["type"] == "Box"

    # gym_policy_optimization prompt
    prompt_res = await sim_adapter._prompt_gym_policy_optimization(
        env_id="CartPole-v1", objective="Reach 500 reward without falling"
    )
    assert len(prompt_res) == 1
    assert prompt_res[0]["role"] == "user"
    content_text = prompt_res[0]["content"]["text"]
    assert "CartPole-v1" in content_text
    assert "Reach 500 reward" in content_text
    assert "gym_step" in content_text

    await sim_adapter.shutdown()


# -----------------------------------------------------------------------------
# Reactive Subscriptions Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_reactive_subscriptions(sim_adapter: GymnasiumAdapter) -> None:
    """Verify push notifications to subscribers on reset and step."""
    await sim_adapter.initialize()

    obs_events: list[dict[str, Any]] = []
    state_events: list[dict[str, Any]] = []

    def on_obs(_uri: str, payload: dict[str, Any]) -> None:
        obs_events.append(payload)

    def on_state(_uri: str, payload: dict[str, Any]) -> None:
        state_events.append(payload)

    sim_adapter.subscribe_resource("gym://observation", on_obs)
    sim_adapter.subscribe_resource("gym://state", on_state)

    # Reset triggers notification
    await sim_adapter._tool_gym_reset(seed=1)
    assert len(obs_events) == 1
    assert len(state_events) == 1
    assert obs_events[0]["step_count"] == 0

    # Step triggers notification
    await sim_adapter._tool_gym_step(action=1)
    assert len(obs_events) == 2
    assert len(state_events) == 2
    assert obs_events[1]["step_count"] == 1
    assert state_events[1]["cumulative_reward"] == 1.0

    # Unsubscribe
    sim_adapter.unsubscribe_resource("gym://observation", on_obs)
    await sim_adapter._tool_gym_step(action=0)
    assert len(obs_events) == 2  # No new event
    assert len(state_events) == 3  # Still subscribed

    await sim_adapter.shutdown()


# -----------------------------------------------------------------------------
# Error Handling Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_error_handling_uninitialized(sim_adapter: GymnasiumAdapter) -> None:
    """Verify tools reject calls before initialization."""
    with pytest.raises(AdapterError, match="not initialized"):
        await sim_adapter._tool_gym_step(action=0)

    with pytest.raises(AdapterError, match="not initialized"):
        await sim_adapter._tool_gym_reset()

    with pytest.raises(AdapterError, match="not initialized"):
        await sim_adapter._tool_gym_action_space()

    with pytest.raises(AdapterError, match="not initialized"):
        await sim_adapter._tool_gym_observation_space()

    with pytest.raises(AdapterError, match="not initialized"):
        await sim_adapter._tool_gym_render()


@pytest.mark.asyncio
async def test_adapter_error_handling_unreset_or_invalid_action(
    sim_adapter: GymnasiumAdapter,
) -> None:
    """Verify tool error handling when step is called without reset or with bad action."""
    await sim_adapter.initialize()

    # Step before reset
    with pytest.raises(AdapterError, match="Environment has not been reset"):
        await sim_adapter._tool_gym_step(action=0)

    # Reset then invalid action
    await sim_adapter._tool_gym_reset(seed=1)
    with pytest.raises(AdapterError, match="out of bounds"):
        await sim_adapter._tool_gym_step(action=99)

    await sim_adapter.shutdown()


# -----------------------------------------------------------------------------
# Capability Probing & Native Fallback Tests
# -----------------------------------------------------------------------------


def test_probe_gymnasium_backend_modes() -> None:
    """Verify probe_gymnasium_backend honors mock_mode and import fallbacks."""
    assert probe_gymnasium_backend(mock_mode=True) == "simulated"

    # Test when gymnasium is simulated
    with patch("importlib.import_module") as mock_import:
        # Neither exists
        mock_import.side_effect = ImportError("No module")
        assert probe_gymnasium_backend(mock_mode=False) == "simulated"

        # Gymnasium exists
        mock_import.side_effect = None
        mock_import.return_value = MagicMock()
        assert probe_gymnasium_backend(mock_mode=False) == "gymnasium"


@pytest.mark.asyncio
async def test_native_gymnasium_initialization_fallback() -> None:
    """Verify that failure in native gymnasium initialization gracefully falls back to simulated."""
    config = GamingMCPConfig()
    config.adapters.gymnasium = GymnasiumConfig(
        env_id="CartPole-v1",
        mock_mode=False,
    )
    adapter = GymnasiumAdapter(config=config)

    with (
        patch(
            "gaming_mcp.adapters.gymnasium.probe_gymnasium_backend",
            return_value="gymnasium",
        ),
        patch(
            "gaming_mcp.adapters.gymnasium.NativeGymnasiumEnv",
            side_effect=Exception("Failed gym make"),
        ),
    ):
        await adapter.initialize()
        assert adapter.is_initialized is True
        assert adapter.is_simulated is True
        assert adapter.backend == "simulated"
        await adapter.shutdown()


@pytest.mark.asyncio
async def test_native_gymnasium_wrapper_step_and_spaces() -> None:
    """Verify NativeGymnasiumEnv wrapper translating Gym calls."""
    mock_env = MagicMock()
    mock_env.reset.return_value = (
        np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32),
        {"native": True},
    )
    mock_env.step.return_value = (
        np.array([0.2, 0.3, 0.4, 0.5], dtype=np.float32),
        1.0,
        False,
        False,
        {"info_key": "info_val"},
    )
    mock_env.render.return_value = np.zeros((200, 200, 3), dtype=np.uint8)

    mock_action_space = MagicMock()
    mock_action_space.shape = ()
    mock_action_space.dtype = np.int64
    mock_action_space.n = 2
    type(mock_action_space).__name__ = "Discrete"
    mock_env.action_space = mock_action_space

    mock_obs_space = MagicMock()
    mock_obs_space.shape = (4,)
    mock_obs_space.dtype = np.float32
    mock_obs_space.low = np.array([-1.0, -1.0, -1.0, -1.0])
    mock_obs_space.high = np.array([1.0, 1.0, 1.0, 1.0])
    type(mock_obs_space).__name__ = "Box"
    mock_env.observation_space = mock_obs_space

    with patch("importlib.import_module") as mock_import:
        mock_gym = MagicMock()
        mock_gym.make.return_value = mock_env
        mock_import.return_value = mock_gym

        from gaming_mcp.adapters.gymnasium import NativeGymnasiumEnv

        wrapper = NativeGymnasiumEnv(env_id="CartPole-v1")
        obs, info = wrapper.reset(seed=10)
        assert obs == pytest.approx([0.1, 0.2, 0.3, 0.4])
        assert info == {"native": True}

        step_obs, reward, term, trunc, step_info = wrapper.step(1)
        assert step_obs == pytest.approx([0.2, 0.3, 0.4, 0.5])
        assert reward == 1.0
        assert term is False
        assert trunc is False
        assert step_info == {"info_key": "info_val"}

        act_info = wrapper.action_space_info()
        assert act_info["type"] == "Discrete"
        assert act_info["n"] == 2

        obs_info = wrapper.observation_space_info()
        assert obs_info["type"] == "Box"
        assert obs_info["shape"] == [4]

        frame = wrapper.render()
        assert frame.shape == (200, 200, 3)

        wrapper.close()
        mock_env.close.assert_called_once()


# -----------------------------------------------------------------------------
# Router & Server Integration Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gymnasium_adapter_in_router_and_server() -> None:
    """Verify hot-swapping into GymnasiumAdapter via AdapterRouter on GamingMCPServer."""
    server = GamingMCPServer()
    adapter = GymnasiumAdapter()
    server.router.register_adapter(adapter)

    # Switch to gymnasium adapter
    switched = await server.router.switch_adapter("gymnasium", server)
    assert switched.metadata.id == "gymnasium"
    assert server.router.active_adapter_id == "gymnasium"

    # Verify tools registered in server
    assert server.tools.get("gym_step") is not None
    assert server.tools.get("gym_reset") is not None
    assert server.tools.get("gym_action_space") is not None
    assert server.tools.get("gym_observation_space") is not None
    assert server.tools.get("gym_render") is not None

    # Verify resources registered in server
    assert server.resources.get("gym://observation") is not None
    assert server.resources.get("gym://state") is not None

    # Verify prompt registered in server
    assert server.prompts.get("gym_policy_optimization") is not None

    # Execute reset tool through registry
    reset_exec = await server.tools.execute("gym_reset", {"seed": 77})
    assert reset_exec["isError"] is False
    assert "observation" in reset_exec

    # Execute step tool through registry
    step_exec = await server.tools.execute("gym_step", {"action": 0})
    assert step_exec["isError"] is False
    assert step_exec["reward"] == 1.0

    # Read resources through registry
    obs_read = await server.resources.read("gym://observation")
    assert obs_read.get("isError") is not True
    assert "contents" in obs_read

    state_read = await server.resources.read("gym://state")
    assert state_read.get("isError") is not True
    assert "contents" in state_read

    # Render prompt through registry
    prompt_res = await server.prompts.render(
        "gym_policy_optimization", {"env_id": "CartPole-v1", "objective": "Balance pole"}
    )
    assert len(prompt_res) == 1
    assert "CartPole-v1" in prompt_res[0]["content"]["text"]

    # Detach / unregister
    await server.router.unregister_adapter("gymnasium", server)
    assert server.router.active_adapter_id is None
    assert server.tools.get("gym_step") is None
