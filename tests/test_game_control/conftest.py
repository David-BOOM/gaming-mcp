"""Shared fixtures, mock harnesses, and interface contracts for E2E game control tests."""

from __future__ import annotations

import asyncio
import importlib.util
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from collections.abc import Sequence

import numpy as np
import pytest
from pydantic import BaseModel, Field

from gaming_mcp.adapters.computer_use import ComputerUseAdapter
from gaming_mcp.adapters.router import AdapterRouter
from gaming_mcp.config import GamingMCPConfig
from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry
from gaming_mcp.io.gamepad import BaseGamepadController, MockGamepadController
from gaming_mcp.io.input import Win32InputInjector
from gaming_mcp.io.process import Win32WindowManager, WindowInfo
from gaming_mcp.io.timing import ActionChunkScheduler
from gaming_mcp.utils.curves import generate_relative_camera_deltas

# ---------------------------------------------------------------------------
# Pydantic v2 Interface Contracts (PROJECT.md Specification)
# ---------------------------------------------------------------------------

class MovementType(StrEnum):
    """Supported directional movement commands."""

    FORWARD = "forward"
    BACKWARD = "backward"
    STRAFE_LEFT = "strafe_left"
    STRAFE_RIGHT = "strafe_right"
    JUMP = "jump"
    SPRINT = "sprint"
    CROUCH = "crouch"


class LookDirection(StrEnum):
    """Cardinal camera look directions."""

    LOOK_UP = "look_up"
    LOOK_DOWN = "look_down"
    LOOK_LEFT = "look_left"
    LOOK_RIGHT = "look_right"


class LookInput(BaseModel):
    """Camera look and angular rotation parameters."""

    direction: LookDirection | None = Field(
        default=None,
        description="Discrete cardinal look direction",
    )
    dx: int | None = Field(
        default=None,
        description="Relative horizontal mouse movement delta in pixels",
    )
    dy: int | None = Field(
        default=None,
        description="Relative vertical mouse movement delta in pixels",
    )
    yaw: float | None = Field(
        default=None,
        description="Horizontal camera rotation in degrees",
    )
    pitch: float | None = Field(
        default=None,
        description="Vertical camera rotation in degrees",
    )
    smooth: bool = Field(
        default=True,
        description="Apply Flash and Hogan minimum-jerk trajectory splining",
    )


class ActionType(StrEnum):
    """Common game actions and interactions."""

    PRIMARY_ACTION = "primary_action"
    SECONDARY_ACTION = "secondary_action"
    INTERACT = "interact"
    RELOAD = "reload"
    PAUSE = "pause"
    MENU = "menu"


class SequenceStep(BaseModel):
    """Individual action step inside a compound sequence."""

    movement: MovementType | None = Field(default=None)
    look: LookInput | None = Field(default=None)
    action: ActionType | None = Field(default=None)
    slot: int | None = Field(default=None, ge=1, le=9)
    chord: list[str] | None = Field(default=None)
    delay_ms: int = Field(default=0, ge=0)
    hold_duration_ms: int = Field(default=50, ge=0)


class GameControlInput(BaseModel):
    """Input parameters for the unified game_control tool."""

    movement: MovementType | None = Field(
        default=None,
        description="Directional locomotion or locomotion modifier",
    )
    look: LookInput | None = Field(
        default=None,
        description="Camera view rotation or relative mouse delta",
    )
    action: ActionType | None = Field(
        default=None,
        description="Standard game interaction or contextual action",
    )
    slot: int | None = Field(
        default=None,
        ge=1,
        le=9,
        description="Hotbar or weapon inventory slot (1 to 9)",
    )
    chord: list[str] | None = Field(
        default=None,
        description="Simultaneous multi-key or button chord",
    )
    sequence: list[SequenceStep] | None = Field(
        default=None,
        description="Timed multi-step action sequence",
    )
    hold_duration_ms: int = Field(
        default=50,
        ge=0,
        description="Duration in milliseconds to hold keys down",
    )


