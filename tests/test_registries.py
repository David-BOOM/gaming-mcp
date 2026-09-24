"""Tests for ToolRegistry, ResourceRegistry, and PromptRegistry."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, Field

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.exceptions import SecurityViolationError
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry


class ClickInput(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)


@pytest.mark.asyncio
async def test_tool_registry_registration_and_execution() -> None:
    """Verify tool registration, schema validation, and execution."""
    registry = ToolRegistry()

    async def _click_handler(x: int, y: int) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": f"Clicked at {x},{y}"}]}

    registry.register(
        name="mouse_click",
        handler=_click_handler,
        description="Click at screen coordinates",
        input_model=ClickInput,
    )

    tool = registry.get("mouse_click")
    assert tool is not None
    assert tool.name == "mouse_click"
    assert tool.input_schema is not None
    assert "properties" in tool.input_schema
    assert len(registry.list_tools()) == 1

    # Valid execution
    res = await registry.execute("mouse_click", {"x": 100, "y": 200})
    assert res["isError"] is False
    assert "Clicked at 100,200" in res["content"][0]["text"]
    assert "latency_ms" in res

    # Invalid arguments (violating Pydantic schema ge=0)
    err_res = await registry.execute("mouse_click", {"x": -10, "y": 200})
    assert err_res["isError"] is True
    assert err_res["error_code"] == -32602

    # Tool not found
    missing_res = await registry.execute("nonexistent_tool")
    assert missing_res["isError"] is True
    assert missing_res["error_code"] == -32601

    # Unregister
    registry.unregister("mouse_click")
    assert registry.get("mouse_click") is None


@pytest.mark.asyncio
async def test_tool_registry_exception_handling() -> None:
    """Verify tool execution catches GamingMCPError and unexpected exceptions."""
    registry = ToolRegistry()

    async def _faulty_tool() -> None:
        raise SecurityViolationError("process_blacklist", "Attempted to click cmd.exe")

    async def _crash_tool() -> None:
        raise ZeroDivisionError("division by zero")

    registry.register("faulty", _faulty_tool)
    registry.register("crash", _crash_tool)

    # Handled GamingMCPError
    res_handled = await registry.execute("faulty")
    assert res_handled["isError"] is True
    assert res_handled["error_code"] == -32004
    assert "cmd.exe" in res_handled["content"][0]["text"]

    # Unexpected Exception
    res_crash = await registry.execute("crash")
    assert res_crash["isError"] is True
    assert res_crash["error_code"] == -32000
    assert "division by zero" in res_crash["content"][0]["text"]


@pytest.mark.asyncio
async def test_tool_cancellation_tracking() -> None:
    """Verify tool execution registers task in CancellationManager."""
    registry = ToolRegistry()
    manager = CancellationManager()

    async def _long_task() -> str:
        await asyncio.sleep(5)
        return "done"

    registry.register("long_task", _long_task)

    import contextlib

    task = asyncio.create_task(
        registry.execute("long_task", cancellation_manager=manager, request_id="call-42")
    )
    # Give task a moment to register
    await asyncio.sleep(0.01)
    assert manager.active_request_count == 1

    await manager.cancel_request("call-42")
    assert manager.active_request_count == 0
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_resource_registry_and_subscriptions() -> None:
    """Verify resource registration, reading, and subscription management."""
    registry = ResourceRegistry()

    async def _json_reader() -> dict[str, Any]:
        return {"health": "ok", "fps": 60}

    async def _bytes_reader() -> bytes:
        return b"\x89PNG\r\n\x1a\n"

    registry.register("game://telemetry", _json_reader, name="Game Telemetry")
    registry.register("game://screenshot", _bytes_reader, name="Screenshot", mime_type="image/png")

    assert len(registry.list_resources()) == 2

    # Read JSON resource
    json_res = await registry.read("game://telemetry")
    assert "contents" in json_res
    assert "fps" in json_res["contents"][0]["text"]

    # Read bytes resource
    bytes_res = await registry.read("game://screenshot")
    assert "blob" in bytes_res["contents"][0]

    # Read missing resource
    missing_res = await registry.read("game://missing")
    assert missing_res["isError"] is True

    # Subscription management
    sub_ok = registry.subscribe("game://telemetry", "client-1")
    assert sub_ok is True
    assert "client-1" in registry.get_subscribers("game://telemetry")

    unsub_ok = registry.unsubscribe("game://telemetry", "client-1")
    assert unsub_ok is True
    assert "client-1" not in registry.get_subscribers("game://telemetry")

    # Unregister resource
    registry.unregister("game://screenshot")
    assert registry.get("game://screenshot") is None


@pytest.mark.asyncio
async def test_prompt_registry() -> None:
    """Verify prompt template registration and rendering."""
    registry = PromptRegistry()

    async def _game_playbook(game: str = "minesweeper") -> list[dict[str, Any]]:
        return [{"role": "user", "content": f"Playbook strategy for {game}"}]

    registry.register(
        name="game_strategy",
        generator=_game_playbook,
        description="Contextual strategy scaffold",
        arguments=[{"name": "game", "required": False}],
    )

    prompt = registry.get("game_strategy")
    assert prompt is not None
    assert len(registry.list_prompts()) == 1

    messages = await registry.render("game_strategy", {"game": "minecraft"})
    assert "minecraft" in messages[0]["content"]

    with pytest.raises(KeyError):
        await registry.render("missing_prompt")

    registry.unregister("game_strategy")
    assert registry.get("game_strategy") is None
