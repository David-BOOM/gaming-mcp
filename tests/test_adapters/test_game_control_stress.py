"""Adversarial empirical stress tests for ComputerUseAdapter.game_control.

Tests cover:
1. Boundary parameter analysis (invalid enums, slot bounds, negative/zero durations,
   malformed chords, huge sequences)
2. Concurrency stress (rapid sequential calls, parallel asyncio.gather bursts, mixed workloads)
3. Mid-sequence cancellation (motor release verification, gamepad reset, structured error response,
   depth unwinding)
4. Security guardrails and lifecycle boundaries (blacklisted process rejection,
   uninitialized access)
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from gaming_mcp.adapters.computer_use import ComputerUseAdapter
from gaming_mcp.config import GamingMCPConfig
from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.exceptions import AdapterError, SecurityViolationError
from gaming_mcp.core.registries import ToolRegistry
from gaming_mcp.io.gamepad import MockGamepadController
from gaming_mcp.io.input import Win32InputInjector
from gaming_mcp.io.process import Win32WindowManager, WindowInfo
from gaming_mcp.io.timing import ActionChunkScheduler
from gaming_mcp.schemas.game_control import ActionType, SequenceStep

SequenceItem = SequenceStep | dict[str, Any]


class StressMockCapturer:
    """Mock capturer for stress testing."""

    def __init__(self) -> None:
        self.closed = False

    @property
    def active_backend(self) -> str:
        return "mock"

    def close(self) -> None:
        self.closed = True


class StressMockInjector(Win32InputInjector):
    """Mock injector tracking calls and release states with thread safety."""

    def __init__(self) -> None:
        super().__init__()
        self.keys_sent: list[tuple[list[str], int, int]] = []
        self.keys_down: list[str] = []
        self.keys_up: list[str] = []
        self.clicks: list[tuple[int, int, str]] = []
        self.relative_moves: list[tuple[int, int]] = []
        self.smooth_looks: list[tuple[int, int, int, int]] = []
        self.released: bool = False
        self.release_count: int = 0
        self._stress_lock = asyncio.Lock()

    def key_down(self, key: str) -> bool:
        self.keys_down.append(key)
        self.released = False
        return True

    def key_up(self, key: str) -> bool:
        self.keys_up.append(key)
        return True

    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        modifiers: Any = None,
    ) -> bool:
        self.clicks.append((x or 0, y or 0, button))
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
        return True

    def release_all(self) -> None:
        self.released = True
        self.release_count += 1
        self.keys_down.clear()


class StressMockWindowManager(Win32WindowManager):
    """Mock window manager for stress testing."""

    def __init__(self, foreground_process: str = "game.exe") -> None:
        self.foreground_process = foreground_process

    def get_foreground_window(self) -> WindowInfo | None:
        return WindowInfo(
            hwnd=5555,
            title="Active Game Window",
            process_name=self.foreground_process,
            process_id=9999,
            rect=(0, 0, 1920, 1080),
        )


StressHarness = tuple[
    ComputerUseAdapter,
    StressMockInjector,
    MockGamepadController,
    StressMockWindowManager,
]


@pytest.fixture
def stress_harness() -> StressHarness:
    """Provide a fresh ComputerUseAdapter and mocks for each stress test."""
    config = GamingMCPConfig()
    config.security.enable_kill_switch = False

    capturer = StressMockCapturer()
    injector = StressMockInjector()
    gamepad = MockGamepadController()
    win_mgr = StressMockWindowManager(foreground_process="game.exe")
    scheduler = ActionChunkScheduler(input_injector=injector, gamepad=gamepad)

    adapter = ComputerUseAdapter(
        config=config,
        screen_capturer=capturer,
        input_injector=injector,
        gamepad_controller=gamepad,
        window_manager=win_mgr,
        action_scheduler=scheduler,
    )
    return adapter, injector, gamepad, win_mgr


# ===========================================================================
# 1. Boundary Parameter Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_boundary_invalid_movement_enum(stress_harness: StressHarness) -> None:
    """Verify invalid movement values are rejected by schema validation."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    invalid_movements = ["fly", "teleport", "hover", "levitate", "", "123"]
    for inv in invalid_movements:
        with pytest.raises(ValidationError):
            await adapter.game_control(movement=inv)

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_boundary_slot_out_of_range(stress_harness: StressHarness) -> None:
    """Verify inventory slots < 1 or > 9 are strictly rejected."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    out_of_bounds_slots = [0, -1, -99, 10, 11, 100]
    for slot in out_of_bounds_slots:
        with pytest.raises(ValidationError):
            await adapter.game_control(slot=slot)

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_boundary_slot_valid_limits(stress_harness: StressHarness) -> None:
    """Verify slots at the boundary edges (1 and 9) execute successfully."""
    adapter, injector, _, _ = stress_harness
    await adapter.initialize()

    res1 = await adapter.game_control(slot=1)
    assert res1["success"] is True
    assert res1["action_type"] == "slot_selection"
    assert injector.keys_sent[-1][0] == ["1"]

    res9 = await adapter.game_control(slot=9)
    assert res9["success"] is True
    assert res9["action_type"] == "slot_selection"
    assert injector.keys_sent[-1][0] == ["9"]

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_boundary_negative_hold_duration(stress_harness: StressHarness) -> None:
    """Verify negative hold duration is rejected by schema validation."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    with pytest.raises(ValidationError):
        await adapter.game_control(movement="forward", hold_duration_ms=-1)

    with pytest.raises(ValidationError):
        await adapter.game_control(movement="forward", hold_duration_ms=-500)

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_boundary_zero_hold_duration(stress_harness: StressHarness) -> None:
    """Verify zero hold duration is accepted and executed without sleeping."""
    adapter, injector, _, _ = stress_harness
    await adapter.initialize()

    res_move = await adapter.game_control(movement="forward", hold_duration_ms=0)
    assert res_move["success"] is True
    assert injector.keys_sent[-1][1] == 0

    res_chord = await adapter.game_control(chord=["ctrl", "c"], hold_duration_ms=0)
    assert res_chord["success"] is True
    assert injector.keys_down[-2:] == ["ctrl", "c"]
    assert injector.keys_up[-2:] == ["c", "ctrl"]

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_boundary_malformed_chord_inputs(stress_harness: StressHarness) -> None:
    """Verify malformed and extreme chord inputs are handled safely."""
    adapter, injector, _, _ = stress_harness
    await adapter.initialize()

    # Empty list chord
    res_empty = await adapter.game_control(chord=[])
    assert res_empty["success"] is True
    assert res_empty["action_type"] == "chord"
    assert res_empty["details"]["keys"] == []

    # Large chord with multiple keys
    large_chord = ["ctrl", "alt", "shift", "f12", "space"]
    res_large = await adapter.game_control(chord=large_chord, hold_duration_ms=10)
    assert res_large["success"] is True
    assert injector.keys_down[-len(large_chord):] == large_chord
    assert injector.keys_up[-len(large_chord):] == list(reversed(large_chord))

    # Invalid chord type (string instead of list)
    with pytest.raises(ValidationError):
        await adapter.game_control(chord="ctrl+c")  # type: ignore[arg-type]

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_boundary_invalid_sequence_step_params(stress_harness: StressHarness) -> None:
    """Verify invalid parameters inside sequence steps trigger validation errors."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    # Step with invalid slot
    with pytest.raises(ValidationError):
        await adapter.game_control(sequence=[{"slot": 0}])

    # Step with negative delay
    with pytest.raises(ValidationError):
        await adapter.game_control(sequence=[{"movement": "forward", "delay_ms": -10}])

    # Step with negative hold duration
    with pytest.raises(ValidationError):
        await adapter.game_control(sequence=[{"movement": "forward", "hold_duration_ms": -5}])

    # Step with invalid action
    with pytest.raises(ValidationError):
        await adapter.game_control(sequence=[{"action": "unknown_action_xyz"}])

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_boundary_huge_sequence_execution(stress_harness: StressHarness) -> None:
    """Verify a sequence of 100 compound steps executes cleanly without recursion limit or leak."""
    adapter, injector, _, _ = stress_harness
    await adapter.initialize()

    step_count = 100
    steps: list[SequenceItem] = [
        {"movement": "forward", "hold_duration_ms": 0, "delay_ms": 0}
        for _ in range(step_count)
    ]

    res = await adapter.game_control(sequence=steps)
    assert res["success"] is True
    assert res["status"] == "executed"
    assert res["action_type"] == "sequence"
    assert res["details"]["steps_count"] == step_count
    assert len(res["details"]["steps"]) == step_count
    assert len(injector.keys_sent) == step_count
    assert adapter._active_control_depth == 0

    await adapter.shutdown()


# ===========================================================================
# 2. Concurrency Stress Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_concurrency_rapid_sequential_calls(stress_harness: StressHarness) -> None:
    """Verify 30 rapid sequential calls execute without state corruption."""
    adapter, injector, _, _ = stress_harness
    await adapter.initialize()

    call_count = 30
    for _i in range(call_count):
        res = await adapter.game_control(movement="jump", hold_duration_ms=0)
        assert res["success"] is True
        assert res["action_type"] == "movement_jump"
        assert adapter._active_control_depth == 0

    assert len(injector.keys_sent) == call_count
    assert adapter._active_control_depth == 0

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_concurrency_parallel_gather_calls(stress_harness: StressHarness) -> None:
    """Verify 25 parallel game_control calls via asyncio.gather complete cleanly."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    tasks = [
        adapter.game_control(movement="strafe_left", hold_duration_ms=0)
        for _ in range(25)
    ]
    results = await asyncio.gather(*tasks)

    assert len(results) == 25
    for res in results:
        assert res["success"] is True
        assert res["action_type"] == "movement_strafe_left"

    assert adapter._active_control_depth == 0
    await adapter.shutdown()


