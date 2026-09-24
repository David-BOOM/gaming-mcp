"""Typed registries for MCP Tools, Resources, and Prompts."""

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.exceptions import GamingMCPError

T = TypeVar("T")


@dataclass
class ToolDefinition:
    """Metadata and execution handler for an MCP tool."""

    name: str
    description: str
    handler: Callable[..., Awaitable[Any]]
    input_model: type[BaseModel] | None = None
    input_schema: dict[str, Any] | None = None


class ToolRegistry:
    """Registry managing dynamic MCP tool declarations and execution."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        description: str = "",
        input_model: type[BaseModel] | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a tool definition."""
        schema = input_schema
        if input_model is not None and schema is None:
            schema = input_model.model_json_schema()

        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            handler=handler,
            input_model=input_model,
            input_schema=schema,
        )

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        """Retrieve a tool definition by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """Return all registered tool definitions."""
        return list(self._tools.values())

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        cancellation_manager: CancellationManager | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a tool with argument validation and error envelope handling."""
        tool = self._tools.get(name)
        if not tool:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Tool '{name}' not found in registry"}],
                "error_code": -32601,
            }

        args = arguments or {}

        # Validate arguments against Pydantic model if specified
        if tool.input_model is not None:
            try:
                validated_model = tool.input_model.model_validate(args)
                parsed_args = validated_model.model_dump()
            except ValidationError as val_err:
                return {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Invalid arguments: {val_err}"}],
                    "error_code": -32602,
                }
        else:
            parsed_args = args

        start_time = time.perf_counter()
        current_task = asyncio.current_task()
        if cancellation_manager and request_id and current_task:
            cancellation_manager.register_task(request_id, current_task)

        try:
            # Inspect handler signature to pass arguments appropriately
            sig = inspect.signature(tool.handler)
            if len(sig.parameters) == 0:
                result = await tool.handler()
            elif len(sig.parameters) == 1 and next(iter(sig.parameters.keys())) == "args":
                result = await tool.handler(parsed_args)
            else:
                result = await tool.handler(**parsed_args)

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            # Wrap string, dict, or standard MCP content structure
            if isinstance(result, dict) and "content" in result:
                if "isError" not in result:
                    result["isError"] = False
                result["latency_ms"] = elapsed_ms
                return result

            text_content = str(result) if not isinstance(result, str) else result
            return {
                "isError": False,
                "content": [{"type": "text", "text": text_content}],
                "latency_ms": elapsed_ms,
            }

        except GamingMCPError as gmcp_err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Error [{name}]: {gmcp_err.message}"}],
                "error_code": gmcp_err.error_code,
                "data": gmcp_err.data,
                "latency_ms": elapsed_ms,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unexpected error in '{name}': {exc}"}],
                "error_code": -32000,
                "latency_ms": elapsed_ms,
            }
        finally:
            if cancellation_manager and request_id:
                cancellation_manager.unregister_task(request_id)


@dataclass
class ResourceDefinition:
    """Metadata and reader hook for an MCP resource."""

    uri: str
    name: str
    description: str
    mime_type: str
    reader: Callable[..., Awaitable[bytes | str | dict[str, Any]]]
    subscribers: set[str] = field(default_factory=set)


class ResourceRegistry:
    """Registry managing reactive MCP resources and subscriber tracking."""

    def __init__(self) -> None:
        self._resources: dict[str, ResourceDefinition] = {}

    def register(
        self,
        uri: str,
        reader: Callable[..., Awaitable[bytes | str | dict[str, Any]]],
        name: str = "",
        description: str = "",
        mime_type: str = "application/json",
    ) -> None:
        """Register a readable resource."""
        self._resources[uri] = ResourceDefinition(
            uri=uri,
            name=name or uri,
            description=description,
            mime_type=mime_type,
            reader=reader,
        )

    def unregister(self, uri: str) -> None:
        """Remove a resource from the registry."""
        self._resources.pop(uri, None)

    def get(self, uri: str) -> ResourceDefinition | None:
        """Retrieve resource definition by URI."""
        return self._resources.get(uri)

    def list_resources(self) -> list[ResourceDefinition]:
        """Return all registered resource definitions."""
        return list(self._resources.values())

    async def read(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI and return formatted content object."""
        res = self._resources.get(uri)
        if not res:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Resource '{uri}' not found"}],
                "error_code": -32002,
            }

        try:
            content = await res.reader()
            if isinstance(content, bytes):
                import base64

                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": res.mime_type,
                            "blob": base64.b64encode(content).decode("ascii"),
                        }
                    ]
                }
            if isinstance(content, dict):
                import json

                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": res.mime_type,
                            "text": json.dumps(content),
                        }
                    ]
                }
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": res.mime_type,
                        "text": str(content),
                    }
                ]
            }
        except Exception as exc:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Error reading '{uri}': {exc}"}],
                "error_code": -32000,
            }

    def subscribe(self, uri: str, subscriber_id: str) -> bool:
        """Subscribe client to dynamic resource updates."""
        res = self._resources.get(uri)
        if res:
            res.subscribers.add(subscriber_id)
            return True
        return False

    def unsubscribe(self, uri: str, subscriber_id: str) -> bool:
        """Unsubscribe client from dynamic resource updates."""
        res = self._resources.get(uri)
        if res and subscriber_id in res.subscribers:
            res.subscribers.remove(subscriber_id)
            return True
        return False

    def get_subscribers(self, uri: str) -> set[str]:
        """Return all active subscriber IDs for a resource."""
        res = self._resources.get(uri)
        return set(res.subscribers) if res else set()


@dataclass
class PromptDefinition:
    """Metadata and template renderer for an MCP prompt."""

    name: str
    description: str
    generator: Callable[..., Awaitable[list[dict[str, Any]]]]
    arguments: list[dict[str, Any]] = field(default_factory=list)


class PromptRegistry:
    """Registry managing contextual MCP prompts."""

    def __init__(self) -> None:
        self._prompts: dict[str, PromptDefinition] = {}

    def register(
        self,
        name: str,
        generator: Callable[..., Awaitable[list[dict[str, Any]]]],
        description: str = "",
        arguments: list[dict[str, Any]] | None = None,
    ) -> None:
        """Register a prompt template."""
        self._prompts[name] = PromptDefinition(
            name=name,
            description=description,
            generator=generator,
            arguments=arguments or [],
        )

    def unregister(self, name: str) -> None:
        """Remove a prompt from the registry."""
        self._prompts.pop(name, None)

    def get(self, name: str) -> PromptDefinition | None:
        """Retrieve prompt definition by name."""
        return self._prompts.get(name)

    def list_prompts(self) -> list[PromptDefinition]:
        """Return all registered prompt definitions."""
        return list(self._prompts.values())

    async def render(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Render prompt template with provided arguments."""
        prompt = self._prompts.get(name)
        if not prompt:
            raise KeyError(f"Prompt '{name}' not found")
        args = arguments or {}
        sig = inspect.signature(prompt.generator)
        if len(sig.parameters) == 0:
            return await prompt.generator()
        return await prompt.generator(**args)
