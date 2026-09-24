"""Tests for GamingMCPServer lifecycle, health reporting, and transport routing."""

from unittest.mock import AsyncMock

import pytest

from gaming_mcp import __version__
from gaming_mcp.config import GamingMCPConfig, TransportType
from gaming_mcp.server import GamingMCPServer, _get_process_memory_mb


@pytest.mark.asyncio
async def test_server_initialization_and_builtins() -> None:
    """Verify server initializes with built-in tools and health resource."""
    server = GamingMCPServer()
    assert server.config.transport == TransportType.STDIO
    assert server.is_running is False

    # Check built-in tools
    health_tool = server.tools.get("server_health")
    assert health_tool is not None
    ping_tool = server.tools.get("ping")
    assert ping_tool is not None

    # Execute health tool
    health_res = await server.tools.execute("server_health")
    assert health_res["isError"] is False

    # Execute ping tool
    ping_res = await server.tools.execute("ping")
    assert ping_res["isError"] is False

    # Check built-in resource
    health_res_def = server.resources.get("system://server/health")
    assert health_res_def is not None
    read_res = await server.resources.read("system://server/health")
    assert "contents" in read_res
    assert "server_version" in read_res["contents"][0]["text"]


def test_server_telemetry_payload() -> None:
    """Verify get_health returns all specified Part XIII metrics."""
    server = GamingMCPServer()
    health = server.get_health()

    assert health["server_version"] == __version__
    assert health["uptime_seconds"] >= 0.0
    assert health["transport"] == "stdio"
    assert health["active_adapter"] == "computer_use"
    assert "minecraft" in health["adapters_available"]
    assert health["kill_switch_armed"] is True
    assert health["tools_registered"] >= 2
    assert "memory_rss_mb" in health


def test_process_memory_helper() -> None:
    """Verify process memory reader does not throw and returns float >= 0."""
    mem = _get_process_memory_mb()
    assert isinstance(mem, float)
    assert mem >= 0.0


@pytest.mark.asyncio
async def test_server_shutdown_and_motor_reset() -> None:
    """Verify server shutdown executes motor safety reset."""
    server = GamingMCPServer()
    reset_fired = False

    def _reset() -> None:
        nonlocal reset_fired
        reset_fired = True

    server.cancellation_manager.register_callback(_reset)
    server.is_running = True

    await server.shutdown()
    assert server.is_running is False
    assert reset_fired is True

    # Calling shutdown again when not running is a no-op
    await server.shutdown()


@pytest.mark.asyncio
async def test_server_transport_dispatch() -> None:
    """Verify server start routes to correct transport runner."""
    # Test stdio
    stdio_server = GamingMCPServer(GamingMCPConfig(transport=TransportType.STDIO))
    stdio_server.run_stdio = AsyncMock()  # type: ignore[method-assign]
    await stdio_server.start()
    stdio_server.run_stdio.assert_awaited_once()

    # Test SSE
    sse_server = GamingMCPServer(GamingMCPConfig(transport=TransportType.SSE))
    sse_server.run_sse = AsyncMock()  # type: ignore[method-assign]
    await sse_server.start()
    sse_server.run_sse.assert_awaited_once()

    # Test HTTP
    http_server = GamingMCPServer(GamingMCPConfig(transport=TransportType.HTTP))
    http_server.run_streamable_http = AsyncMock()  # type: ignore[method-assign]
    await http_server.start()
    http_server.run_streamable_http.assert_awaited_once()


@pytest.mark.asyncio
async def test_server_transport_runners() -> None:
    """Verify run_stdio, run_sse, and run_streamable_http invoke underlying MCPServer."""
    server = GamingMCPServer()

    # stdio
    server.mcp_server.run_stdio_async = AsyncMock()  # type: ignore[method-assign]
    await server.run_stdio()
    server.mcp_server.run_stdio_async.assert_awaited_once()
    assert server.is_running is False

    # sse
    server.mcp_server.run_sse_async = AsyncMock()  # type: ignore[method-assign]
    await server.run_sse(host="0.0.0.0", port=9000)
    server.mcp_server.run_sse_async.assert_awaited_once_with(host="0.0.0.0", port=9000)
    assert server.is_running is False

    # streamable http
    server.mcp_server.run_streamable_http_async = AsyncMock()  # type: ignore[method-assign]
    await server.run_streamable_http(host="0.0.0.0", port=9001)
    server.mcp_server.run_streamable_http_async.assert_awaited_once_with(host="0.0.0.0", port=9001)
    assert server.is_running is False

