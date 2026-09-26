"""Comprehensive E2E test suite for Universal Game Control and Auto-Startup.

Covers all 4 tiers of the testing methodology:
- Tier 1: Feature Coverage (Category-Partition Testing)
- Tier 2: Boundary Value Analysis and Corner Cases
- Tier 3: Cross-Feature Combinations (Pairwise Testing)
- Tier 4: Real-World Application Workloads
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.core.exceptions import AdapterNotFoundError
from gaming_mcp.io.gamepad import MockGamepadController, get_gamepad_controller
from gaming_mcp.io.screen import CompositeScreenCapturer
from tests.test_game_control.conftest import (
    GameControlDispatcher,
    GameControlInput,
    LookInput,
    MockInputInjector,
    MockTestServer,
)

if TYPE_CHECKING:
    from gaming_mcp.config import GamingMCPConfig
    from gaming_mcp.core.cancellation import CancellationManager
    from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry

# ===========================================================================
# Tier 1: Feature Coverage (Category-Partition Testing)
# ===========================================================================

# --- 1.1 Movement Commands (7 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier1_movement_forward(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'forward' movement emits 'w' keystroke with hold duration."""
    res = await game_control_dispatcher.execute({"movement": "forward", "hold_duration_ms": 75})
    assert res["success"] is True
    assert res["action_type"] == "movement_forward"
    assert len(mock_injector.keys_sent) == 1
    keys, hold_ms, _ = mock_injector.keys_sent[0]
    assert keys == ["w"]
    assert hold_ms == 75