class GameControlOutput(BaseModel):
    """Standardized response schema for game_control tool."""

    success: bool
    status: str
    action_type: str
    details: dict[str, Any] = Field(default_factory=dict)


# Availability flag for M2 production schemas
try:
    HAS_PROD_SCHEMAS = (
        importlib.util.find_spec("gaming_mcp.schemas.game_control") is not None
    )
except (ImportError, ModuleNotFoundError):
    HAS_PROD_SCHEMAS = False


# ---------------------------------------------------------------------------
# Test Mocks and Harness Components
# ---------------------------------------------------------------------------

class MockScreenCapturer:
    """Mock screen capturer returning synthetic frame buffers."""

    def __init__(self) -> None:
        self.closed: bool = False
        self.call_count: int = 0
        self.last_region: tuple[int, int, int, int] | None = None

    @property
    def active_backend(self) -> str:
        return "mock_capturer"

    def capture_frame(
        self, region: tuple[int, int, int, int] | None = None
    ) -> np.ndarray[Any, Any]:
        self.call_count += 1
        self.last_region = region
        arr = np.zeros((200, 200, 3), dtype=np.uint8)
        arr[50:150, 50:150] = [0, 128, 255]
        return arr

    def close(self) -> None:
        self.closed = True


class MockInputInjector(Win32InputInjector):
    """Mock input injector recording all keystrokes, mouse moves, and smooth looks."""

    def __init__(self) -> None:
        super().__init__()
        self.clicks: list[tuple[int, int, str, Any]] = []
        self.drags: list[tuple[int, int, int, int, str, int, int]] = []
        self.keys_sent: list[tuple[list[str], int, int]] = []
        self.keys_down: list[str] = []
        self.keys_up: list[str] = []
        self.relative_moves: list[tuple[int, int]] = []
        self.smooth_looks: list[tuple[int, int, int, int]] = []
        self.released: bool = False

    def key_down(self, key: str) -> bool:
        self.keys_down.append(key)
        return True

    def key_up(self, key: str) -> bool:
        self.keys_up.append(key)
        return True

    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        modifiers: Sequence[str] | None = None,
    ) -> bool:
        self.clicks.append((x or 0, y or 0, button, list(modifiers) if modifiers else None))
        return True

    def mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str = "left",
        duration_ms: float = 300.0,
        steps: int = 25,
    ) -> bool:
        self.drags.append((start_x, start_y, end_x, end_y, button, int(duration_ms), steps))
        return True

    def send_keys(
        self,
        keys: list[str] | Any,
        hold_duration_ms: float = 100.0,
        repeat_count: int = 1,
    ) -> bool:
        self.keys_sent.append((list(keys), int(hold_duration_ms), repeat_count))
        return True

    def mouse_move_relative(self, dx: int, dy: int) -> bool:
        self.relative_moves.append((dx, dy))
        return True

    def mouse_look_smooth(
        self,
        total_dx: int,
        total_dy: int,
        duration_ms: int = 100,
        samples: int = 15,
    ) -> bool:
        self.smooth_looks.append((total_dx, total_dy, duration_ms, samples))
        deltas = generate_relative_camera_deltas(total_dx, total_dy, samples)
        for dx, dy in deltas:
            self.relative_moves.append((dx, dy))
        return True

    def release_all(self) -> None:
        self.released = True
        self.keys_down.clear()


