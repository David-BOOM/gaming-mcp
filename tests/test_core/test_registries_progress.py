"""Unit tests for progress tokens, callbacks, and resource update push notifications."""

from typing import Any

import pytest

from gaming_mcp.core.registries import ResourceRegistry, ToolRegistry


@pytest.mark.asyncio
async def test_tool_registry_progress_callback() -> None:
    """ToolRegistry must forward progress_callback to handler functions that accept it."""
    registry = ToolRegistry()
    progress_reports: list[tuple[float, float | None, str | None]] = []

    async def mock_progress_callback(
        progress: float, total: float | None = None, message: str | None = None
    ) -> None:
        progress_reports.append((progress, total, message))

    async def long_running_tool(steps: int = 3, progress_callback: Any = None) -> dict[str, Any]:
        for i in range(1, steps + 1):
            if progress_callback:
                await progress_callback(float(i), float(steps), f"Step {i}/{steps}")
        return {"content": [{"type": "text", "text": "All steps completed"}]}

    registry.register(
        name="long_running_task",
        handler=long_running_tool,
        description="Simulated long-running task with progress reporting",
    )

    res = await registry.execute(
        name="long_running_task",
        arguments={"steps": 3},
        progress_callback=mock_progress_callback,
    )

    assert res["isError"] is False
    assert len(progress_reports) == 3
    assert progress_reports[0] == (1.0, 3.0, "Step 1/3")
    assert progress_reports[2] == (3.0, 3.0, "Step 3/3")


@pytest.mark.asyncio
async def test_resource_registry_update_listeners() -> None:
    """ResourceRegistry must broadcast updates to registered listeners."""
    registry = ResourceRegistry()
    updates_received: list[str] = []

    async def reader() -> dict[str, str]:
        return {"status": "ok"}

    registry.register(
        uri="system://test/telemetry",
        reader=reader,
        name="Test Telemetry",
    )

    async def on_resource_updated(uri: str) -> None:
        updates_received.append(uri)

    registry.add_update_listener(on_resource_updated)

    await registry.notify_updated("system://test/telemetry")
    assert updates_received == ["system://test/telemetry"]

    registry.remove_update_listener(on_resource_updated)
    await registry.notify_updated("system://test/telemetry")
    assert len(updates_received) == 1