@pytest.mark.asyncio
async def test_concurrency_high_load_mixed_workload(stress_harness: StressHarness) -> None:
    """Verify 50 mixed concurrent tasks across all action categories run safely."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    tasks: list[asyncio.Task[dict[str, Any]]] = []

    for i in range(50):
        mod = i % 5
        if mod == 0:
            coro = adapter.game_control(movement="forward", hold_duration_ms=1)
        elif mod == 1:
            coro = adapter.game_control(look={"direction": "look_left", "smooth": False})
        elif mod == 2:
            coro = adapter.game_control(action="primary_action")
        elif mod == 3:
            coro = adapter.game_control(slot=min(9, (i % 9) + 1))
        else:
            coro = adapter.game_control(chord=["w", "shift"], hold_duration_ms=1)

        tasks.append(asyncio.create_task(coro))

    results = await asyncio.gather(*tasks)
    assert len(results) == 50
    for res in results:
        assert res["success"] is True

    assert adapter._active_control_depth == 0
    await adapter.shutdown()


# ===========================================================================
# 3. Cancellation Stress Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_cancellation_mid_sequence_aborts_and_releases(stress_harness: StressHarness) -> None:
    """Verify mid-sequence task cancellation halts execution and immediately resets motors."""
    adapter, injector, gamepad, _ = stress_harness
    await adapter.initialize()

    # 10 steps each delayed by 40ms (total ~400ms)
    steps: list[SequenceItem] = [{"movement": "forward", "delay_ms": 40} for _ in range(10)]

    task = asyncio.create_task(adapter.game_control(sequence=steps))
    # Allow 2 steps to process (~80ms)
    await asyncio.sleep(0.09)
    task.cancel()

    res = await task
    assert res["success"] is False
    assert res["status"] == "cancelled"
    assert res["action_type"] == "aborted"
    assert res["details"]["completed_steps"] >= 1
    assert res["details"]["completed_steps"] < 10

    # Motor release verified
    assert injector.released is True
    assert injector.release_count >= 1
    assert gamepad.left_stick == (0.0, 0.0)

    # Active depth unwound to 0
    assert adapter._active_control_depth == 0

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_cancellation_during_chord_hold(stress_harness: StressHarness) -> None:
    """Verify task cancellation during a chord hold releases held keys immediately."""
    adapter, injector, gamepad, _ = stress_harness
    await adapter.initialize()

    # Large hold duration (500ms)
    task = asyncio.create_task(
        adapter.game_control(chord=["ctrl", "shift", "alt"], hold_duration_ms=500)
    )
    await asyncio.sleep(0.02)
    task.cancel()

    res = await task
    assert res["success"] is False
    assert res["status"] == "cancelled"
    assert injector.released is True
    assert gamepad.left_stick == (0.0, 0.0)
    assert adapter._active_control_depth == 0

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_cancellation_pre_cancelled_task(stress_harness: StressHarness) -> None:
    """Verify pre-cancelled task immediately releases motors without executing actions."""
    adapter, injector, gamepad, _ = stress_harness
    await adapter.initialize()

    async def _cancelled_runner() -> dict[str, Any]:
        cur = asyncio.current_task()
        if cur:
            cur.cancel()
        return await adapter.game_control(movement="forward")

    task = asyncio.create_task(_cancelled_runner())
    try:
        res = await task
        assert res["success"] is False
        assert res["status"] == "cancelled"
    except asyncio.CancelledError:
        # Standard Python 3.12 task cancellation propagation
        pass

    assert injector.released is True
    assert gamepad.left_stick == (0.0, 0.0)
    assert len(injector.keys_sent) == 0
    assert adapter._active_control_depth == 0

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_cancellation_depth_unwinding(stress_harness: StressHarness) -> None:
    """Verify active control depth cleanly unwinds to 0 across recursive cancellation."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    seq: list[SequenceItem] = [{"movement": "forward", "delay_ms": 50} for _ in range(5)]
    task = asyncio.create_task(adapter.game_control(sequence=seq))
    await asyncio.sleep(0.01)
    task.cancel()
    await task

    assert adapter._active_control_depth == 0
    await adapter.shutdown()