class MockWindowManager(Win32WindowManager):
    """Mock window manager providing predictable window bounds and foreground tracking."""

    def __init__(self) -> None:
        self.brought_to_front: list[int] = []

    def find_window(
        self,
        pattern: str,
        regex: bool = True,
        visible_only: bool = True,
    ) -> WindowInfo | None:
        if "game" in pattern.lower() or "minesweeper" in pattern.lower():
            return WindowInfo(
                hwnd=2001,
                title="Universal Game Window",
                process_name="game.exe",
                process_id=5678,
                rect=(50, 50, 1280, 720),
            )
        if "cmd" in pattern.lower() or "powershell" in pattern.lower():
            return WindowInfo(
                hwnd=2002,
                title="Command Prompt",
                process_name="cmd.exe",
                process_id=9999,
                rect=(0, 0, 640, 480),
            )
        return None

    def bring_to_front(self, hwnd: int) -> bool:
        self.brought_to_front.append(hwnd)
        return True

    def get_foreground_window(self) -> WindowInfo | None:
        return WindowInfo(
            hwnd=2001,
            title="Universal Game Window",
            process_name="game.exe",
            process_id=5678,
            rect=(50, 50, 1280, 720),
        )


# ---------------------------------------------------------------------------
# Reference Game Control Dispatcher (Specification Verification Oracle)
# ---------------------------------------------------------------------------

