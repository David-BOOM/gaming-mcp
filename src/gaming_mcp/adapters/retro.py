"""Retro & Emulation Adapter for Gaming MCP Server.

Provides frame-perfect control, state serialization, memory introspection,
and frame buffer streaming for Libretro cores and stable-retro environments (NES, SNES, Genesis).
Seamlessly operates in high-fidelity simulation mode when native emulation libraries or ROMs
are unavailable.
"""

from __future__ import annotations

import importlib
import logging
import pickle
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.config import GamingMCPConfig, RetroConfig
from gaming_mcp.core.exceptions import AdapterError
from gaming_mcp.utils.image import encode_image

if TYPE_CHECKING:
    from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry

logger = logging.getLogger("gaming_mcp.adapters.retro")

VALID_RETRO_BUTTONS: set[str] = {
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "A",
    "B",
    "X",
    "Y",
    "L",
    "R",
    "SELECT",
    "START",
}


# -----------------------------------------------------------------------------
# Tool Input Schemas
# -----------------------------------------------------------------------------


class RetroSendPadInput(BaseModel):
    """Input parameters for the retro_send_pad tool."""

    buttons: list[str] = Field(
        ...,
        description=(
            "List of controller buttons to depress (e.g. ['A', 'B', 'UP', 'DOWN', "
            "'LEFT', 'RIGHT', 'SELECT', 'START', 'X', 'Y', 'L', 'R'])."
        ),
    )
    frames: int = Field(
        default=4,
        ge=1,
        le=300,
        description="Number of emulation frames to hold the pad bitmask before release.",
    )


class RetroSaveStateInput(BaseModel):
    """Input parameters for the retro_save_state tool."""

    slot_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique slot identifier for the saved state snapshot.",
    )


class RetroLoadStateInput(BaseModel):
    """Input parameters for the retro_load_state tool."""

    slot_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Slot identifier of the state snapshot to restore.",
    )


class RetroReadRamInput(BaseModel):
    """Input parameters for the retro_read_ram tool."""

    address: int = Field(
        ...,
        ge=0,
        description="Starting RAM memory address (decimal or 0-indexed byte offset).",
    )
    length: int = Field(
        ...,
        ge=1,
        le=65536,
        description="Number of sequential bytes to read from memory.",
    )


# -----------------------------------------------------------------------------
# Abstract Retro Backend
# -----------------------------------------------------------------------------


class BaseRetroBackend(ABC):
    """Abstract interface decoupling the adapter from specific emulation libraries."""

    @property
    @abstractmethod
    def is_simulated(self) -> bool:
        """Return True if backend is running in high-fidelity mock/simulation mode."""
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Return backend identifier name (e.g. 'stable_retro', 'retro', 'simulation')."""
        ...

    @property
    @abstractmethod
    def game_title(self) -> str:
        """Return target game title."""
        ...

    @property
    @abstractmethod
    def ram_size(self) -> int:
        """Return size of readable RAM in bytes."""
        ...

    @property
    @abstractmethod
    def frame_count(self) -> int:
        """Return total elapsed emulation frame count."""
        ...

    @property
    @abstractmethod
    def saved_states(self) -> dict[str, Any]:
        """Return mapping of saved state slots."""
        ...

    @abstractmethod
    def reset(self) -> np.ndarray:
        """Reset emulation environment to initial state and return frame buffer."""
        ...

    @abstractmethod
    def step(self, buttons: list[str], frames: int = 1) -> tuple[np.ndarray, dict[str, Any]]:
        """Actuate gamepad buttons for frame duration and return (frame, variables)."""
        ...

    @abstractmethod
    def save_state(self, slot_name: str) -> bytes:
        """Serialize current emulator snapshot to the specified slot and return raw bytes."""
        ...

    @abstractmethod
    def load_state(self, slot_name: str) -> None:
        """Restore emulator snapshot from the specified slot."""
        ...

    @abstractmethod
    def read_ram(self, address: int, length: int) -> bytes:
        """Read sequential memory bytes from emulator RAM."""
        ...

    @abstractmethod
    def get_variables(self) -> dict[str, Any]:
        """Return structured dictionary of pre-mapped game memory variables."""
        ...

    @abstractmethod
    def get_frame(self) -> np.ndarray:
        """Return current visual frame buffer as uint8 RGB numpy array."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release emulator resources and clean up buffers."""
        ...


