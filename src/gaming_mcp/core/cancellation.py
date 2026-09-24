"""Cancellation manager and motor safety reset dispatcher for gaming-mcp."""

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("gaming_mcp.core.cancellation")

CancellationCallback = Callable[[], Awaitable[None] | None]


class CancellationManager:
    """Tracks in-flight async operations and guarantees motor safety release on cancellation."""

    def __init__(self) -> None:
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}
        self._callbacks: list[CancellationCallback] = []
        self._lock = asyncio.Lock()

    def register_task(self, request_id: str, task: asyncio.Task[Any]) -> None:
        """Bind an active asyncio task to an MCP request ID."""
        self._active_tasks[request_id] = task

    def unregister_task(self, request_id: str) -> None:
        """Remove task upon normal completion."""
        self._active_tasks.pop(request_id, None)

    def register_callback(self, callback: CancellationCallback) -> None:
        """Register a motor safety reset callback (e.g. release held keys)."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: CancellationCallback) -> None:
        """Unregister a previously registered callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def emergency_reset(self) -> None:
        """Execute all registered motor reset callbacks unconditionally."""
        for cb in self._callbacks:
            try:
                res = cb()
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                logger.error("Error executing cancellation callback: %s", exc, exc_info=True)

    async def cancel_request(self, request_id: str, reason: str = "") -> bool:
        """Cancel the specified in-flight task and trigger emergency motor reset."""
        async with self._lock:
            task = self._active_tasks.pop(request_id, None)
            # Execute safety motor reset immediately
            await self.emergency_reset()

            if task and not task.done():
                logger.info(
                    "Cancelling request %s (reason: %s)",
                    request_id,
                    reason or "unspecified",
                )
                task.cancel()
                return True
            return False

    @property
    def active_request_count(self) -> int:
        """Return the number of tracked active requests."""
        return len(self._active_tasks)