class GameControlDispatcher:
    """Executes GameControlInput requests through the actuation subsystem.

    Acts as an authoritative verification oracle derived from PROJECT.md
    interface contracts, translating high-level commands into low-level
    injections with full cancellation token support.
    """

    MOVEMENT_KEY_MAP: ClassVar[dict[MovementType, str]] = {
        MovementType.FORWARD: "w",
        MovementType.BACKWARD: "s",
        MovementType.STRAFE_LEFT: "a",
        MovementType.STRAFE_RIGHT: "d",
        MovementType.JUMP: "space",
        MovementType.SPRINT: "shift",
        MovementType.CROUCH: "ctrl",
    }

    ACTION_KEY_MAP: ClassVar[dict[ActionType, str]] = {
        ActionType.INTERACT: "e",
        ActionType.RELOAD: "r",
        ActionType.PAUSE: "escape",
        ActionType.MENU: "tab",
    }

    def __init__(
        self,
        input_injector: MockInputInjector,
        gamepad_controller: BaseGamepadController,
        cancellation_manager: CancellationManager | None = None,
    ) -> None:
        self.injector = input_injector
        self.gamepad = gamepad_controller
        self.cancellation = cancellation_manager or CancellationManager()
        self.active_request_id: str | None = None
        self._pre_cancelled_requests: set[str] = set()
        self._active_depth = 0

        # Wire motor reset callbacks into cancellation manager
        self.cancellation.register_callback(self.injector.release_all)
        self.cancellation.register_callback(self.gamepad.reset)

    def mark_pre_cancelled(self, request_id: str) -> None:
        """Mark a request ID as cancelled prior to execution."""
        self._pre_cancelled_requests.add(request_id)

    async def execute(
        self,
        params: dict[str, Any] | GameControlInput | None = None,
        request_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a GameControlInput specification."""
        self.active_request_id = request_id

        # Validate input schema
        if params is None:
            input_model = GameControlInput.model_validate(kwargs)
        elif isinstance(params, dict):
            input_model = GameControlInput.model_validate(params)
        else:
            input_model = params

        hold_ms = input_model.hold_duration_ms

        is_root = (self._active_depth == 0)
        self._active_depth += 1
        current_task = asyncio.current_task()
        if is_root and request_id and current_task:
            self.cancellation.register_task(request_id, current_task)

        try:
            # Check pre-cancellation
            if request_id and request_id in self._pre_cancelled_requests:
                self.injector.release_all()
                return {
                    "success": False,
                    "status": "cancelled",
                    "action_type": "aborted",
                    "details": {"reason": "Request was cancelled before start"},
                }

            # 1. Movement execution
            if input_model.movement is not None:
                key = self.MOVEMENT_KEY_MAP.get(input_model.movement, "w")
                self.injector.send_keys([key], hold_duration_ms=hold_ms)
                return {
                    "success": True,
                    "status": "executed",
                    "action_type": f"movement_{input_model.movement.value}",
                    "details": {"key": key, "hold_ms": hold_ms},
                }

            # 2. Camera look execution
            if input_model.look is not None:
                look = input_model.look
                dx = look.dx or 0
                dy = look.dy or 0

                # Directional lookup
                if look.direction == LookDirection.LOOK_UP:
                    dy = -100
                elif look.direction == LookDirection.LOOK_DOWN:
                    dy = 100
                elif look.direction == LookDirection.LOOK_LEFT:
                    dx = -100
                elif look.direction == LookDirection.LOOK_RIGHT:
                    dx = 100

                # Angular conversion (5 pixels per degree sensitivity)
                if look.yaw is not None:
                    dx = round(look.yaw * 5.0)
                if look.pitch is not None:
                    dy = round(look.pitch * 5.0)

                if look.smooth:
                    self.injector.mouse_look_smooth(dx, dy, duration_ms=hold_ms)
                else:
                    self.injector.mouse_move_relative(dx, dy)

                return {
                    "success": True,
                    "status": "executed",
                    "action_type": "look",
                    "details": {"dx": dx, "dy": dy, "smooth": look.smooth},
                }

            # 3. Common action execution
            if input_model.action is not None:
                action = input_model.action
                if action == ActionType.PRIMARY_ACTION:
                    self.injector.mouse_click(button="left")
                    return {
                        "success": True,
                        "status": "executed",
                        "action_type": "primary_action",
                        "details": {"button": "left"},
                    }
                if action == ActionType.SECONDARY_ACTION:
                    self.injector.mouse_click(button="right")
                    return {
                        "success": True,
                        "status": "executed",
                        "action_type": "secondary_action",
                        "details": {"button": "right"},
                    }

                key = self.ACTION_KEY_MAP.get(action, "e")
                self.injector.send_keys([key], hold_duration_ms=hold_ms)
                return {
                    "success": True,
                    "status": "executed",
                    "action_type": f"action_{action.value}",
                    "details": {"key": key, "hold_ms": hold_ms},
                }

            # 4. Hotbar slot execution
            if input_model.slot is not None:
                key = str(input_model.slot)
                self.injector.send_keys([key], hold_duration_ms=hold_ms)
                return {
                    "success": True,
                    "status": "executed",
                    "action_type": "slot_selection",
                    "details": {"slot": input_model.slot, "key": key},
                }

            # 5. Key chord execution
            if input_model.chord is not None:
                for k in input_model.chord:
                    self.injector.key_down(k)
                if hold_ms > 0:
                    await asyncio.sleep(min(hold_ms / 1000.0, 0.05))
                for k in reversed(input_model.chord):
                    self.injector.key_up(k)
                return {
                    "success": True,
                    "status": "executed",
                    "action_type": "chord",
                    "details": {"keys": input_model.chord, "hold_ms": hold_ms},
                }

            # 6. Compound sequence execution
            if input_model.sequence is not None:
                executed_steps: list[dict[str, Any]] = []
                for _step_idx, step in enumerate(input_model.sequence):
                    # Check task cancellation
                    is_cancelling = (
                        current_task
                        and hasattr(current_task, "cancelling")
                        and current_task.cancelling() > 0
                    )
                    if is_cancelling:
                        raise asyncio.CancelledError()

                    if step.delay_ms > 0:
                        await asyncio.sleep(step.delay_ms / 1000.0)

                    step_res = await self.execute(
                        GameControlInput(
                            movement=step.movement,
                            look=step.look,
                            action=step.action,
                            slot=step.slot,
                            chord=step.chord,
                            hold_duration_ms=step.hold_duration_ms,
                        ),
                        request_id=request_id,
                    )
                    executed_steps.append(step_res)

                return {
                    "success": True,
                    "status": "executed",
                    "action_type": "sequence",
                    "details": {"steps_count": len(executed_steps), "steps": executed_steps},
                }

            # Empty payload
            return {
                "success": True,
                "status": "noop",
                "action_type": "none",
                "details": {"message": "No action specified"},
            }

        except asyncio.CancelledError:
            self.injector.release_all()
            self.gamepad.reset()
            return {
                "success": False,
                "status": "cancelled",
                "action_type": "aborted",
                "details": {
                    "reason": "Request cancelled by client",
                    "completed_steps": len(executed_steps) if input_model.sequence else 0,
                },
            }
        finally:
            self._active_depth -= 1
            if is_root and request_id and current_task:
                self.cancellation.unregister_task(request_id)


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_injector() -> MockInputInjector:
    """Provide a fresh mock input injector recording all low-level calls."""
    return MockInputInjector()


@pytest.fixture
def mock_gamepad() -> MockGamepadController:
    """Provide a fresh mock gamepad controller."""
    return MockGamepadController()


@pytest.fixture
def mock_screen() -> MockScreenCapturer:
    """Provide a fresh mock screen capturer."""
    return MockScreenCapturer()


@pytest.fixture
def mock_win_mgr() -> MockWindowManager:
    """Provide a fresh mock window manager."""
    return MockWindowManager()


@pytest.fixture
def cancellation_mgr() -> CancellationManager:
    """Provide a fresh cancellation manager."""
    return CancellationManager()


@pytest.fixture
def test_config() -> GamingMCPConfig:
    """Provide a test server configuration."""
    config = GamingMCPConfig()
    config.security.enable_kill_switch = False
    return config


@pytest.fixture
def test_computer_use_adapter(
    test_config: GamingMCPConfig,
    mock_screen: MockScreenCapturer,
    mock_injector: MockInputInjector,
    mock_gamepad: MockGamepadController,
    mock_win_mgr: MockWindowManager,
) -> ComputerUseAdapter:
    """Provide an instantiated ComputerUseAdapter wired with mock I/O."""
    scheduler = ActionChunkScheduler(input_injector=mock_injector, gamepad=mock_gamepad)
    return ComputerUseAdapter(
        config=test_config,
        screen_capturer=mock_screen,
        input_injector=mock_injector,
        gamepad_controller=mock_gamepad,
        window_manager=mock_win_mgr,
        action_scheduler=scheduler,
    )


@pytest.fixture
def game_control_dispatcher(
    mock_injector: MockInputInjector,
    mock_gamepad: MockGamepadController,
    cancellation_mgr: CancellationManager,
) -> GameControlDispatcher:
    """Provide a ready-to-use GameControlDispatcher instance."""
    return GameControlDispatcher(
        input_injector=mock_injector,
        gamepad_controller=mock_gamepad,
        cancellation_manager=cancellation_mgr,
    )


class MockTestServer:
    """Lightweight test server verifying auto-startup and tool registration lifecycle."""

    def __init__(self, config: GamingMCPConfig | None = None) -> None:
        self.config = config or GamingMCPConfig()
        self.router = AdapterRouter()
        self.tools = ToolRegistry()
        self.resources = ResourceRegistry()
        self.prompts = PromptRegistry()
        self.cancellation_manager = CancellationManager()
        self.is_initialized: bool = False

    async def initialize(self) -> None:
        """Execute default adapter startup lifecycle."""
        # Auto-switch to configured default adapter
        default_id = self.config.adapters.default_adapter
        if self.router.get_adapter(default_id) is not None:
            await self.router.switch_adapter(default_id, self)  # type: ignore[arg-type]
        self.is_initialized = True

    def register_tool(
        self,
        name: str,
        handler: Any,
        description: str = "",
        input_model: Any = None,
    ) -> None:
        self.tools.register(name, handler, description=description, input_model=input_model)

    def get_health(self) -> dict[str, Any]:
        return {
            "is_initialized": self.is_initialized,
            "active_adapter": self.router.active_adapter_id or self.config.adapters.default_adapter,
            "tools_registered": len(self.tools.list_tools()),
        }


@pytest.fixture
def mock_test_server(
    test_config: GamingMCPConfig,
    test_computer_use_adapter: ComputerUseAdapter,
) -> MockTestServer:
    """Provide a MockTestServer pre-populated with ComputerUseAdapter."""
    server = MockTestServer(config=test_config)
    server.router.register_adapter(test_computer_use_adapter)
    return server