# -----------------------------------------------------------------------------
# High-Fidelity Simulated NES Core (Super Mario Bros)
# -----------------------------------------------------------------------------


class SimulatedRetroCore(BaseRetroBackend):
    """High-fidelity simulated NES core for Super Mario Bros.

    Features a simulated 256x240 RGB frame buffer, dynamic physics, jumping kinematics,
    score/lives/timer telemetry, and byte-accurate RAM register mappings matching
    NES Super Mario Bros memory layout.
    """

    # NES Super Mario Bros RAM register offsets
    RAM_ADDR_PLAYER_X_SCREEN = 0x0086
    RAM_ADDR_PLAYER_PAGE = 0x006D
    RAM_ADDR_PLAYER_Y = 0x00CE
    RAM_ADDR_LIVES = 0x075A
    RAM_ADDR_COINS = 0x075E
    RAM_ADDR_WORLD = 0x075F
    RAM_ADDR_LEVEL = 0x075C
    RAM_ADDR_SCORE_HUNDRED_THOUSANDS = 0x07D7
    RAM_ADDR_SCORE_TEN_THOUSANDS = 0x07D8
    RAM_ADDR_SCORE_THOUSANDS = 0x07D9
    RAM_ADDR_SCORE_HUNDREDS = 0x07DA
    RAM_ADDR_SCORE_TENS = 0x07DB
    RAM_ADDR_SCORE_ONES = 0x07DC
    RAM_ADDR_TIMER_HUNDREDS = 0x07F8
    RAM_ADDR_TIMER_TENS = 0x07F9
    RAM_ADDR_TIMER_ONES = 0x07FA

    def __init__(self, game: str = "SuperMarioBros-Nes") -> None:
        self._game_title = game
        self._ram_capacity = 65536  # Full 64KB address space
        self._ram = bytearray(self._ram_capacity)
        self._saved_states: dict[str, dict[str, Any]] = {}
        self._total_frames = 0

        # Game state variables
        self.score = 0
        self.lives = 3
        self.x_pos = 40
        self.y_pos = 176
        self.timer = 400
        self.coins = 0
        self.world = "1-1"
        self.stage = 1
        self.game_state = "running"
        self.is_jumping = False
        self.jump_timer = 0
        self.facing = "right"

        self._frame: np.ndarray = np.zeros((240, 256, 3), dtype=np.uint8)
        self.reset()

    @property
    def is_simulated(self) -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "simulation"

    @property
    def game_title(self) -> str:
        return self._game_title

    @property
    def ram_size(self) -> int:
        return self._ram_capacity

    @property
    def frame_count(self) -> int:
        return self._total_frames

    @property
    def saved_states(self) -> dict[str, Any]:
        return self._saved_states

    def reset(self) -> np.ndarray:
        """Reset game variables, RAM, and render initial frame buffer."""
        self.score = 0
        self.lives = 3
        self.x_pos = 40
        self.y_pos = 176
        self.timer = 400
        self.coins = 0
        self.world = "1-1"
        self.stage = 1
        self.game_state = "running"
        self.is_jumping = False
        self.jump_timer = 0
        self.facing = "right"
        self._total_frames = 0

        self._sync_ram()
        self._render_frame()
        return self._frame

    def _sync_ram(self) -> None:
        """Synchronize high-level game variables into RAM registers."""
        self._ram[self.RAM_ADDR_LIVES] = max(0, min(255, self.lives))
        self._ram[self.RAM_ADDR_COINS] = max(0, min(99, self.coins))
        self._ram[self.RAM_ADDR_PLAYER_X_SCREEN] = self.x_pos & 0xFF
        self._ram[self.RAM_ADDR_PLAYER_PAGE] = (self.x_pos >> 8) & 0xFF
        self._ram[self.RAM_ADDR_PLAYER_Y] = max(0, min(255, self.y_pos))
        self._ram[self.RAM_ADDR_WORLD] = 0
        self._ram[self.RAM_ADDR_LEVEL] = 0

        # Score BCD digits
        sc = max(0, self.score)
        self._ram[self.RAM_ADDR_SCORE_HUNDRED_THOUSANDS] = (sc // 100000) % 10
        self._ram[self.RAM_ADDR_SCORE_TEN_THOUSANDS] = (sc // 10000) % 10
        self._ram[self.RAM_ADDR_SCORE_THOUSANDS] = (sc // 1000) % 10
        self._ram[self.RAM_ADDR_SCORE_HUNDREDS] = (sc // 100) % 10
        self._ram[self.RAM_ADDR_SCORE_TENS] = (sc // 10) % 10
        self._ram[self.RAM_ADDR_SCORE_ONES] = sc % 10

        # Timer BCD digits
        tm = max(0, self.timer)
        self._ram[self.RAM_ADDR_TIMER_HUNDREDS] = (tm // 100) % 10
        self._ram[self.RAM_ADDR_TIMER_TENS] = (tm // 10) % 10
        self._ram[self.RAM_ADDR_TIMER_ONES] = tm % 10

    def step(self, buttons: list[str], frames: int = 1) -> tuple[np.ndarray, dict[str, Any]]:
        """Advance simulation by the given frame count with specified buttons held."""
        normalized_buttons = {b.strip().upper() for b in buttons}

        # Check for invalid button inputs
        unknown_buttons = normalized_buttons - VALID_RETRO_BUTTONS
        if unknown_buttons:
            raise AdapterError(
                f"Invalid gamepad buttons: {sorted(unknown_buttons)}. "
                f"Supported buttons: {sorted(VALID_RETRO_BUTTONS)}"
            )

        for _ in range(frames):
            self._total_frames += 1

            if "START" in normalized_buttons:
                if self.game_state == "running":
                    self.game_state = "paused"
                elif self.game_state == "paused":
                    self.game_state = "running"

            if self.game_state == "running":
                # Movement speed: B button is dash/sprint
                speed = 4 if "B" in normalized_buttons else 2

                if "RIGHT" in normalized_buttons:
                    self.x_pos += speed
                    self.score += speed
                    self.facing = "right"

                if "LEFT" in normalized_buttons:
                    self.x_pos = max(0, self.x_pos - speed)
                    self.facing = "left"

                # Jump initiation
                if "A" in normalized_buttons and not self.is_jumping and self.y_pos >= 176:
                    self.is_jumping = True
                    self.jump_timer = 14

                # Jump trajectory physics
                if self.is_jumping:
                    if self.jump_timer > 0:
                        self.y_pos = max(90, self.y_pos - 6)
                        self.jump_timer -= 1
                    else:
                        self.y_pos = min(176, self.y_pos + 6)
                        if self.y_pos >= 176:
                            self.is_jumping = False
                            self.y_pos = 176

                # Coin collection milestones
                prev_x = self.x_pos - speed if "RIGHT" in normalized_buttons else self.x_pos
                if (self.x_pos // 64) > (prev_x // 64):
                    self.coins = (self.coins + 1) % 100
                    self.score += 200

                # Timer decrement (1 second per 60 frames)
                if self._total_frames % 60 == 0 and self.timer > 0:
                    self.timer -= 1
                    if self.timer == 0:
                        self.lives = max(0, self.lives - 1)
                        if self.lives > 0:
                            self.timer = 400
                            self.x_pos = 40
                            self.y_pos = 176
                        else:
                            self.game_state = "game_over"

        self._sync_ram()
        self._render_frame()
        return self._frame, self.get_variables()

    def _render_frame(self) -> None:
        """Render a synthetic 256x240 NES Super Mario Bros frame buffer."""
        # Sky blue background: NES color 0x22 / RGB(107, 136, 255)
        img = Image.new("RGB", (256, 240), (107, 136, 255))
        draw = ImageDraw.Draw(img)

        # Ground bricks at Y=208..240: RGB(200, 76, 12)
        draw.rectangle([(0, 208), (255, 240)], fill=(200, 76, 12))
        draw.line([(0, 208), (255, 208)], fill=(252, 188, 176), width=1)
        for gx in range(0, 256, 16):
            draw.line([(gx, 208), (gx, 240)], fill=(120, 40, 0), width=1)

        # Scenery: Warp Pipe (green RGB(0, 168, 0))
        pipe_screen_x = (180 - (self.x_pos // 2)) % 320 - 32
        if -40 <= pipe_screen_x <= 260:
            draw.rectangle(
                [(pipe_screen_x + 2, 168), (pipe_screen_x + 30, 208)],
                fill=(0, 168, 0),
                outline=(0, 80, 0),
            )
            draw.rectangle(
                [(pipe_screen_x, 152), (pipe_screen_x + 32, 168)],
                fill=(0, 168, 0),
                outline=(0, 80, 0),
            )

        # Clouds in sky
        draw.ellipse([(30, 40), (70, 56)], fill=(255, 255, 255))
        draw.ellipse([(160, 30), (210, 50)], fill=(255, 255, 255))

        # Mario character sprite
        # Screen X relative to current screen
        mario_x = max(16, min(224, (self.x_pos % 220) + 16))
        mario_y = self.y_pos

        # Hat and shirt: Red RGB(228, 0, 88)
        draw.rectangle(
            [(mario_x + 2, mario_y), (mario_x + 14, mario_y + 6)],
            fill=(228, 0, 88),
        )
        # Face: Skin RGB(252, 188, 176)
        draw.rectangle(
            [(mario_x + 4, mario_y + 6), (mario_x + 12, mario_y + 12)],
            fill=(252, 188, 176),
        )
        # Overalls: Blue RGB(0, 80, 200)
        draw.rectangle(
            [(mario_x + 2, mario_y + 12), (mario_x + 14, mario_y + 20)],
            fill=(0, 80, 200),
        )
        # Shoes: Brown RGB(136, 112, 0)
        draw.rectangle(
            [(mario_x, mario_y + 20), (mario_x + 16, mario_y + 24)],
            fill=(136, 112, 0),
        )

        # Top HUD Status Bar
        hud_score = f"{self.score:06d}"
        hud_coins = f"x{self.coins:02d}"
        hud_world = self.world
        hud_time = f"{self.timer:03d}"

        # Draw HUD labels
        draw.text((16, 8), "MARIO", fill=(255, 255, 255))
        draw.text((16, 18), hud_score, fill=(255, 255, 255))
        draw.text((90, 18), hud_coins, fill=(255, 255, 255))
        draw.text((140, 8), "WORLD", fill=(255, 255, 255))
        draw.text((146, 18), hud_world, fill=(255, 255, 255))
        draw.text((200, 8), "TIME", fill=(255, 255, 255))
        draw.text((206, 18), hud_time, fill=(255, 255, 255))

        if self.game_state == "paused":
            draw.text((110, 100), "PAUSE", fill=(255, 255, 255))
        elif self.game_state == "game_over":
            draw.text((96, 100), "GAME OVER", fill=(255, 255, 255))

        self._frame = np.array(img, dtype=np.uint8)

    def save_state(self, slot_name: str) -> bytes:
        """Serialize current emulator snapshot to memory."""
        snapshot = {
            "ram": bytes(self._ram),
            "score": self.score,
            "lives": self.lives,
            "x_pos": self.x_pos,
            "y_pos": self.y_pos,
            "timer": self.timer,
            "coins": self.coins,
            "world": self.world,
            "stage": self.stage,
            "game_state": self.game_state,
            "is_jumping": self.is_jumping,
            "jump_timer": self.jump_timer,
            "facing": self.facing,
            "total_frames": self._total_frames,
        }
        serialized = pickle.dumps(snapshot)
        self._saved_states[slot_name] = snapshot
        return serialized

    def load_state(self, slot_name: str) -> None:
        """Restore emulator snapshot from memory slot."""
        if slot_name not in self._saved_states:
            raise AdapterError(
                f"Saved state slot '{slot_name}' not found. "
                f"Available slots: {list(self._saved_states.keys())}"
            )

        snapshot = self._saved_states[slot_name]
        self._ram = bytearray(snapshot["ram"])
        self.score = snapshot["score"]
        self.lives = snapshot["lives"]
        self.x_pos = snapshot["x_pos"]
        self.y_pos = snapshot["y_pos"]
        self.timer = snapshot["timer"]
        self.coins = snapshot["coins"]
        self.world = snapshot["world"]
        self.stage = snapshot["stage"]
        self.game_state = snapshot["game_state"]
        self.is_jumping = snapshot["is_jumping"]
        self.jump_timer = snapshot["jump_timer"]
        self.facing = snapshot["facing"]
        self._total_frames = snapshot["total_frames"]

        self._sync_ram()
        self._render_frame()

    def read_ram(self, address: int, length: int) -> bytes:
        """Read sequential memory bytes with bounds checking."""
        if address < 0:
            raise AdapterError(f"RAM address {address} cannot be negative")
        if length <= 0:
            raise AdapterError(f"Read length {length} must be greater than zero")
        if address + length > self._ram_capacity:
            raise AdapterError(
                f"RAM read out of bounds: address 0x{address:04X} + length {length} "
                f"exceeds capacity 0x{self._ram_capacity:04X} bytes"
            )

        return bytes(self._ram[address : address + length])

    def get_variables(self) -> dict[str, Any]:
        """Return structured game telemetry variables."""
        return {
            "game": self._game_title,
            "score": self.score,
            "lives": self.lives,
            "x_pos": self.x_pos,
            "y_pos": self.y_pos,
            "timer": self.timer,
            "coins": self.coins,
            "world": self.world,
            "frame_count": self._total_frames,
            "status": self.game_state,
        }

    def get_frame(self) -> np.ndarray:
        """Return active 256x240 RGB frame buffer."""
        return self._frame

    def close(self) -> None:
        """Clean up buffers and clear memory."""
        self._saved_states.clear()


# -----------------------------------------------------------------------------
# Native Retro Backend (Libretro / Stable-Retro / Gymnasium-Retro)
# -----------------------------------------------------------------------------


class NativeRetroBackend(BaseRetroBackend):
    """Native Libretro emulator wrapper using stable_retro or retro packages."""

    def __init__(
        self,
        retro_module: Any,
        game: str = "SuperMarioBros-Nes",
        core: str = "fceumm",
    ) -> None:
        self._module = retro_module
        self._game_title = game
        self._core = core
        self._env: Any = None
        self._saved_states: dict[str, bytes] = {}
        self._total_frames = 0
        self._last_frame: np.ndarray = np.zeros((240, 256, 3), dtype=np.uint8)
        self._last_info: dict[str, Any] = {}

        # Create native retro environment
        try:
            self._env = self._module.make(game=self._game_title)
        except Exception as exc:
            raise AdapterError(
                f"Failed to initialize native retro environment for game '{game}': {exc}"
            ) from exc

        self.reset()

    @property
    def is_simulated(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return getattr(self._module, "__name__", "native_retro")

    @property
    def game_title(self) -> str:
        return self._game_title

    @property
    def ram_size(self) -> int:
        if self._env and hasattr(self._env, "get_ram"):
            ram = self._env.get_ram()
            return len(ram)
        return 65536

    @property
    def frame_count(self) -> int:
        return self._total_frames

    @property
    def saved_states(self) -> dict[str, Any]:
        return self._saved_states

    def reset(self) -> np.ndarray:
        if not self._env:
            return self._last_frame
        obs = self._env.reset()
        if isinstance(obs, tuple):
            obs = obs[0]
        self._last_frame = np.asarray(obs, dtype=np.uint8)
        self._total_frames = 0
        return self._last_frame

    def step(self, buttons: list[str], frames: int = 1) -> tuple[np.ndarray, dict[str, Any]]:
        if not self._env:
            raise AdapterError("Native retro environment is not initialized")

        normalized = {b.strip().upper() for b in buttons}
        # Build action multi-binary array according to env.buttons
        env_buttons = getattr(self._env, "buttons", [])
        action = [1 if btn in normalized else 0 for btn in env_buttons]

        for _ in range(frames):
            self._total_frames += 1
            step_result = self._env.step(action)
            # Support both Gymnasium 5-tuple and classic Gym 4-tuple
            if len(step_result) == 5:
                obs, _reward, _terminated, _truncated, info = step_result
            else:
                obs, _reward, _done, info = step_result

            self._last_frame = np.asarray(obs, dtype=np.uint8)
            self._last_info = info if isinstance(info, dict) else {}

        return self._last_frame, self.get_variables()

    def save_state(self, slot_name: str) -> bytes:
        if not self._env:
            raise AdapterError("Native retro environment is not initialized")
        em = getattr(self._env, "em", None)
        if em and hasattr(em, "get_state"):
            state_data = em.get_state()
            if not isinstance(state_data, bytes):
                state_data = bytes(state_data)
            self._saved_states[slot_name] = state_data
            return state_data

        raise AdapterError("Emulator core does not support get_state()")

    def load_state(self, slot_name: str) -> None:
        if slot_name not in self._saved_states:
            raise AdapterError(f"Saved state slot '{slot_name}' not found")

        state_data = self._saved_states[slot_name]
        em = getattr(self._env, "em", None)
        if em and hasattr(em, "set_state"):
            em.set_state(state_data)
            return

        raise AdapterError("Emulator core does not support set_state()")

    def read_ram(self, address: int, length: int) -> bytes:
        if not self._env or not hasattr(self._env, "get_ram"):
            raise AdapterError("Emulator RAM introspection is not available")

        ram = self._env.get_ram()
        ram_len = len(ram)
        if address < 0:
            raise AdapterError(f"RAM address {address} cannot be negative")
        if length <= 0:
            raise AdapterError(f"Read length {length} must be greater than zero")
        if address + length > ram_len:
            raise AdapterError(
                f"RAM read out of bounds: address 0x{address:04X} + length {length} "
                f"exceeds capacity {ram_len} bytes"
            )

        return bytes(ram[address : address + length])

    def get_variables(self) -> dict[str, Any]:
        vars_dict = dict(self._last_info)
        vars_dict["game"] = self._game_title
        vars_dict["frame_count"] = self._total_frames
        return vars_dict

    def get_frame(self) -> np.ndarray:
        return self._last_frame

    def close(self) -> None:
        if self._env:
            self._env.close()
            self._env = None
        self._saved_states.clear()


# -----------------------------------------------------------------------------
# Capability Probing Helper
# -----------------------------------------------------------------------------


def probe_retro_backend() -> tuple[str | None, Any]:
    """Probe system for installed retro emulation packages."""
    for mod_name in ("stable_retro", "retro"):
        try:
            mod = importlib.import_module(mod_name)
            return mod_name, mod
        except ImportError:
            continue
    return None, None


# -----------------------------------------------------------------------------
# Retro Game Adapter Implementation
# -----------------------------------------------------------------------------


class RetroAdapter(GameAdapter):
    """Model Context Protocol GameAdapter for Libretro and retro environments."""

    def __init__(
        self,
        config: GamingMCPConfig | None = None,
        backend: BaseRetroBackend | None = None,
    ) -> None:
        super().__init__(config or GamingMCPConfig())
        self._custom_backend = backend
        self.backend: BaseRetroBackend | None = None

    @property
    def metadata(self) -> AdapterMetadata:
        """Return adapter capability and requirement metadata."""
        return AdapterMetadata(
            id="retro",
            display_name="Retro & Emulation Adapter",
            version="0.1.0",
            description=(
                "Frame-perfect retro game emulation adapter for Libretro cores and "
                "stable-retro environments (NES, SNES, Genesis) with RAM introspection "
                "and state serialization."
            ),
            supported_platforms=["win32", "linux", "darwin"],
            requires_display=False,
            requires_admin_privileges=False,
        )

    async def initialize(self) -> None:
        """Asynchronously initialize emulator backend or simulated core."""
        if self.is_initialized:
            return

        retro_cfg: RetroConfig = self.config.adapters.retro

        # 1. Custom backend injected directly
        if self._custom_backend is not None:
            self.backend = self._custom_backend
            self.backend.reset()
            self.is_initialized = True
            logger.info("RetroAdapter initialized with custom backend")
            return

        # 2. Check if mock mode is forced via configuration
        if retro_cfg.mock_mode:
            logger.info("Initializing RetroAdapter in configured mock simulation mode")
            self.backend = SimulatedRetroCore(game=retro_cfg.game)
            self.backend.reset()
            self.is_initialized = True
            return

        # 3. Probe native libraries (stable_retro / retro)
        pkg_name, pkg_module = probe_retro_backend()
        if pkg_module is not None:
            try:
                logger.info("Found native retro library: %s. Initializing...", pkg_name)
                self.backend = NativeRetroBackend(
                    retro_module=pkg_module,
                    game=retro_cfg.game,
                    core=retro_cfg.core,
                )
                self.backend.reset()
                self.is_initialized = True
                logger.info("RetroAdapter initialized with native backend '%s'", pkg_name)
                return
            except Exception as exc:
                logger.warning(
                    "Native retro backend '%s' failed to load game '%s': %s. "
                    "Falling back to high-fidelity simulated core.",
                    pkg_name,
                    retro_cfg.game,
                    exc,
                )

        # 4. Fallback: High-fidelity simulated NES core
        logger.info(
            "Native retro libraries unavailable or game ROM absent. "
            "Activating high-fidelity SimulatedRetroCore."
        )
        self.backend = SimulatedRetroCore(game=retro_cfg.game)
        self.backend.reset()
        self.is_initialized = True

    async def shutdown(self) -> None:
        """Gracefully release emulator resources and frame buffers."""
        if not self.is_initialized:
            return

        if self.backend:
            self.backend.close()
            self.backend = None

        self.is_initialized = False
        logger.info("RetroAdapter shut down cleanly")

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register all retro emulator actuation, snapshotting, and memory tools."""
        registry.register(
            name="retro_send_pad",
            handler=self._tool_retro_send_pad,
            description=(
                "Send gamepad button inputs to the emulator core for an exact frame duration "
                "before releasing (supports A, B, UP, DOWN, LEFT, RIGHT, SELECT, START)."
            ),
            input_model=RetroSendPadInput,
        )
        registry.register(
            name="retro_save_state",
            handler=self._tool_retro_save_state,
            description=(
                "Serialize current emulator memory, CPU registers, and frame state into "
                "a named snapshot slot for checkpointing."
            ),
            input_model=RetroSaveStateInput,
        )
        registry.register(
            name="retro_load_state",
            handler=self._tool_retro_load_state,
            description=(
                "Restore emulator memory and CPU state from a previously saved snapshot slot "
                "to explore branching strategies or recover from hazards."
            ),
            input_model=RetroLoadStateInput,
        )
        registry.register(
            name="retro_read_ram",
            handler=self._tool_retro_read_ram,
            description=(
                "Directly read arbitrary RAM memory bytes by start address and length, "
                "bypassing vision latency to extract exact scores, lives, or positions."
            ),
            input_model=RetroReadRamInput,
        )

    def register_resources(self, registry: ResourceRegistry) -> None:
        """Register live telemetry and screen frame resources."""
        registry.register(
            uri="retro://screen",
            reader=self._resource_screen,
            name="Retro Emulator Screen Frame",
            description="Raw unscaled emulator frame buffer serialized as lossless PNG",
            mime_type="image/png",
        )
        registry.register(
            uri="retro://ram/variables",
            reader=self._resource_ram_variables,
            name="Retro RAM Variables",
            description=(
                "Pre-mapped game telemetry variables extracted directly from emulator memory "
                "(score, lives, x_pos, timer, coins)"
            ),
            mime_type="application/json",
        )

    def register_prompts(self, registry: PromptRegistry) -> None:
        """Register strategic game-playing scaffolding prompts."""
        registry.register(
            name="retro_speedrun_strategy",
            generator=self._prompt_speedrun_strategy,
            description=(
                "Scaffolding prompt for frame-perfect retro game speedrunning and RAM analysis"
            ),
            arguments=[
                {
                    "name": "game_title",
                    "description": "Name of the retro game",
                    "required": False,
                },
                {
                    "name": "objective",
                    "description": "Current speedrun or level completion objective",
                    "required": False,
                },
            ],
        )

    async def health_check(self) -> dict[str, Any]:
        """Probe verifying emulator health, backend mode, and frame statistics."""
        return {
            "adapter_id": self.metadata.id,
            "status": "healthy" if self.is_initialized else "uninitialized",
            "backend": self.backend.backend_name if self.backend else None,
            "is_simulated": self.backend.is_simulated if self.backend else True,
            "game": self.backend.game_title if self.backend else self.config.adapters.retro.game,
            "frame_count": self.backend.frame_count if self.backend else 0,
            "saved_states_count": len(self.backend.saved_states) if self.backend else 0,
        }

    # -------------------------------------------------------------------------
    # Tool Handlers
    # -------------------------------------------------------------------------

    async def _tool_retro_send_pad(
        self,
        buttons: list[str],
        frames: int = 4,
    ) -> dict[str, Any]:
        if not self.is_initialized or not self.backend:
            raise AdapterError("RetroAdapter is not initialized")

        _frame, vars_dict = self.backend.step(buttons, frames=frames)

        x_pos = vars_dict.get("x_pos", 0)
        score = vars_dict.get("score", 0)
        lives = vars_dict.get("lives", 3)
        timer = vars_dict.get("timer", 400)

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Pad actuated with {buttons} for {frames} frame(s). "
                        f"State: x_pos={x_pos}, score={score}, lives={lives}, timer={timer}."
                    ),
                }
            ],
            "state": vars_dict,
            "frames_stepped": frames,
            "total_frames": self.backend.frame_count,
        }

    async def _tool_retro_save_state(
        self,
        slot_name: str,
    ) -> dict[str, Any]:
        if not self.is_initialized or not self.backend:
            raise AdapterError("RetroAdapter is not initialized")

        state_bytes = self.backend.save_state(slot_name)
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Successfully serialized state snapshot to slot '{slot_name}' "
                        f"({len(state_bytes)} bytes)."
                    ),
                }
            ],
            "slot_name": slot_name,
            "size_bytes": len(state_bytes),
        }

    async def _tool_retro_load_state(
        self,
        slot_name: str,
    ) -> dict[str, Any]:
        if not self.is_initialized or not self.backend:
            raise AdapterError("RetroAdapter is not initialized")

        self.backend.load_state(slot_name)
        vars_dict = self.backend.get_variables()

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Successfully restored state snapshot from slot '{slot_name}'.",
                }
            ],
            "slot_name": slot_name,
            "state": vars_dict,
        }

    async def _tool_retro_read_ram(
        self,
        address: int,
        length: int,
    ) -> dict[str, Any]:
        if not self.is_initialized or not self.backend:
            raise AdapterError("RetroAdapter is not initialized")

        raw_bytes = self.backend.read_ram(address, length)
        hex_dump = " ".join(f"{b:02X}" for b in raw_bytes)

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Read {len(raw_bytes)} byte(s) from 0x{address:04X}: {hex_dump}",
                }
            ],
            "address": address,
            "address_hex": f"0x{address:04X}",
            "length": len(raw_bytes),
            "hex": hex_dump,
            "bytes": list(raw_bytes),
        }

    # -------------------------------------------------------------------------
    # Resource Readers
    # -------------------------------------------------------------------------

    async def _resource_screen(self) -> bytes:
        if not self.is_initialized or not self.backend:
            raise AdapterError("RetroAdapter is not initialized")

        frame = self.backend.get_frame()
        return encode_image(frame, image_format="png")

    async def _resource_ram_variables(self) -> dict[str, Any]:
        if not self.is_initialized or not self.backend:
            return {"status": "uninitialized"}

        return self.backend.get_variables()

    # -------------------------------------------------------------------------
    # Prompt Renderers
    # -------------------------------------------------------------------------

    async def _prompt_speedrun_strategy(
        self,
        game_title: str = "Super Mario Bros",
        objective: str = "Complete World 1-1 with maximum score and zero deaths",
    ) -> list[dict[str, Any]]:
        text = (
            f"You are an expert autonomous retro speedrunning agent playing '{game_title}'.\n"
            f"Objective: {objective}\n\n"
            "Operational Execution Rules:\n"
            "1. Frame-Perfect Actuation: Use `retro_send_pad(buttons=['RIGHT', 'B'], frames=8)` "
            "for sprint jumps.\n"
            "2. State Snapshotting: Call `retro_save_state(slot_name='checkpoint_1')` before "
            "high-risk maneuvers.\n"
            "3. Memory Verification: Query `retro://ram/variables` or "
            "`retro_read_ram(address, length)` to monitor exact x_pos and timers.\n"
            "4. Visual Inspection: Inspect `retro://screen` to verify enemy positions "
            "and platform alignment.\n"
            "5. Failure Recovery: On death or pitfall, immediately invoke "
            "`retro_load_state(slot_name='checkpoint_1')`."
        )
        return [{"role": "user", "content": {"type": "text", "text": text}}]
