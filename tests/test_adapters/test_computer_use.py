"""Automated tests for ComputerUseAdapter lifecycle, tools, resources, and safety."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

import numpy as np
import pytest

from gaming_mcp.adapters.computer_use import (
    ComputerUseAdapter,
)
from gaming_mcp.config import GamingMCPConfig
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry
from gaming_mcp.io.gamepad import MockGamepadController
from gaming_mcp.io.input import Win32InputInjector
from gaming_mcp.io.process import Win32WindowManager, WindowInfo
from gaming_mcp.io.timing import ActionChunkScheduler
from gaming_mcp.server import GamingMCPServer


class MockScreenCapturer:
    """Mock screen capturer returning synthetic frame buffers."""

    def __init__(self) -> None:
        self.closed = False
        self.call_count = 0
        self.last_region: tuple[int, int, int, int] | None = None

    @property
    def active_backend(self) -> str:
        return "mock_capturer"

    def capture_frame(self, region: tuple[int, int, int, int] | None = None) -> np.ndarray:
        self.call_count += 1
        self.last_region = region
        # Create a 200x200 RGB synthetic test pattern
        arr = np.zeros((200, 200, 3), dtype=np.uint8)
        arr[50:150, 50:150] = [0, 128, 255]
        return arr

    def close(self) -> None:
        self.closed = True


class MockInputInjector(Win32InputInjector):
    """Mock input injector recording all actuation requests."""

    def __init__(self) -> None:
        super().__init__()
        self.clicks: list[tuple[int, int, str, Any]] = []
        self.drags: list[tuple[int, int, int, int, str, int, int]] = []
        self.keys_sent: list[tuple[list[str], int, int]] = []
        self.released: bool = False

    def key_down(self, key: str) -> bool:
        return True

    def key_up(self, key: str) -> bool:
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

    def release_all(self) -> None:
        self.released = True


class MockWindowManager(Win32WindowManager):
    """Mock window manager providing controllable window handles."""

    def __init__(self) -> None:
        self.brought_to_front: list[int] = []

    def find_window(
        self,
        pattern: str,
        regex: bool = True,
        visible_only: bool = True,
    ) -> WindowInfo | None:
        if "minesweeper" in pattern.lower():
            return WindowInfo(
                hwnd=1001,
                title="Minesweeper Deluxe",
                process_name="minesweeper.exe",
                process_id=4567,
                rect=(100, 100, 900, 700),
            )
        if "cmd" in pattern.lower():
            return WindowInfo(
                hwnd=1002,
                title="Command Prompt",
                process_name="cmd.exe",
                process_id=8888,
                rect=(0, 0, 640, 480),
            )
        return None

    def bring_to_front(self, hwnd: int) -> bool:
        self.brought_to_front.append(hwnd)
        return True

    def get_foreground_window(self) -> WindowInfo | None:
        return WindowInfo(
            hwnd=1001,
            title="Minesweeper Deluxe",
            process_name="minesweeper.exe",
            process_id=4567,
            rect=(100, 100, 900, 700),
        )


@pytest.fixture
def mock_adapter() -> tuple[
    ComputerUseAdapter,
    MockScreenCapturer,
    MockInputInjector,
    MockGamepadController,
    MockWindowManager,
]:
    config = GamingMCPConfig()
    config.security.enable_kill_switch = False  # Keep disabled in unit test to avoid hook threads

    capturer = MockScreenCapturer()
    injector = MockInputInjector()
    gamepad = MockGamepadController()
    win_mgr = MockWindowManager()
    scheduler = ActionChunkScheduler(input_injector=injector, gamepad=gamepad)

    adapter = ComputerUseAdapter(
        config=config,
        screen_capturer=capturer,
        input_injector=injector,
        gamepad_controller=gamepad,
        window_manager=win_mgr,
        action_scheduler=scheduler,
    )
    return adapter, capturer, injector, gamepad, win_mgr


def test_adapter_metadata(mock_adapter: Any) -> None:
    adapter, _, _, _, _ = mock_adapter
    meta = adapter.metadata
    assert meta.id == "computer_use"
    assert "Universal" in meta.display_name
    assert meta.requires_display is True
    assert "win32" in meta.supported_platforms


@pytest.mark.asyncio
async def test_adapter_lifecycle(mock_adapter: Any) -> None:
    adapter, capturer, injector, gamepad, _ = mock_adapter
    assert adapter.is_initialized is False

    await adapter.initialize()
    assert adapter.is_initialized is True

    health = await adapter.health_check()
    assert health["adapter_id"] == "computer_use"
    assert health["status"] == "healthy"
    assert health["screen_capturer_backend"] == "mock_capturer"

    await adapter.shutdown()
    assert adapter.is_initialized is False
    assert capturer.closed is True
    assert injector.released is True
    assert gamepad.left_stick == (0.0, 0.0)


@pytest.mark.asyncio
async def test_tool_registrations_and_execution(mock_adapter: Any) -> None:
    adapter, _capturer, injector, gamepad, win_mgr = mock_adapter
    await adapter.initialize()

    tool_registry = ToolRegistry()
    adapter.register_tools(tool_registry)

    # Verify all 7 tools are registered
    tool_names = {t.name for t in tool_registry.list_tools()}
    expected_tools = {
        "screenshot",
        "mouse_click",
        "mouse_drag",
        "send_keys",
        "execute_action_chunk",
        "gamepad_control",
        "window_focus",
    }
    assert expected_tools.issubset(tool_names)

    # 1. Test screenshot
    res_shot = await tool_registry.execute(
        "screenshot",
        {"annotate_grid": True, "format": "jpeg", "quality": 80},
    )
    assert res_shot["isError"] is False
    assert res_shot["content"][0]["type"] == "image"
    assert res_shot["content"][0]["mimeType"] == "image/jpeg"
    assert len(res_shot["content"][0]["data"]) > 100

    # 2. Test screenshot with static delta gating
    _res_static = await tool_registry.execute(
        "screenshot",
        {"skip_if_static": True},
    )
    # Second identical screenshot should detect static scene
    res_static2 = await tool_registry.execute(
        "screenshot",
        {"skip_if_static": True},
    )
    assert res_static2["isError"] is False
    assert "unchanged" in res_static2["content"][0]["text"].lower()

    # 3. Test mouse_click within bounds
    res_click = await tool_registry.execute(
        "mouse_click",
        {"x": 200, "y": 200, "button": "left"},
    )
    assert res_click["isError"] is False
    assert len(injector.clicks) == 1
    assert injector.clicks[0][:3] == (200, 200, "left")

    # 4. Test mouse_drag
    res_drag = await tool_registry.execute(
        "mouse_drag",
        {"start_x": 200, "start_y": 200, "end_x": 300, "end_y": 300, "duration_ms": 150},
    )
    assert res_drag["isError"] is False
    assert len(injector.drags) == 1

    # 5. Test send_keys
    res_keys = await tool_registry.execute(
        "send_keys",
        {"keys": ["w", "space"], "hold_duration_ms": 50},
    )
    assert res_keys["isError"] is False
    assert len(injector.keys_sent) == 1
    assert injector.keys_sent[0][0] == ["w", "space"]

    # 6. Test execute_action_chunk
    actions = [
        {"offset_ms": 0, "type": "key_down", "params": {"key": "w"}},
        {"offset_ms": 50, "type": "key_up", "params": {"key": "w"}},
    ]
    res_chunk = await tool_registry.execute(
        "execute_action_chunk",
        {"actions": actions, "total_duration_ms": 100},
    )
    assert res_chunk["isError"] is False
    assert "actions" in res_chunk["content"][0]["text"]

    # 7. Test gamepad_control
    res_gamepad = await tool_registry.execute(
        "gamepad_control",
        {
            "left_stick": {"x": 0.5, "y": -0.5},
            "left_trigger": 0.8,
            "buttons_pressed": ["A"],
            "duration_ms": 50,
        },
    )
    assert res_gamepad["isError"] is False
    assert gamepad.left_stick == (0.0, 0.0)

    # 8. Test window_focus valid
    res_focus = await tool_registry.execute(
        "window_focus",
        {"title_pattern": "Minesweeper"},
    )
    assert res_focus["isError"] is False
    assert 1001 in win_mgr.brought_to_front
    assert adapter.bound_window_rect == (100, 100, 900, 700)

    # 9. Test window_focus missing
    res_missing = await tool_registry.execute(
        "window_focus",
        {"title_pattern": "NonExistentGameXYZ"},
    )
    assert res_missing["isError"] is True
    assert "No active window" in res_missing["content"][0]["text"]

    # 10. Test window_focus security blacklist violation
    res_blacklisted = await tool_registry.execute(
        "window_focus",
        {"title_pattern": "cmd"},
    )
    assert res_blacklisted["isError"] is True
    assert res_blacklisted["error_code"] == -32004

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_resource_and_prompt_registrations(mock_adapter: Any) -> None:
    adapter, _, _, _, _ = mock_adapter
    await adapter.initialize()

    resource_registry = ResourceRegistry()
    adapter.register_resources(resource_registry)

    # Verify resource registrations
    uris = {r.uri for r in resource_registry.list_resources()}
    assert "game://audio/events" in uris
    assert "game://screen/info" in uris

    # Read resources
    audio_data = await resource_registry.read("game://audio/events")
    assert "contents" in audio_data

    screen_data = await resource_registry.read("game://screen/info")
    assert "contents" in screen_data

    # Verify prompt registration
    prompt_registry = PromptRegistry()
    adapter.register_prompts(prompt_registry)
    prompts = {p.name for p in prompt_registry.list_prompts()}
    assert "gameplay_strategy" in prompts

    rendered = await prompt_registry.render("gameplay_strategy", {"game_title": "Elden Ring"})
    assert "Elden Ring" in rendered[0]["content"]["text"]

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_router_integration_with_server(mock_adapter: Any) -> None:
    adapter, _, _, _, _ = mock_adapter
    server = GamingMCPServer()

    # Register adapter into router
    server.router.register_adapter(adapter)
    registered_ids = [m.id for m in server.router.list_adapters()]
    assert "computer_use" in registered_ids

    # Switch adapter to computer_use
    active = await server.router.switch_adapter("computer_use", server)
    assert active.metadata.id == "computer_use"
    assert server.router.active_adapter_id == "computer_use"

    # Check that tools from computer_use are present in server.tools
    assert server.tools.get("screenshot") is not None
    assert server.tools.get("mouse_click") is not None
    assert server.tools.get("send_keys") is not None

    # Check resources
    assert server.resources.get("game://audio/events") is not None

    # Shutdown server
    await server.shutdown()
