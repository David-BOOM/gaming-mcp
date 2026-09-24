"""Unit and integration tests for microsecond action chunk scheduler and motor safety."""

import asyncio
from unittest.mock import MagicMock

import pytest

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.io.gamepad import MockGamepadController
from gaming_mcp.io.input import Win32InputInjector
from gaming_mcp.io.timing import ActionChunk, ActionChunkItem, ActionChunkScheduler


@pytest.mark.asyncio
async def test_action_chunk_model_validation() -> None:
    """ActionChunk and ActionChunkItem must enforce schema constraints."""
    item1 = ActionChunkItem(offset_ms=0, type="key_down", params={"key": "w"})
    item2 = ActionChunkItem(offset_ms=50, type="key_up", params={"key": "w"})

    chunk = ActionChunk(actions=[item1, item2], total_duration_ms=100)
    assert len(chunk.actions) == 2
    assert chunk.total_duration_ms == 100


@pytest.mark.asyncio
async def test_action_chunk_execution_successful() -> None:
    """Action chunk scheduler must execute mixed input sequence in chronological order."""
    injector = Win32InputInjector()
    gamepad = MockGamepadController()
    manager = CancellationManager()
    scheduler = ActionChunkScheduler(
        input_injector=injector,
        gamepad=gamepad,
        cancellation_manager=manager,
    )

    chunk = ActionChunk(
        actions=[
            ActionChunkItem(offset_ms=0, type="key_down", params={"key": "w"}),
            ActionChunkItem(offset_ms=10, type="mouse_move", params={"dx": 5, "dy": 0}),
            ActionChunkItem(
                offset_ms=20,
                type="gamepad_axis",
                params={"left_stick": {"x": 0.5, "y": 0.5}},
            ),
            ActionChunkItem(offset_ms=30, type="gamepad_button_down", params={"button": "A"}),
            ActionChunkItem(offset_ms=40, type="gamepad_button_up", params={"button": "A"}),
            ActionChunkItem(offset_ms=50, type="key_up", params={"key": "w"}),
            ActionChunkItem(offset_ms=55, type="sleep", params={}),
        ],
        total_duration_ms=65,
    )

    report = await scheduler.execute_chunk(chunk)
    assert report["status"] == "completed"
    assert report["executed_count"] == 7
    assert report["duration_ms"] >= 40.0

    # Ensure w is released at the end
    assert "w" not in injector.held_keys
    # Gamepad left stick is at (0.5, 0.5)
    assert gamepad.left_stick == (0.5, 0.5)

    # Clean reset
    scheduler.emergency_reset()
    assert gamepad.left_stick == (0.0, 0.0)


@pytest.mark.asyncio
async def test_action_chunk_cancellation_pre_execution() -> None:
    """If cancellation token is set before execution, scheduler aborts immediately."""
    injector = Win32InputInjector()
    gamepad = MockGamepadController()
    scheduler = ActionChunkScheduler(input_injector=injector, gamepad=gamepad)

    cancel_token = asyncio.Event()
    cancel_token.set()

    chunk = ActionChunk(
        actions=[
            ActionChunkItem(offset_ms=10, type="key_down", params={"key": "space"}),
        ],
        total_duration_ms=50,
    )

    report = await scheduler.execute_chunk(chunk, cancellation_token=cancel_token)
    assert report["status"] == "cancelled"
    assert report["executed_count"] == 0
    assert "Cancellation token fired" in report["reason"]
    assert "space" not in injector.held_keys


@pytest.mark.asyncio
async def test_action_chunk_cancellation_mid_execution() -> None:
    """If cancellation token fires mid-chunk, remaining actions are halted and motors released."""
    injector = Win32InputInjector()
    gamepad = MockGamepadController()
    scheduler = ActionChunkScheduler(input_injector=injector, gamepad=gamepad)

    cancel_token = asyncio.Event()

    async def _trigger_cancel_after_delay() -> None:
        await asyncio.sleep(0.015)
        cancel_token.set()

    chunk = ActionChunk(
        actions=[
            ActionChunkItem(offset_ms=0, type="key_down", params={"key": "shift"}),
            ActionChunkItem(offset_ms=50, type="key_down", params={"key": "e"}),
            ActionChunkItem(offset_ms=100, type="key_up", params={"key": "shift"}),
        ],
        total_duration_ms=120,
    )

    cancel_task = asyncio.create_task(_trigger_cancel_after_delay())
    report = await scheduler.execute_chunk(chunk, cancellation_token=cancel_token)
    await cancel_task

    assert report["status"] == "cancelled"
    assert report["executed_count"] <= 2
    # Held shift must be released by emergency_reset
    assert "shift" not in injector.held_keys


@pytest.mark.asyncio
async def test_action_chunk_error_handling() -> None:
    """When an action fails, scheduler calls emergency reset and returns failed report."""
    mock_injector = MagicMock()
    mock_injector.key_down.side_effect = RuntimeError("Simulated driver failure")
    mock_gamepad = MockGamepadController()

    scheduler = ActionChunkScheduler(input_injector=mock_injector, gamepad=mock_gamepad)

    chunk = ActionChunk(
        actions=[
            ActionChunkItem(offset_ms=0, type="key_down", params={"key": "ctrl"}),
        ],
        total_duration_ms=50,
    )

    report = await scheduler.execute_chunk(chunk)
    assert report["status"] == "failed"
    assert "Simulated driver failure" in report["error"]
    mock_injector.release_all.assert_called_once()
