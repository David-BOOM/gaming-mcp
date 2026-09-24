"""Dynamic Adapter Router for hot-swapping game integrations at runtime."""

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.core.exceptions import AdapterNotFoundError

if TYPE_CHECKING:
    from gaming_mcp.server import GamingMCPServer

logger = logging.getLogger("gaming_mcp.adapters.router")


class SwitchAdapterInput(BaseModel):
    """Input parameters for the switch_adapter tool."""

    adapter_id: str = Field(
        ...,
        description=(
            "Target adapter identifier to activate (e.g. 'computer_use', 'minecraft', 'retro')"
        ),
    )


class AdapterRouter:
    """Registry and state machine for managing multiple game adapters with dynamic hot-swapping."""

    def __init__(self) -> None:
        self._adapters: dict[str, GameAdapter] = {}
        self._active_adapter_id: str | None = None
        self._bound_tool_names: set[str] = set()
        self._bound_resource_uris: set[str] = set()
        self._bound_prompt_names: set[str] = set()

    @property
    def active_adapter_id(self) -> str | None:
        """Return ID of currently active adapter."""
        return self._active_adapter_id

    @property
    def active_adapter(self) -> GameAdapter | None:
        """Return currently active adapter instance."""
        if self._active_adapter_id:
            return self._adapters.get(self._active_adapter_id)
        return None

    def register_adapter(self, adapter: GameAdapter) -> None:
        """Register a GameAdapter instance into the router."""
        meta = adapter.metadata
        self._adapters[meta.id] = adapter
        logger.info("Registered adapter: %s (%s)", meta.id, meta.display_name)

    async def unregister_adapter(
        self, adapter_id: str, server: "GamingMCPServer | None" = None
    ) -> None:
        """Unregister and shut down an adapter if active."""
        if adapter_id == self._active_adapter_id and server is not None:
            await self._detach_active_adapter(server)

        adapter = self._adapters.pop(adapter_id, None)
        if adapter and adapter.is_initialized:
            try:
                await adapter.shutdown()
            except Exception as exc:
                logger.error(
                    "Error shutting down adapter %s during unregister: %s", adapter_id, exc
                )

    def get_adapter(self, adapter_id: str) -> GameAdapter | None:
        """Retrieve an adapter by ID."""
        return self._adapters.get(adapter_id)

    def list_adapters(self) -> list[AdapterMetadata]:
        """Return metadata for all registered adapters."""
        return [adapter.metadata for adapter in self._adapters.values()]

    async def _detach_active_adapter(self, server: "GamingMCPServer") -> None:
        """Shut down current adapter and detach its tools and resources from server."""
        current = self.active_adapter
        if current:
            logger.info("Detaching active adapter: %s", self._active_adapter_id)
            if current.is_initialized:
                try:
                    await current.shutdown()
                except Exception as exc:
                    logger.warning("Error during active adapter shutdown: %s", exc)

            # Unbind tools
            for tool_name in list(self._bound_tool_names):
                server.tools.unregister(tool_name)
                with contextlib.suppress(Exception):
                    server.mcp_server.remove_tool(tool_name)
            self._bound_tool_names.clear()

            # Unbind resources
            for uri in list(self._bound_resource_uris):
                server.resources.unregister(uri)
            self._bound_resource_uris.clear()

            # Unbind prompts
            for prompt_name in list(self._bound_prompt_names):
                server.prompts.unregister(prompt_name)
                with contextlib.suppress(Exception):
                    server.mcp_server.remove_prompt(prompt_name)
            self._bound_prompt_names.clear()

            self._active_adapter_id = None

    async def switch_adapter(self, adapter_id: str, server: "GamingMCPServer") -> GameAdapter:
        """Hot-swap active adapter to the specified target adapter ID without dropping client."""
        if adapter_id not in self._adapters:
            raise AdapterNotFoundError(adapter_id)

        target = self._adapters[adapter_id]

        if self._active_adapter_id == adapter_id and target.is_initialized:
            logger.info("Adapter '%s' is already active", adapter_id)
            return target

        # Detach previous adapter
        await self._detach_active_adapter(server)

        # Initialize target adapter
        logger.info("Initializing target adapter: %s", adapter_id)
        await target.initialize()

        # Capture registries before and after to track bound items
        tools_before = {t.name for t in server.tools.list_tools()}
        resources_before = {r.uri for r in server.resources.list_resources()}
        prompts_before = {p.name for p in server.prompts.list_prompts()}

        target.register_tools(server.tools)
        target.register_resources(server.resources)
        target.register_prompts(server.prompts)

        # Track which tools/resources/prompts belong to this adapter
        tools_after = {t.name for t in server.tools.list_tools()}
        resources_after = {r.uri for r in server.resources.list_resources()}
        prompts_after = {p.name for p in server.prompts.list_prompts()}

        new_tools = tools_after - tools_before
        self._bound_tool_names = new_tools

        # Register new tools with the underlying MCPServer
        for tool_name in new_tools:
            tool_def = server.tools.get(tool_name)
            if tool_def:
                try:
                    server.mcp_server.add_tool(
                        tool_def.handler,
                        name=tool_name,
                        description=tool_def.description,
                    )
                except Exception as exc:
                    logger.debug("Tool '%s' already attached to MCPServer: %s", tool_name, exc)

        self._bound_resource_uris = resources_after - resources_before
        self._bound_prompt_names = prompts_after - prompts_before
        self._active_adapter_id = adapter_id

        # Update server config default adapter pointer
        server.config.adapters.default_adapter = adapter_id
        logger.info(
            "Successfully switched to adapter '%s' with %d tools and %d resources",
            adapter_id,
            len(self._bound_tool_names),
            len(self._bound_resource_uris),
        )
        return target

    async def health_check(self) -> dict[str, Any]:
        """Aggregate health status across all registered adapters."""
        statuses: dict[str, Any] = {}
        for adapter_id, adapter in self._adapters.items():
            statuses[adapter_id] = await adapter.health_check()
        return {
            "active_adapter": self._active_adapter_id,
            "adapters": statuses,
        }