# ===========================================================================
# 4. Security Guardrail & Lifecycle Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_security_blacklist_rejection(stress_harness: StressHarness) -> None:
    """Verify game_control is blocked when the active window is a blacklisted process."""
    adapter, injector, _, win_mgr = stress_harness
    # Set foreground window to cmd.exe (blacklisted)
    win_mgr.foreground_process = "cmd.exe"
    await adapter.initialize()

    with pytest.raises(SecurityViolationError) as exc_info:
        await adapter.game_control(movement="forward")

    assert "cmd.exe" in str(exc_info.value).lower()
    assert len(injector.keys_sent) == 0
    assert adapter._active_control_depth == 0

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_uninitialized_adapter_rejection(stress_harness: StressHarness) -> None:
    """Verify game_control raises AdapterError if called before initialize()."""
    adapter, _, _, _ = stress_harness

    with pytest.raises(AdapterError):
        await adapter.game_control(movement="forward")


@pytest.mark.asyncio
async def test_tool_registry_mcp_validation_envelopes(stress_harness: StressHarness) -> None:
    """Verify ToolRegistry wraps validation failures into standard MCP -32602 error envelopes."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    registry = ToolRegistry()
    adapter.register_tools(registry)

    # Invalid movement
    res_bad_move = await registry.execute("game_control", {"movement": "invalid_movement"})
    assert res_bad_move["isError"] is True
    assert res_bad_move["error_code"] == -32602

    # Out of range slot
    res_bad_slot = await registry.execute("game_control", {"slot": 15})
    assert res_bad_slot["isError"] is True
    assert res_bad_slot["error_code"] == -32602

    # Negative hold duration
    res_bad_hold = await registry.execute("game_control", {"hold_duration_ms": -50})
    assert res_bad_hold["isError"] is True
    assert res_bad_hold["error_code"] == -32602

    # Valid execution through registry
    res_valid = await registry.execute("game_control", {"movement": "forward"})
    assert res_valid["isError"] is False

    await adapter.shutdown()


# ===========================================================================
# 5. Advanced Adversarial Stress & Chaos Scenarios
# ===========================================================================

@pytest.mark.asyncio
async def test_adversarial_cancellation_manager_abort(stress_harness: StressHarness) -> None:
    """Verify CancellationManager.cancel_request halts game_control and triggers motor reset."""
    adapter, injector, gamepad, _ = stress_harness
    await adapter.initialize()

    cm = CancellationManager()
    cm.register_callback(injector.release_all)
    cm.register_callback(gamepad.reset)

    req_id = "req_chaos_abort_99"
    seq: list[SequenceItem] = [{"movement": "forward", "delay_ms": 30} for _ in range(8)]

    async def _runner() -> dict[str, Any]:
        task = asyncio.current_task()
        if task:
            cm.register_task(req_id, task)
        return await adapter.game_control(sequence=seq, request_id=req_id)

    task = asyncio.create_task(_runner())
    await asyncio.sleep(0.05)
    cancelled = await cm.cancel_request(req_id, "Chaos stress cancellation")
    assert cancelled is True

    res = await task
    assert res["status"] == "cancelled"
    assert injector.released is True
    assert gamepad.left_stick == (0.0, 0.0)
    assert res["details"]["completed_steps"] < 8
    assert adapter._active_control_depth == 0

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_adversarial_concurrent_chaos_workload(stress_harness: StressHarness) -> None:
    """Verify adapter under mixed concurrent burst where random tasks are cancelled."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    tasks: list[asyncio.Task[dict[str, Any]]] = []
    task_types: list[str] = []

    for i in range(40):
        if i % 4 == 0:
            # Slow sequence destined to be cancelled
            seq: list[SequenceItem] = [{"movement": "backward", "delay_ms": 50} for _ in range(5)]
            t = asyncio.create_task(adapter.game_control(sequence=seq))
            tasks.append(t)
            task_types.append("to_cancel")
        else:
            # Fast normal commands
            t = asyncio.create_task(
                adapter.game_control(movement="forward", hold_duration_ms=0)
            )
            tasks.append(t)
            task_types.append("normal")

    # Let execution begin
    await asyncio.sleep(0.03)

    # Cancel target tasks
    for _idx, (t, t_type) in enumerate(zip(tasks, task_types, strict=False)):
        if t_type == "to_cancel":
            t.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)

    cancelled_count = 0
    success_count = 0

    for _idx, r in enumerate(results):
        if isinstance(r, dict):
            if r.get("status") == "cancelled":
                cancelled_count += 1
            elif r.get("success") is True:
                success_count += 1
        elif isinstance(r, asyncio.CancelledError):
            cancelled_count += 1

    assert success_count == 30
    assert cancelled_count == 10
    assert adapter._active_control_depth == 0

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_boundary_empty_sequence_and_noop(stress_harness: StressHarness) -> None:
    """Verify empty sequence and empty arguments return valid responses."""
    adapter, _, _, _ = stress_harness
    await adapter.initialize()

    # Empty sequence
    res_empty_seq = await adapter.game_control(sequence=[])
    assert res_empty_seq["success"] is True
    assert res_empty_seq["action_type"] == "sequence"
    assert res_empty_seq["details"]["steps_count"] == 0

    # No arguments (noop)
    res_noop = await adapter.game_control()
    assert res_noop["success"] is True
    assert res_noop["status"] == "noop"
    assert res_noop["action_type"] == "none"

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_look_precedence_and_angular_conversion(stress_harness: StressHarness) -> None:
    """Verify angular yaw/pitch overrides cardinal directions and dx/dy deltas."""
    adapter, injector, _, _ = stress_harness
    await adapter.initialize()

    # Yaw 18 degrees (at 5 px/deg -> 90 px), smooth=False
    res_yaw = await adapter.game_control(
        look={"direction": "look_left", "dx": -100, "yaw": 18.0, "smooth": False}
    )
    assert res_yaw["success"] is True
    assert res_yaw["details"]["dx"] == 90
    assert (90, 0) in injector.relative_moves

    # Pitch -15 degrees (at 5 px/deg -> -75 px), smooth=False
    res_pitch = await adapter.game_control(
        look={"direction": "look_up", "dy": -200, "pitch": -15.0, "smooth": False}
    )
    assert res_pitch["success"] is True
    assert res_pitch["details"]["dy"] == -75
    assert (0, -75) in injector.relative_moves

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_all_action_types_execution(stress_harness: StressHarness) -> None:
    """Verify all 6 ActionType variants map to their expected hardware actions."""
    adapter, injector, _, _ = stress_harness
    await adapter.initialize()

    # 1. Primary action (left click)
    res1 = await adapter.game_control(action=ActionType.PRIMARY_ACTION)
    assert res1["success"] is True
    assert injector.clicks[-1][2] == "left"

    # 2. Secondary action (right click)
    res2 = await adapter.game_control(action=ActionType.SECONDARY_ACTION)
    assert res2["success"] is True
    assert injector.clicks[-1][2] == "right"

    # 3. Interact ('e')
    res3 = await adapter.game_control(action=ActionType.INTERACT)
    assert res3["success"] is True
    assert injector.keys_sent[-1][0] == ["e"]

    # 4. Reload ('r')
    res4 = await adapter.game_control(action=ActionType.RELOAD)
    assert res4["success"] is True
    assert injector.keys_sent[-1][0] == ["r"]

    # 5. Pause ('escape')
    res5 = await adapter.game_control(action=ActionType.PAUSE)
    assert res5["success"] is True
    assert injector.keys_sent[-1][0] == ["escape"]

    # 6. Menu ('tab')
    res6 = await adapter.game_control(action=ActionType.MENU)
    assert res6["success"] is True
    assert injector.keys_sent[-1][0] == ["tab"]

    await adapter.shutdown()
