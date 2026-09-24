"""Tests for GameAdapter SPI and dynamic AdapterRouter."""

from typing import Any

import pytest

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.adapters.router import AdapterRouter
from gaming_mcp.config import GamingMCPConfig
from gaming_mcp.core.exceptions import AdapterNotFoundError
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry
from gaming_mcp.server import GamingMCPServer


class MockGameAdapter(GameAdapter):
    """Mock game adapter for router testing."""

    def __init__(self, config: GamingMCPConfig, adapter_id: str = "mock_game") -> None:
        super().__init__(config)
        self._id = adapter_id
        self.init_called = False
        self.shutdown_called = False

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            id=self._id,
            display_name=f"Mock Game {self._id}",
            version="1.0.0",
            description="Mock adapter for testing",
            author="Test Runner",
        )

    async def initialize(self) -> None:
        self.init_called = True
        self.is_initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True
        self.is_initialized = False

    def register_tools(self, registry: ToolRegistry) -> None:
        async def _mock_action() -> str:
            return f"Action from {self._id}"

        registry.register(f"{self._id}_action", _mock_action, description="Mock action")

    def register_resources(self, registry: ResourceRegistry) -> None:
        async def _mock_telemetry() -> dict[str, Any]:
            return {"game": self._id, "score": 100}

        registry.register(f"game://{self._id}/stats", _mock_telemetry, name=f"{self._id} Stats")

    def register_prompts(self, registry: PromptRegistry) -> None:
        async def _mock_prompt() -> list[dict[str, Any]]:
            return [{"role": "user", "content": f"Strategy for {self._id}"}]

        registry.register(f"{self._id}_strategy", _mock_prompt, description="Mock prompt")


@pytest.mark.asyncio
async def test_adapter_metadata_and_defaults(default_config: GamingMCPConfig) -> None:
    """Verify AdapterMetadata validation and defaults."""
    adapter = MockGameAdapter(default_config, "test_game")
    meta = adapter.metadata
    assert meta.id == "test_game"
    assert meta.display_name == "Mock Game test_game"
    assert meta.version == "1.0.0"
    assert "win32" in meta.supported_platforms
    assert meta.requires_display is True
    assert meta.requires_admin_privileges is False

    health = await adapter.health_check()
    assert health["adapter_id"] == "test_game"
    assert health["status"] == "uninitialized"


@pytest.mark.asyncio
async def test_router_registration_and_listing(default_config: GamingMCPConfig) -> None:
    """Verify router registers, retrieves, and lists adapters."""
    router = AdapterRouter()
    adapter1 = MockGameAdapter(default_config, "game_1")
    adapter2 = MockGameAdapter(default_config, "game_2")

    router.register_adapter(adapter1)
    router.register_adapter(adapter2)

    assert router.get_adapter("game_1") is adapter1
    assert router.get_adapter("game_2") is adapter2
    assert router.get_adapter("nonexistent") is None

    adapters_meta = router.list_adapters()
    assert len(adapters_meta) == 2
    assert {m.id for m in adapters_meta} == {"game_1", "game_2"}


@pytest.mark.asyncio
async def test_router_switch_adapter_lifecycle(default_config: GamingMCPConfig) -> None:
    """Verify switching between adapters initializes new and detaches old."""
    server = GamingMCPServer(default_config)
    adapter1 = MockGameAdapter(default_config, "game_1")
    adapter2 = MockGameAdapter(default_config, "game_2")

    server.router.register_adapter(adapter1)
    server.router.register_adapter(adapter2)

    # 1. Switch to game_1
    active1 = await server.router.switch_adapter("game_1", server)
    assert active1 is adapter1
    assert adapter1.init_called is True
    assert adapter1.is_initialized is True
    assert server.router.active_adapter_id == "game_1"
    assert server.router.active_adapter is adapter1

    # Verify game_1 tools, resources, prompts bound to server
    assert server.tools.get("game_1_action") is not None
    assert server.resources.get("game://game_1/stats") is not None
    assert server.prompts.get("game_1_strategy") is not None

    # Execute bound tool
    tool_res = await server.tools.execute("game_1_action")
    assert tool_res["isError"] is False
    assert "Action from game_1" in tool_res["content"][0]["text"]

    # 2. Switch to game_2
    active2 = await server.router.switch_adapter("game_2", server)
    assert active2 is adapter2
    assert adapter1.shutdown_called is True
    assert adapter1.is_initialized is False
    assert adapter2.init_called is True
    assert adapter2.is_initialized is True
    assert server.router.active_adapter_id == "game_2"

    # Verify game_1 items unbound, game_2 items bound
    assert server.tools.get("game_1_action") is None
    assert server.resources.get("game://game_1/stats") is None
    assert server.prompts.get("game_1_strategy") is None

    assert server.tools.get("game_2_action") is not None
    assert server.resources.get("game://game_2/stats") is not None
    assert server.prompts.get("game_2_strategy") is not None

    # 3. Switching to already active adapter is a no-op
    adapter2.init_called = False
    same_active = await server.router.switch_adapter("game_2", server)
    assert same_active is adapter2
    assert adapter2.init_called is False  # Not re-initialized


@pytest.mark.asyncio
async def test_router_switch_to_missing_adapter(default_config: GamingMCPConfig) -> None:
    """Verify switching to an unregistered adapter raises AdapterNotFoundError."""
    server = GamingMCPServer(default_config)
    with pytest.raises(AdapterNotFoundError) as exc_info:
        await server.router.switch_adapter("nonexistent", server)
    assert "nonexistent" in str(exc_info.value)


@pytest.mark.asyncio
async def test_switch_adapter_tool_execution(default_config: GamingMCPConfig) -> None:
    """Verify switch_adapter MCP tool executes properly."""
    server = GamingMCPServer(default_config)
    adapter = MockGameAdapter(default_config, "minecraft")
    server.router.register_adapter(adapter)

    res = await server.tools.execute("switch_adapter", {"adapter_id": "minecraft"})
    assert res["isError"] is False
    assert "Successfully activated adapter 'minecraft'" in res["content"][0]["text"]
    assert server.router.active_adapter_id == "minecraft"

    # Switching to missing adapter via tool returns structured error
    err_res = await server.tools.execute("switch_adapter", {"adapter_id": "unknown"})
    assert err_res["isError"] is True
    assert err_res["error_code"] == -32001


@pytest.mark.asyncio
async def test_router_health_check_and_unregister(default_config: GamingMCPConfig) -> None:
    """Verify router aggregated health check and clean unregister."""
    server = GamingMCPServer(default_config)
    adapter = MockGameAdapter(default_config, "test_game")
    server.router.register_adapter(adapter)

    await server.router.switch_adapter("test_game", server)
    health = await server.router.health_check()
    assert health["active_adapter"] == "test_game"
    assert health["adapters"]["test_game"]["status"] == "healthy"

    # Unregister active adapter
    await server.router.unregister_adapter("test_game", server)
    assert server.router.active_adapter_id is None
    assert server.router.get_adapter("test_game") is None
    assert server.tools.get("test_game_action") is None
