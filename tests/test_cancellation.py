"""Tests for CancellationManager and motor safety release."""

import asyncio

import pytest

from gaming_mcp.core.cancellation import CancellationManager


@pytest.mark.asyncio
async def test_cancellation_task_lifecycle() -> None:
    """Verify tasks can be registered, tracked, and unregistered."""
    manager = CancellationManager()
    assert manager.active_request_count == 0

    async def _dummy_task() -> None:
        await asyncio.sleep(10)

    task = asyncio.create_task(_dummy_task())
    manager.register_task("req-1", task)
    assert manager.active_request_count == 1

    import contextlib

    manager.unregister_task("req-1")
    assert manager.active_request_count == 0
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancellation_triggers_motor_reset() -> None:
    """Verify cancelling an in-flight request aborts the task and runs callbacks."""
    manager = CancellationManager()
    callback_fired = False

    def _motor_reset() -> None:
        nonlocal callback_fired
        callback_fired = True

    manager.register_callback(_motor_reset)

    async def _long_operation() -> None:
        await asyncio.sleep(5)

    task = asyncio.create_task(_long_operation())
    manager.register_task("req-2", task)

    cancelled = await manager.cancel_request("req-2", reason="Agent goal updated")
    assert cancelled is True
    assert callback_fired is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()

    # Unregister callback
    manager.unregister_callback(_motor_reset)
    assert _motor_reset not in manager._callbacks


@pytest.mark.asyncio
async def test_async_cancellation_callback_and_error_tolerance() -> None:
    """Verify async callbacks execute and exceptions in callbacks are logged safely."""
    manager = CancellationManager()
    async_fired = False

    async def _async_reset() -> None:
        nonlocal async_fired
        await asyncio.sleep(0.01)
        async_fired = True

    def _faulty_callback() -> None:
        raise RuntimeError("hardware glitch")

    manager.register_callback(_faulty_callback)
    manager.register_callback(_async_reset)

    await manager.emergency_reset()
    assert async_fired is True
