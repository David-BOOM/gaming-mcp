"""Core MCP JSON-RPC protocol server and dispatcher for gaming-mcp."""

import ctypes
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import mcp.types as types
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from gaming_mcp import __version__
from gaming_mcp.adapters import AdapterRouter, SwitchAdapterInput
from gaming_mcp.config import GamingMCPConfig, TransportType
from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry

logger = logging.getLogger("gaming_mcp.server")


def _get_process_memory_mb() -> float:
    """Return current process WorkingSetSize (RSS) in MB using Win32 API if available."""
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(ProcessMemoryCounters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return float(round(counters.WorkingSetSize / (1024 * 1024), 2))
        except Exception:
            pass
    return 0.0


class GamingMCPServer:
    """Sovereign Model Context Protocol server for video game observation and actuation."""

    def __init__(self, config: GamingMCPConfig | None = None) -> None:
        self.config = config or GamingMCPConfig()
        self.start_time = time.time()
        self.is_running = False

        self.cancellation_manager = CancellationManager()
        self.tools = ToolRegistry()
        self.resources = ResourceRegistry()
        self.prompts = PromptRegistry()
        self.router = AdapterRouter()

        self.mcp_server = MCPServer(name="gaming-mcp", version=__version__)

        self._setup_cancellation_handler()
        self._register_builtin_tools()
        self._register_builtin_resources()

    def _setup_cancellation_handler(self) -> None:
        """Hook notifications/cancelled into the cancellation manager."""
        try:
            lowlevel = self.mcp_server._lowlevel_server

            async def _on_cancelled(
                _context: Any, params: types.CancelledNotificationParams
            ) -> None:
                request_id = str(params.request_id) if params.request_id is not None else ""
                reason = params.reason or "Client requested cancellation"
                logger.info(
                    "Received notifications/cancelled for request %s: %s",
                    request_id,
                    reason,
                )
                await self.cancellation_manager.cancel_request(request_id, reason)

            lowlevel.add_notification_handler(
                "notifications/cancelled",
                types.CancelledNotificationParams,
                _on_cancelled,
            )
        except Exception as exc:
            logger.warning("Could not bind lowlevel cancellation handler: %s", exc)

    def _register_builtin_tools(self) -> None:
        """Register default diagnostic, health, and adapter management tools."""

        async def _health_tool() -> dict[str, Any]:
            return self.get_health()

        async def _ping_tool() -> dict[str, Any]:
            return {
                "status": "pong",
                "timestamp": datetime.now(UTC).isoformat(),
            }

        async def _switch_adapter_tool(adapter_id: str) -> dict[str, Any]:
            adapter = await self.router.switch_adapter(adapter_id, self)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Successfully activated adapter '{adapter.metadata.id}' "
                            f"({adapter.metadata.display_name})"
                        ),
                    }
                ]
            }

        self.register_tool(
            name="server_health",
            handler=_health_tool,
            description="Retrieve real-time server telemetry, uptime, memory, and subsystem health",
        )
        self.register_tool(
            name="ping",
            handler=_ping_tool,
            description="Verify server connectivity and clock synchronization",
        )
        self.register_tool(
            name="switch_adapter",
            handler=_switch_adapter_tool,
            description="Hot-swap the active game adapter at runtime without dropping connection",
            input_model=SwitchAdapterInput,
        )

    def _register_builtin_resources(self) -> None:
        """Register live telemetry and health resources."""

        async def _health_resource() -> dict[str, Any]:
            return self.get_health()

        self.resources.register(
            uri="system://server/health",
            reader=_health_resource,
            name="Server Health",
            description="Live diagnostic metrics and subsystem connectivity status",
            mime_type="application/json",
        )

    def register_tool(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        description: str = "",
        input_model: type[BaseModel] | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a tool in both the local ToolRegistry and the active MCPServer."""
        self.tools.register(
            name=name,
            handler=handler,
            description=description,
            input_model=input_model,
            input_schema=input_schema,
        )

        # Expose dynamically to the underlying MCPServer
        try:
            self.mcp_server.add_tool(handler, name=name, description=description)
        except Exception as exc:
            logger.debug(
                "Tool '%s' already attached to MCPServer or signature mismatch: %s",
                name,
                exc,
            )

    def get_health(self) -> dict[str, Any]:
        """Compute structured health dictionary per Part XIII of implementation plan."""
        uptime = round(time.time() - self.start_time, 2)
        registered_adapters = [m.id for m in self.router.list_adapters()]
        available = registered_adapters or ["computer_use", "minecraft", "retro", "gymnasium"]
        active = self.router.active_adapter_id or self.config.adapters.default_adapter
        return {
            "server_version": __version__,
            "uptime_seconds": uptime,
            "transport": self.config.transport.value,
            "active_adapter": active,
            "adapters_available": available,
            "screen_capture_backend": self.config.screen.preferred_backend,
            "input_backend": self.config.input.preferred_backend,
            "audio_enabled": self.config.audio.enabled,
            "kill_switch_armed": self.config.security.enable_kill_switch,
            "active_subscriptions": len(self.resources.list_resources()),
            "skills_registered": 0,
            "tools_registered": len(self.tools.list_tools()),
            "memory_rss_mb": _get_process_memory_mb(),
        }

    async def run_stdio(self) -> None:
        """Execute server loop over standard I/O streams."""
        self.is_running = True
        logger.info("Starting gaming-mcp over stdio transport")
        try:
            await self.mcp_server.run_stdio_async()
        finally:
            await self.shutdown()

    async def run_sse(self, host: str | None = None, port: int | None = None) -> None:
        """Execute server loop over Server-Sent Events (SSE)."""
        self.is_running = True
        bind_host = host or self.config.host
        bind_port = port or self.config.port
        logger.info("Starting gaming-mcp over SSE transport at %s:%s", bind_host, bind_port)
        try:
            await self.mcp_server.run_sse_async(host=bind_host, port=bind_port)
        finally:
            await self.shutdown()

    async def run_streamable_http(self, host: str | None = None, port: int | None = None) -> None:
        """Execute server loop over Streamable HTTP."""
        self.is_running = True
        bind_host = host or self.config.host
        bind_port = port or self.config.port
        logger.info("Starting gaming-mcp over Streamable HTTP at %s:%s", bind_host, bind_port)
        try:
            await self.mcp_server.run_streamable_http_async(host=bind_host, port=bind_port)
        finally:
            await self.shutdown()

    async def start(self) -> None:
        """Start server using configured transport."""
        if self.config.transport == TransportType.STDIO:
            await self.run_stdio()
        elif self.config.transport == TransportType.SSE:
            await self.run_sse()
        elif self.config.transport == TransportType.HTTP:
            await self.run_streamable_http()

    async def shutdown(self) -> None:
        """Gracefully release drivers, reset motors, and halt active routines."""
        if not self.is_running:
            return
        self.is_running = False
        logger.info("Shutting down gaming-mcp server")
        # Shut down active adapter if any
        if self.router.active_adapter_id:
            await self.router.unregister_adapter(self.router.active_adapter_id, self)
        # Trigger emergency motor reset to release physical/virtual keys
        await self.cancellation_manager.emergency_reset()