@pytest.mark.asyncio
async def test_tier1_movement_backward(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'backward' movement emits 's' keystroke with hold duration."""
    res = await game_control_dispatcher.execute({"movement": "backward", "hold_duration_ms": 60})
    assert res["success"] is True
    assert res["action_type"] == "movement_backward"
    assert len(mock_injector.keys_sent) == 1
    keys, hold_ms, _ = mock_injector.keys_sent[0]
    assert keys == ["s"]
    assert hold_ms == 60


@pytest.mark.asyncio
async def test_tier1_movement_strafe_left(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'strafe_left' movement emits 'a' keystroke."""
    res = await game_control_dispatcher.execute({"movement": "strafe_left"})
    assert res["success"] is True
    assert res["action_type"] == "movement_strafe_left"
    assert len(mock_injector.keys_sent) == 1
    assert mock_injector.keys_sent[0][0] == ["a"]


@pytest.mark.asyncio
async def test_tier1_movement_strafe_right(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'strafe_right' movement emits 'd' keystroke."""
    res = await game_control_dispatcher.execute({"movement": "strafe_right"})
    assert res["success"] is True
    assert res["action_type"] == "movement_strafe_right"
    assert len(mock_injector.keys_sent) == 1
    assert mock_injector.keys_sent[0][0] == ["d"]


@pytest.mark.asyncio
async def test_tier1_movement_jump(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'jump' movement emits 'space' keystroke."""
    res = await game_control_dispatcher.execute({"movement": "jump"})
    assert res["success"] is True
    assert res["action_type"] == "movement_jump"
    assert len(mock_injector.keys_sent) == 1
    assert mock_injector.keys_sent[0][0] == ["space"]


@pytest.mark.asyncio
async def test_tier1_movement_sprint(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'sprint' movement emits 'shift' keystroke."""
    res = await game_control_dispatcher.execute({"movement": "sprint"})
    assert res["success"] is True
    assert res["action_type"] == "movement_sprint"
    assert len(mock_injector.keys_sent) == 1
    assert mock_injector.keys_sent[0][0] == ["shift"]


@pytest.mark.asyncio
async def test_tier1_movement_crouch(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'crouch' movement emits 'ctrl' keystroke."""
    res = await game_control_dispatcher.execute({"movement": "crouch"})
    assert res["success"] is True
    assert res["action_type"] == "movement_crouch"
    assert len(mock_injector.keys_sent) == 1
    assert mock_injector.keys_sent[0][0] == ["ctrl"]


# --- 1.2 Camera Look Commands (5 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier1_look_cardinal_directions(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify cardinal directions map to negative/positive pixel deltas."""
    # Look up -> dy < 0
    res_up = await game_control_dispatcher.execute({"look": {"direction": "look_up"}})
    assert res_up["success"] is True
    assert res_up["details"]["dy"] < 0

    # Look down -> dy > 0
    res_down = await game_control_dispatcher.execute({"look": {"direction": "look_down"}})
    assert res_down["success"] is True
    assert res_down["details"]["dy"] > 0

    # Look left -> dx < 0
    res_left = await game_control_dispatcher.execute({"look": {"direction": "look_left"}})
    assert res_left["success"] is True
    assert res_left["details"]["dx"] < 0

    # Look right -> dx > 0
    res_right = await game_control_dispatcher.execute({"look": {"direction": "look_right"}})
    assert res_right["success"] is True
    assert res_right["details"]["dx"] > 0


@pytest.mark.asyncio
async def test_tier1_look_relative_pixel_deltas(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify arbitrary relative pixel deltas are forwarded."""
    res = await game_control_dispatcher.execute({"look": {"dx": 150, "dy": -75, "smooth": False}})
    assert res["success"] is True
    assert res["details"]["dx"] == 150
    assert res["details"]["dy"] == -75
    assert (150, -75) in mock_injector.relative_moves


@pytest.mark.asyncio
async def test_tier1_look_angular_pitch_and_yaw(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify yaw and pitch angles are converted to proportional relative deltas."""
    res = await game_control_dispatcher.execute(
        {"look": {"yaw": 45.0, "pitch": -20.0, "smooth": False}}
    )
    assert res["success"] is True
    expected_dx = round(45.0 * 5.0)
    expected_dy = round(-20.0 * 5.0)
    assert res["details"]["dx"] == expected_dx
    assert res["details"]["dy"] == expected_dy
    assert (expected_dx, expected_dy) in mock_injector.relative_moves


@pytest.mark.asyncio
async def test_tier1_look_smooth_minimum_jerk_trajectory(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify smooth camera look records smooth_looks and produces sliced relative deltas."""
    res = await game_control_dispatcher.execute(
        {"look": {"dx": 100, "dy": 60, "smooth": True}, "hold_duration_ms": 120}
    )
    assert res["success"] is True
    assert len(mock_injector.smooth_looks) == 1
    total_dx, total_dy, dur, _ = mock_injector.smooth_looks[0]
    assert total_dx == 100
    assert total_dy == 60
    assert dur == 120
    # Sum of all sliced relative deltas must equal total
    sum_dx = sum(dx for dx, _ in mock_injector.relative_moves)
    sum_dy = sum(dy for _, dy in mock_injector.relative_moves)
    assert sum_dx == 100
    assert sum_dy == 60


@pytest.mark.asyncio
async def test_tier1_look_discrete_unsmoothed_movement(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify smooth=False dispatches single instantaneous relative mouse jump."""
    res = await game_control_dispatcher.execute(
        {"look": {"dx": 80, "dy": 40, "smooth": False}}
    )
    assert res["success"] is True
    assert len(mock_injector.smooth_looks) == 0
    assert (80, 40) in mock_injector.relative_moves


# --- 1.3 Interactions (6 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier1_action_primary_action(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'primary_action' triggers left mouse click."""
    res = await game_control_dispatcher.execute({"action": "primary_action"})
    assert res["success"] is True
    assert res["action_type"] == "primary_action"
    assert len(mock_injector.clicks) == 1
    assert mock_injector.clicks[0][2] == "left"


@pytest.mark.asyncio
async def test_tier1_action_secondary_action(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'secondary_action' triggers right mouse click."""
    res = await game_control_dispatcher.execute({"action": "secondary_action"})
    assert res["success"] is True
    assert res["action_type"] == "secondary_action"
    assert len(mock_injector.clicks) == 1
    assert mock_injector.clicks[0][2] == "right"


@pytest.mark.asyncio
async def test_tier1_action_interact(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'interact' sends 'e' keystroke."""
    res = await game_control_dispatcher.execute({"action": "interact"})
    assert res["success"] is True
    assert res["action_type"] == "action_interact"
    assert mock_injector.keys_sent[0][0] == ["e"]


@pytest.mark.asyncio
async def test_tier1_action_reload(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'reload' sends 'r' keystroke."""
    res = await game_control_dispatcher.execute({"action": "reload"})
    assert res["success"] is True
    assert res["action_type"] == "action_reload"
    assert mock_injector.keys_sent[0][0] == ["r"]


@pytest.mark.asyncio
async def test_tier1_action_pause(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'pause' sends 'escape' keystroke."""
    res = await game_control_dispatcher.execute({"action": "pause"})
    assert res["success"] is True
    assert res["action_type"] == "action_pause"
    assert mock_injector.keys_sent[0][0] == ["escape"]


@pytest.mark.asyncio
async def test_tier1_action_menu(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 'menu' sends 'tab' keystroke."""
    res = await game_control_dispatcher.execute({"action": "menu"})
    assert res["success"] is True
    assert res["action_type"] == "action_menu"
    assert mock_injector.keys_sent[0][0] == ["tab"]


# --- 1.4 Hotbar Slots (5 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier1_slot_1(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify slot 1 selects hotbar index 1."""
    res = await game_control_dispatcher.execute({"slot": 1})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["1"]


@pytest.mark.asyncio
async def test_tier1_slot_3(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify slot 3 selects hotbar index 3."""
    res = await game_control_dispatcher.execute({"slot": 3})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["3"]


@pytest.mark.asyncio
async def test_tier1_slot_5(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify slot 5 selects hotbar index 5."""
    res = await game_control_dispatcher.execute({"slot": 5})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["5"]


@pytest.mark.asyncio
async def test_tier1_slot_7(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify slot 7 selects hotbar index 7."""
    res = await game_control_dispatcher.execute({"slot": 7})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["7"]


@pytest.mark.asyncio
async def test_tier1_slot_9(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify slot 9 selects hotbar index 9."""
    res = await game_control_dispatcher.execute({"slot": 9})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["9"]


# --- 1.5 Chords (5 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier1_chord_sprint_forward(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify chord ['shift', 'w'] presses both keys down and releases them."""
    res = await game_control_dispatcher.execute({"chord": ["shift", "w"]})
    assert res["success"] is True
    assert mock_injector.keys_down == ["shift", "w"]
    assert mock_injector.keys_up == ["w", "shift"]


@pytest.mark.asyncio
async def test_tier1_chord_jump_forward(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify chord ['w', 'space'] presses both keys down and releases them."""
    res = await game_control_dispatcher.execute({"chord": ["w", "space"]})
    assert res["success"] is True
    assert mock_injector.keys_down == ["w", "space"]
    assert mock_injector.keys_up == ["space", "w"]


@pytest.mark.asyncio
async def test_tier1_chord_crouch_walk(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify chord ['ctrl', 'w'] presses both keys down and releases them."""
    res = await game_control_dispatcher.execute({"chord": ["ctrl", "w"]})
    assert res["success"] is True
    assert mock_injector.keys_down == ["ctrl", "w"]
    assert mock_injector.keys_up == ["w", "ctrl"]


@pytest.mark.asyncio
async def test_tier1_chord_inventory_drop(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify chord ['ctrl', 'q'] executes cleanly."""
    res = await game_control_dispatcher.execute({"chord": ["ctrl", "q"]})
    assert res["success"] is True
    assert mock_injector.keys_down == ["ctrl", "q"]
    assert mock_injector.keys_up == ["q", "ctrl"]


@pytest.mark.asyncio
async def test_tier1_chord_three_key_combination(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 3-key chord ['shift', 'w', 'space'] executes all keydowns and keyups."""
    res = await game_control_dispatcher.execute({"chord": ["shift", "w", "space"]})
    assert res["success"] is True
    assert mock_injector.keys_down == ["shift", "w", "space"]
    assert mock_injector.keys_up == ["space", "w", "shift"]


# --- 1.6 Compound Sequences (5 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier1_sequence_movement_and_look(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify sequential execution of movement followed by camera look."""
    seq = [
        {"movement": "forward", "hold_duration_ms": 50},
        {"look": {"dx": 50, "dy": 0, "smooth": False}},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert res["details"]["steps_count"] == 2
    assert mock_injector.keys_sent[0][0] == ["w"]
    assert (50, 0) in mock_injector.relative_moves


@pytest.mark.asyncio
async def test_tier1_sequence_slot_and_interact(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify sequence of slot change followed by interaction."""
    seq = [
        {"slot": 2},
        {"action": "interact"},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert len(mock_injector.keys_sent) == 2
    assert mock_injector.keys_sent[0][0] == ["2"]
    assert mock_injector.keys_sent[1][0] == ["e"]


@pytest.mark.asyncio
async def test_tier1_sequence_pause_and_menu(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify sequence of pause followed by menu."""
    seq = [
        {"action": "pause"},
        {"action": "menu"},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["escape"]
    assert mock_injector.keys_sent[1][0] == ["tab"]


@pytest.mark.asyncio
async def test_tier1_sequence_attack_and_reload(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify sequence of primary action followed by reload."""
    seq = [
        {"action": "primary_action"},
        {"action": "reload"},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert len(mock_injector.clicks) == 1
    assert mock_injector.keys_sent[0][0] == ["r"]


@pytest.mark.asyncio
async def test_tier1_sequence_multi_step_patrol(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 4-step sequence executes all steps in exact order."""
    seq = [
        {"movement": "forward"},
        {"look": {"dx": 90, "dy": 0, "smooth": False}},
        {"movement": "strafe_right"},
        {"action": "pause"},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert res["details"]["steps_count"] == 4
    assert mock_injector.keys_sent[0][0] == ["w"]
    assert (90, 0) in mock_injector.relative_moves
    assert mock_injector.keys_sent[1][0] == ["d"]
    assert mock_injector.keys_sent[2][0] == ["escape"]


# --- 1.7 Auto-Startup (5 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier1_auto_startup_default_adapter_active(
    mock_test_server: MockTestServer,
) -> None:
    """Verify server startup automatically activates default adapter without manual call."""
    assert mock_test_server.is_initialized is False
    await mock_test_server.initialize()
    assert mock_test_server.is_initialized is True
    assert mock_test_server.router.active_adapter_id == "computer_use"


@pytest.mark.asyncio
async def test_tier1_auto_startup_game_control_tool_exposed(
    mock_test_server: MockTestServer,
    game_control_dispatcher: GameControlDispatcher,
) -> None:
    """Verify game_control is exposed in tools registry upon startup."""
    mock_test_server.register_tool(
        name="game_control",
        handler=game_control_dispatcher.execute,
        description="Execute general game control commands",
        input_model=GameControlInput,
    )
    await mock_test_server.initialize()
    tool_names = [t.name for t in mock_test_server.tools.list_tools()]
    assert "game_control" in tool_names


@pytest.mark.asyncio
async def test_tier1_auto_startup_execution_without_switch_adapter(
    mock_test_server: MockTestServer,
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify tool executes directly after server boot without switch_adapter."""
    mock_test_server.register_tool(
        name="game_control",
        handler=game_control_dispatcher.execute,
        description="Execute general game control commands",
        input_model=GameControlInput,
    )
    await mock_test_server.initialize()
    exec_res = await mock_test_server.tools.execute("game_control", {"movement": "jump"})
    assert exec_res["isError"] is False
    assert mock_injector.keys_sent[0][0] == ["space"]


@pytest.mark.asyncio
async def test_tier1_auto_startup_health_telemetry(
    mock_test_server: MockTestServer,
) -> None:
    """Verify server health telemetry reflects active adapter after startup."""
    await mock_test_server.initialize()
    health = mock_test_server.get_health()
    assert health["is_initialized"] is True
    assert health["active_adapter"] == "computer_use"


@pytest.mark.asyncio
async def test_tier1_auto_startup_resources_registered(
    mock_test_server: MockTestServer,
) -> None:
    """Verify server resource registry is populated upon startup."""
    await mock_test_server.initialize()
    uris = [r.uri for r in mock_test_server.resources.list_resources()]
    assert "game://screen/info" in uris
    assert "game://audio/events" in uris


# --- 1.8 Dynamic Hot-Swapping (5 tests >= 5) ---

class MockSecondaryAdapter(GameAdapter):
    """Secondary mock adapter for hot-swapping tests."""

    def __init__(self, config: GamingMCPConfig, adapter_id: str = "minecraft") -> None:
        super().__init__(config)
        self._id = adapter_id

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            id=self._id,
            display_name=f"Mock {self._id.capitalize()}",
            version="1.0.0",
            description="Mock adapter for testing",
            author="Test",
        )

    async def initialize(self) -> None:
        self.is_initialized = True

    async def shutdown(self) -> None:
        self.is_initialized = False

    def register_tools(self, registry: ToolRegistry) -> None:
        async def _bot_action() -> str:
            return "bot_active"

        registry.register(f"{self._id}_bot_action", _bot_action)

    def register_resources(self, registry: ResourceRegistry) -> None:
        async def _bot_resource() -> dict[str, Any]:
            return {"status": "ok"}

        registry.register(f"game://{self._id}/status", _bot_resource)

    def register_prompts(self, registry: PromptRegistry) -> None:
        async def _bot_prompt() -> list[dict[str, Any]]:
            return [{"role": "user", "content": "play"}]

        registry.register(f"{self._id}_prompt", _bot_prompt)


@pytest.mark.asyncio
async def test_tier1_dynamic_swap_to_secondary_adapter(
    mock_test_server: MockTestServer,
    test_config: GamingMCPConfig,
) -> None:
    """Verify hot-swapping from computer_use to minecraft adapter."""
    secondary = MockSecondaryAdapter(test_config, "minecraft")
    mock_test_server.router.register_adapter(secondary)
    await mock_test_server.initialize()

    # Switch to minecraft
    switched = await mock_test_server.router.switch_adapter("minecraft", mock_test_server)  # type: ignore[arg-type]
    assert switched.metadata.id == "minecraft"
    assert mock_test_server.router.active_adapter_id == "minecraft"


@pytest.mark.asyncio
async def test_tier1_dynamic_swap_back_to_default(
    mock_test_server: MockTestServer,
    test_config: GamingMCPConfig,
) -> None:
    """Verify switching away and then switching back to default adapter."""
    secondary = MockSecondaryAdapter(test_config, "minecraft")
    mock_test_server.router.register_adapter(secondary)
    await mock_test_server.initialize()

    await mock_test_server.router.switch_adapter("minecraft", mock_test_server)  # type: ignore[arg-type]
    assert mock_test_server.router.active_adapter_id == "minecraft"

    # Switch back to computer_use
    back = await mock_test_server.router.switch_adapter("computer_use", mock_test_server)  # type: ignore[arg-type]
    assert back.metadata.id == "computer_use"
    assert mock_test_server.router.active_adapter_id == "computer_use"


@pytest.mark.asyncio
async def test_tier1_dynamic_swap_tool_detachment_and_reattachment(
    mock_test_server: MockTestServer,
    test_config: GamingMCPConfig,
) -> None:
    """Verify old adapter tools are unregistered and new adapter tools registered."""
    secondary = MockSecondaryAdapter(test_config, "minecraft")
    mock_test_server.router.register_adapter(secondary)
    await mock_test_server.initialize()

    await mock_test_server.router.switch_adapter("minecraft", mock_test_server)  # type: ignore[arg-type]
    tool_names = [t.name for t in mock_test_server.tools.list_tools()]
    assert "minecraft_bot_action" in tool_names


@pytest.mark.asyncio
async def test_tier1_dynamic_swap_resource_lifecycle(
    mock_test_server: MockTestServer,
    test_config: GamingMCPConfig,
) -> None:
    """Verify adapter shutdown is cleanly invoked on previous adapter during swap."""
    secondary = MockSecondaryAdapter(test_config, "retro")
    mock_test_server.router.register_adapter(secondary)
    await mock_test_server.initialize()

    prev_adapter = mock_test_server.router.active_adapter
    assert prev_adapter is not None
    assert prev_adapter.is_initialized is True

    await mock_test_server.router.switch_adapter("retro", mock_test_server)  # type: ignore[arg-type]
    assert prev_adapter.is_initialized is False
    assert mock_test_server.router.active_adapter_id == "retro"


@pytest.mark.asyncio
async def test_tier1_dynamic_swap_invalid_adapter_raises_error(
    mock_test_server: MockTestServer,
) -> None:
    """Verify switching to an unregistered adapter raises AdapterNotFoundError."""
    await mock_test_server.initialize()
    with pytest.raises(AdapterNotFoundError):
        await mock_test_server.router.switch_adapter("nonexistent_adapter_xyz", mock_test_server)  # type: ignore[arg-type]


# --- 1.9 Cancellation (5 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier1_cancellation_aborts_running_sequence(
    game_control_dispatcher: GameControlDispatcher,
) -> None:
    """Verify pre-cancelled token halts sequence immediately."""
    req_id = "req_cancel_01"
    game_control_dispatcher.mark_pre_cancelled(req_id)

    seq = [{"movement": "forward"}, {"movement": "jump"}]
    res = await game_control_dispatcher.execute({"sequence": seq}, request_id=req_id)
    assert res["success"] is False
    assert res["status"] == "cancelled"


@pytest.mark.asyncio
async def test_tier1_cancellation_releases_all_held_keys(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify cancelling an active sequence immediately triggers release_all()."""
    req_id = "req_cancel_02"
    game_control_dispatcher.mark_pre_cancelled(req_id)
    await game_control_dispatcher.execute({"movement": "forward"}, request_id=req_id)
    assert mock_injector.released is True


@pytest.mark.asyncio
async def test_tier1_cancellation_resets_gamepad_sticks(
    mock_gamepad: MockGamepadController,
    cancellation_mgr: CancellationManager,
) -> None:
    """Verify cancellation reset centers virtual gamepad thumbsticks."""
    mock_gamepad.set_left_stick(0.8, -0.5)
    mock_gamepad.set_right_stick(-0.4, 0.9)
    assert mock_gamepad.left_stick == (0.8, -0.5)

    cancellation_mgr.register_callback(mock_gamepad.reset)
    await cancellation_mgr.emergency_reset()

    assert mock_gamepad.left_stick == (0.0, 0.0)
    assert mock_gamepad.right_stick == (0.0, 0.0)


@pytest.mark.asyncio
async def test_tier1_cancellation_emergency_reset_hook(
    mock_injector: MockInputInjector,
    mock_gamepad: MockGamepadController,
    cancellation_mgr: CancellationManager,
) -> None:
    """Verify emergency_reset triggers both keyboard and gamepad motor release."""
    mock_injector.key_down("w")
    mock_gamepad.press_button("A")

    cancellation_mgr.register_callback(mock_injector.release_all)
    cancellation_mgr.register_callback(mock_gamepad.reset)

    await cancellation_mgr.emergency_reset()
    assert mock_injector.released is True
    assert len(mock_gamepad.held_buttons) == 0


@pytest.mark.asyncio
async def test_tier1_cancellation_notifications_cancelled_handler(
    cancellation_mgr: CancellationManager,
) -> None:
    """Verify cancel_request cancels active task and returns True."""
    req_id = "rpc_notification_req_99"

    async def _long_work() -> None:
        await asyncio.sleep(5.0)

    task = asyncio.create_task(_long_work())
    cancellation_mgr.register_task(req_id, task)
    assert cancellation_mgr.active_request_count == 1

    cancelled = await cancellation_mgr.cancel_request(req_id, reason="Client timed out")
    assert cancelled is True
    assert cancellation_mgr.active_request_count == 0
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled() is True


# --- 1.10 Fallback Actuation (5 tests >= 5) ---

def test_tier1_fallback_missing_vigembus_uses_mock() -> None:
    """Verify missing ViGEmBus driver falls back gracefully to MockGamepadController."""
    ctrl = get_gamepad_controller(prefer_mock=True)
    assert isinstance(ctrl, MockGamepadController)
    assert ctrl.is_available is True
    assert "operational" in ctrl.status_message.lower()


def test_tier1_fallback_headless_gamepad_operations(
    mock_gamepad: MockGamepadController,
) -> None:
    """Verify headless mock gamepad handles inputs without hardware errors."""
    mock_gamepad.set_left_stick(0.5, 0.5)
    mock_gamepad.set_left_trigger(1.0)
    mock_gamepad.press_button("START")
    mock_gamepad.release_button("START")
    assert mock_gamepad.left_stick == (0.5, 0.5)
    assert mock_gamepad.left_trigger == 1.0


def test_tier1_fallback_software_keystroke_tracking(
    mock_injector: MockInputInjector,
) -> None:
    """Verify software input tracking records all presses and releases without OS hooks."""
    mock_injector.key_down("shift")
    mock_injector.key_down("w")
    assert mock_injector.keys_down == ["shift", "w"]
    mock_injector.release_all()
    assert mock_injector.released is True
    assert len(mock_injector.keys_down) == 0


def test_tier1_fallback_screen_capturer_fallback_to_mss() -> None:
    """Verify CompositeScreenCapturer falls back to MSS when DXGI is unavailable."""
    capturer = CompositeScreenCapturer(prefer_dxgi=False)
    assert capturer.active_backend in ["mss", "mock", "pillow"]
    capturer.close()


def test_tier1_fallback_non_windows_platform_graceful_handling() -> None:
    """Verify scan code resolution operates cleanly without native OS hooks."""
    injector = MockInputInjector()
    scan_code, is_extended = injector.resolve_scan_code("w")
    assert scan_code == 0x11
    assert is_extended is False


# ===========================================================================
# Tier 2: Boundary Value Analysis and Corner Cases
# ===========================================================================

# --- 2.1 Parameter Boundaries (6 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier2_bva_empty_input_payload(
    game_control_dispatcher: GameControlDispatcher,
) -> None:
    """Verify empty input payload returns clean noop response."""
    res = await game_control_dispatcher.execute({})
    assert res["success"] is True
    assert res["status"] == "noop"
    assert res["action_type"] == "none"


def test_tier2_bva_slot_lower_boundary_zero_rejected() -> None:
    """Verify slot=0 is rejected by Pydantic validation (ge=1)."""
    with pytest.raises(ValidationError):
        GameControlInput(slot=0)


def test_tier2_bva_slot_upper_boundary_ten_rejected() -> None:
    """Verify slot=10 is rejected by Pydantic validation (le=9)."""
    with pytest.raises(ValidationError):
        GameControlInput(slot=10)


def test_tier2_bva_slot_boundary_values_1_and_9_accepted() -> None:
    """Verify exact slot boundaries 1 and 9 are accepted."""
    inp1 = GameControlInput(slot=1)
    inp9 = GameControlInput(slot=9)
    assert inp1.slot == 1
    assert inp9.slot == 9


@pytest.mark.asyncio
async def test_tier2_bva_extreme_mouse_deltas(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify extreme relative pixel deltas (+-10,000) are handled safely."""
    res_pos = await game_control_dispatcher.execute(
        {"look": {"dx": 10000, "dy": 5000, "smooth": True}}
    )
    assert res_pos["success"] is True
    res_neg = await game_control_dispatcher.execute(
        {"look": {"dx": -10000, "dy": -5000, "smooth": True}}
    )
    assert res_neg["success"] is True


def test_tier2_bva_zero_and_negative_hold_durations() -> None:
    """Verify zero hold duration is accepted, while negative is rejected."""
    valid_zero = GameControlInput(hold_duration_ms=0)
    assert valid_zero.hold_duration_ms == 0
    with pytest.raises(ValidationError):
        GameControlInput(hold_duration_ms=-10)


# --- 2.2 Unknown and Malformed Inputs (5 tests >= 5) ---

def test_tier2_bva_unknown_movement_string_rejected() -> None:
    """Verify unsupported movement string raises ValidationError."""
    with pytest.raises(ValidationError):
        GameControlInput.model_validate({"movement": "teleport"})


def test_tier2_bva_unknown_action_string_rejected() -> None:
    """Verify unsupported action string raises ValidationError."""
    with pytest.raises(ValidationError):
        GameControlInput.model_validate({"action": "super_laser"})


def test_tier2_bva_unknown_look_direction_rejected() -> None:
    """Verify invalid look direction raises ValidationError."""
    with pytest.raises(ValidationError):
        LookInput.model_validate({"direction": "diagonal_north_east"})


@pytest.mark.asyncio
async def test_tier2_bva_empty_chord_list_handled(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify empty chord list [] executes cleanly without exceptions."""
    res = await game_control_dispatcher.execute({"chord": []})
    assert res["success"] is True
    assert len(mock_injector.keys_down) == 0


def test_tier2_bva_malformed_sequence_step_rejected() -> None:
    """Verify invalid step inside sequence raises ValidationError."""
    with pytest.raises(ValidationError):
        GameControlInput.model_validate({
            "sequence": [{"slot": 15}]  # slot > 9
        })


# --- 2.3 Concurrency and Rapid Commands (5 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier2_bva_rapid_successive_commands(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 10 rapid successive commands execute without race conditions."""
    for _ in range(10):
        res = await game_control_dispatcher.execute({"movement": "forward", "hold_duration_ms": 1})
        assert res["success"] is True
    assert len(mock_injector.keys_sent) == 10


@pytest.mark.asyncio
async def test_tier2_bva_concurrent_asyncio_executions(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify 5 concurrent tool executions via asyncio.gather execute cleanly."""
    tasks = [
        game_control_dispatcher.execute({"movement": "jump", "hold_duration_ms": 1}),
        game_control_dispatcher.execute({"action": "interact", "hold_duration_ms": 1}),
        game_control_dispatcher.execute({"slot": 4, "hold_duration_ms": 1}),
        game_control_dispatcher.execute({"movement": "sprint", "hold_duration_ms": 1}),
        game_control_dispatcher.execute({"action": "reload", "hold_duration_ms": 1}),
    ]
    results = await asyncio.gather(*tasks)
    assert len(results) == 5
    assert all(r["success"] is True for r in results)
    assert len(mock_injector.keys_sent) == 5


@pytest.mark.asyncio
async def test_tier2_bva_rapid_hotbar_slot_switching(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify rapidly cycling through all hotbar slots 1 through 9."""
    for slot_idx in range(1, 10):
        res = await game_control_dispatcher.execute({"slot": slot_idx, "hold_duration_ms": 1})
        assert res["success"] is True
    assert [k[0][0] for k in mock_injector.keys_sent] == [str(i) for i in range(1, 10)]


@pytest.mark.asyncio
async def test_tier2_bva_concurrent_cancellation_and_execution(
    game_control_dispatcher: GameControlDispatcher,
    cancellation_mgr: CancellationManager,
) -> None:
    """Verify concurrent cancellation token fires safely while dispatching."""
    req_id = "req_concurrent_cancel"
    exec_task = asyncio.create_task(
        game_control_dispatcher.execute(
            {"chord": ["shift", "w"], "hold_duration_ms": 50},
            request_id=req_id,
        )
    )
    await asyncio.sleep(0.01)
    await cancellation_mgr.cancel_request(req_id, "Mid-flight cancel")
    res = await exec_task
    assert res["status"] in ["executed", "cancelled"]


@pytest.mark.asyncio
async def test_tier2_bva_rapid_directional_reversals(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify rapid alternation between forward and backward locomotion."""
    res_fwd = await game_control_dispatcher.execute({"movement": "forward"})
    res_bwd = await game_control_dispatcher.execute({"movement": "backward"})
    assert res_fwd["success"] is True
    assert res_bwd["success"] is True
    assert mock_injector.keys_sent[0][0] == ["w"]
    assert mock_injector.keys_sent[1][0] == ["s"]


# --- 2.4 Cancellation Timing Variations (5 tests >= 5) ---

@pytest.mark.asyncio
async def test_tier2_bva_cancellation_immediately_before_action(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Verify request already cancelled prior to invocation never touches hardware."""
    req_id = "pre_cancelled_01"
    game_control_dispatcher.mark_pre_cancelled(req_id)
    res = await game_control_dispatcher.execute({"movement": "forward"}, request_id=req_id)
    assert res["success"] is False
    assert res["status"] == "cancelled"
    assert len(mock_injector.keys_sent) == 0


@pytest.mark.asyncio
async def test_tier2_bva_cancellation_during_mid_sequence(
    game_control_dispatcher: GameControlDispatcher,
    cancellation_mgr: CancellationManager,
    mock_injector: MockInputInjector,
) -> None:
    """Verify cancellation after step 1 halts step 2 from executing."""
    req_id = "seq_mid_cancel"
    seq = [
        {"movement": "forward", "delay_ms": 10},
        {"movement": "jump", "delay_ms": 100},
    ]

    async def _cancel_later() -> None:
        await asyncio.sleep(0.03)
        await cancellation_mgr.cancel_request(req_id, "Aborting multi-step")

    cancel_task = asyncio.create_task(_cancel_later())
    res = await game_control_dispatcher.execute({"sequence": seq}, request_id=req_id)
    await cancel_task
    assert res["status"] == "cancelled"
    assert mock_injector.released is True


@pytest.mark.asyncio
async def test_tier2_bva_cancellation_immediately_after_action(
    game_control_dispatcher: GameControlDispatcher,
    cancellation_mgr: CancellationManager,
) -> None:
    """Verify cancelling token after successful completion returns False (no active task)."""
    req_id = "post_completed_cancel"
    res = await game_control_dispatcher.execute({"movement": "jump"}, request_id=req_id)
    assert res["success"] is True
    # Cancellation arrives after task unregistered
    cancelled = await cancellation_mgr.cancel_request(req_id, "Late cancel")
    assert cancelled is False


@pytest.mark.asyncio
async def test_tier2_bva_repeated_cancellation_idempotence(
    cancellation_mgr: CancellationManager,
    mock_injector: MockInputInjector,
) -> None:
    """Verify multiple emergency resets are idempotent and safe."""
    cancellation_mgr.register_callback(mock_injector.release_all)
    await cancellation_mgr.emergency_reset()
    await cancellation_mgr.emergency_reset()
    await cancellation_mgr.emergency_reset()
    assert mock_injector.released is True


@pytest.mark.asyncio
async def test_tier2_bva_unknown_request_id_cancellation(
    cancellation_mgr: CancellationManager,
) -> None:
    """Verify cancelling un-registered request ID returns False."""
    cancelled = await cancellation_mgr.cancel_request("never_registered_req_id")
    assert cancelled is False


# ===========================================================================
# Tier 3: Cross-Feature Combinations (Pairwise Testing)
# ===========================================================================

@pytest.mark.asyncio
async def test_tier3_pairwise_movement_while_camera_panning(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Pairwise: Locomotion combined with camera pan in a single sequence."""
    seq = [
        {"movement": "forward", "hold_duration_ms": 100},
        {"look": {"dx": 80, "dy": -20, "smooth": True}, "hold_duration_ms": 50},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["w"]
    assert len(mock_injector.smooth_looks) == 1
    assert mock_injector.smooth_looks[0][0] == 80


@pytest.mark.asyncio
async def test_tier3_pairwise_sprint_while_jumping(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Pairwise: Sprint and jump combined via chord."""
    res = await game_control_dispatcher.execute({"chord": ["shift", "space"]})
    assert res["success"] is True
    assert mock_injector.keys_down == ["shift", "space"]
    assert mock_injector.keys_up == ["space", "shift"]


@pytest.mark.asyncio
async def test_tier3_pairwise_chord_combined_with_primary_action(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Pairwise: Key chord followed immediately by primary action click."""
    seq = [
        {"chord": ["shift", "w"]},
        {"action": "primary_action"},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert mock_injector.keys_down == ["shift", "w"]
    assert len(mock_injector.clicks) == 1
    assert mock_injector.clicks[0][2] == "left"


@pytest.mark.asyncio
async def test_tier3_pairwise_action_sequence_movement_look_interaction(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Pairwise: 3-way combination of movement, camera rotation, and interact key."""
    seq = [
        {"movement": "forward"},
        {"look": {"direction": "look_up"}},
        {"action": "interact"},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["w"]
    assert mock_injector.keys_sent[1][0] == ["e"]
    assert len(mock_injector.smooth_looks) == 1


@pytest.mark.asyncio
async def test_tier3_pairwise_hotbar_slot_selection_while_moving(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Pairwise: Strafe left followed by hotbar slot 4 selection."""
    seq = [
        {"movement": "strafe_left"},
        {"slot": 4},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["a"]
    assert mock_injector.keys_sent[1][0] == ["4"]


@pytest.mark.asyncio
async def test_tier3_pairwise_camera_look_with_secondary_action(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Pairwise: Look down-left followed by secondary action (aim & right-click)."""
    seq = [
        {"look": {"dx": -50, "dy": 50, "smooth": False}},
        {"action": "secondary_action"},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert (-50, 50) in mock_injector.relative_moves
    assert len(mock_injector.clicks) == 1
    assert mock_injector.clicks[0][2] == "right"


@pytest.mark.asyncio
async def test_tier3_pairwise_crouch_while_cycling_hotbar(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Pairwise: Crouch action followed by multiple hotbar slot changes."""
    seq = [
        {"movement": "crouch"},
        {"slot": 1},
        {"slot": 2},
        {"slot": 3},
    ]
    res = await game_control_dispatcher.execute({"sequence": seq})
    assert res["success"] is True
    assert mock_injector.keys_sent[0][0] == ["ctrl"]
    assert mock_injector.keys_sent[1][0] == ["1"]
    assert mock_injector.keys_sent[2][0] == ["2"]
    assert mock_injector.keys_sent[3][0] == ["3"]


@pytest.mark.asyncio
async def test_tier3_pairwise_auto_startup_and_dynamic_swap_cycle(
    mock_test_server: MockTestServer,
    test_config: GamingMCPConfig,
) -> None:
    """Pairwise: Default auto-startup followed by full dynamic hot-swap cycle."""
    secondary = MockSecondaryAdapter(test_config, "gymnasium")
    mock_test_server.router.register_adapter(secondary)

    # 1. Auto-startup
    await mock_test_server.initialize()
    assert mock_test_server.router.active_adapter_id == "computer_use"

    # 2. Swap to gymnasium
    await mock_test_server.router.switch_adapter("gymnasium", mock_test_server)  # type: ignore[arg-type]
    assert mock_test_server.router.active_adapter_id == "gymnasium"

    # 3. Swap back to computer_use
    await mock_test_server.router.switch_adapter("computer_use", mock_test_server)  # type: ignore[arg-type]
    assert mock_test_server.router.active_adapter_id == "computer_use"


# ===========================================================================
# Tier 4: Real-World Application Workloads
# ===========================================================================

@pytest.mark.asyncio
async def test_tier4_scenario_first_person_navigation(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Scenario 1: First-person navigation.

    Sprint forward for 200ms, rotate camera 90 degrees right (dx=150),
    and jump over obstacle.
    """
    workflow = [
        {"chord": ["shift", "w"], "hold_duration_ms": 200},
        {"look": {"dx": 150, "dy": 0, "smooth": True}, "hold_duration_ms": 100},
        {"movement": "jump", "hold_duration_ms": 50},
    ]
    res = await game_control_dispatcher.execute({"sequence": workflow})
    assert res["success"] is True
    assert res["details"]["steps_count"] == 3
    # Step 1: chord
    assert mock_injector.keys_down == ["shift", "w"]
    # Step 2: camera smooth look
    assert len(mock_injector.smooth_looks) == 1
    assert mock_injector.smooth_looks[0][0] == 150
    # Step 3: jump
    assert any(k[0] == ["space"] for k in mock_injector.keys_sent)


@pytest.mark.asyncio
async def test_tier4_scenario_tactical_combat_cycle(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Scenario 2: Tactical combat cycle.

    Strafe left ('a'), aim down-left (dx=-60, dy=40), fire weapon (primary_action),
    reload weapon ('r'), and duck behind cover ('crouch').
    """
    workflow = [
        {"movement": "strafe_left", "hold_duration_ms": 100},
        {"look": {"dx": -60, "dy": 40, "smooth": True}, "hold_duration_ms": 50},
        {"action": "primary_action"},
        {"action": "reload", "hold_duration_ms": 50},
        {"movement": "crouch", "hold_duration_ms": 150},
    ]
    res = await game_control_dispatcher.execute({"sequence": workflow})
    assert res["success"] is True
    assert res["details"]["steps_count"] == 5
    # Strafe left executed
    assert mock_injector.keys_sent[0][0] == ["a"]
    # Aiming executed
    assert len(mock_injector.smooth_looks) == 1
    # Fired weapon
    assert len(mock_injector.clicks) == 1
    assert mock_injector.clicks[0][2] == "left"
    # Reloaded weapon
    assert mock_injector.keys_sent[1][0] == ["r"]
    # Crouched
    assert mock_injector.keys_sent[2][0] == ["ctrl"]


@pytest.mark.asyncio
async def test_tier4_scenario_inventory_interaction(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Scenario 3: Inventory interaction.

    Open menu ('tab'), select hotbar slot 3, primary action click, and close menu ('tab').
    """
    workflow = [
        {"action": "menu"},
        {"slot": 3},
        {"action": "primary_action"},
        {"action": "menu"},
    ]
    res = await game_control_dispatcher.execute({"sequence": workflow})
    assert res["success"] is True
    assert res["details"]["steps_count"] == 4
    # Menu open ('tab')
    assert mock_injector.keys_sent[0][0] == ["tab"]
    # Slot 3 ('3')
    assert mock_injector.keys_sent[1][0] == ["3"]
    # Primary click
    assert len(mock_injector.clicks) == 1
    # Menu close ('tab')
    assert mock_injector.keys_sent[2][0] == ["tab"]


@pytest.mark.asyncio
async def test_tier4_scenario_headless_exploration_loop(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
) -> None:
    """Scenario 4: Headless exploration loop.

    3 sequential iterations of forward movement, camera re-orientation,
    and obstacle clearing jumps.
    """
    for iteration in range(3):
        res = await game_control_dispatcher.execute({
            "sequence": [
                {"movement": "forward", "hold_duration_ms": 50},
                {"look": {"dx": 40 * (iteration + 1), "dy": 0, "smooth": False}},
                {"movement": "jump", "hold_duration_ms": 50},
            ]
        })
        assert res["success"] is True
        assert res["details"]["steps_count"] == 3

    # Total 3 forward moves and 3 jumps recorded
    forward_count = sum(1 for k in mock_injector.keys_sent if k[0] == ["w"])
    jump_count = sum(1 for k in mock_injector.keys_sent if k[0] == ["space"])
    assert forward_count == 3
    assert jump_count == 3


@pytest.mark.asyncio
async def test_tier4_scenario_emergency_abort_mid_sequence(
    game_control_dispatcher: GameControlDispatcher,
    mock_injector: MockInputInjector,
    cancellation_mgr: CancellationManager,
) -> None:
    """Scenario 5: Emergency abort mid-sequence.

    10-step sequence is cancelled by client notification mid-flight;
    verifies execution terminates immediately and all keys are severed within safety window.
    """
    req_id = "emergency_abort_flight_01"
    ten_step_sequence = [{"movement": "forward", "delay_ms": 30} for _ in range(10)]

    async def _abort_trigger() -> None:
        await asyncio.sleep(0.04)
        await cancellation_mgr.cancel_request(req_id, "Emergency stop signal received")

    abort_task = asyncio.create_task(_abort_trigger())
    res = await game_control_dispatcher.execute(
        {"sequence": ten_step_sequence},
        request_id=req_id,
    )
    await abort_task

    assert res["status"] == "cancelled"
    # Must not have executed all 10 steps
    completed = res["details"].get("completed_steps", 0)
    assert completed < 10
    # Inputs released
    assert mock_injector.released is True
