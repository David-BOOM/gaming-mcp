"""Automated tests for MinecraftAdapter and MinecraftBridge IPC supervisor."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from gaming_mcp.adapters.minecraft import (
    MinecraftAdapter,
    MinecraftBridge,
)
from gaming_mcp.config import GamingMCPConfig, MinecraftConfig
from gaming_mcp.core.exceptions import AdapterError
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry


@pytest.fixture
def mock_mc_config() -> MinecraftConfig:
    """Fixture providing MinecraftConfig configured in mock simulation mode."""
    return MinecraftConfig(
        host="localhost",
        port=25565,
        username="TestBot",
        mock_mode=True,
        auto_reconnect=False,
        heartbeat_interval_sec=1.0,
    )


@pytest.mark.asyncio
async def test_minecraft_adapter_metadata() -> None:
    """Verify MinecraftAdapter metadata properties."""
    adapter = MinecraftAdapter()
    meta = adapter.metadata
    assert meta.id == "minecraft"
    assert meta.display_name == "Minecraft High-Fidelity Bridge"
    assert meta.version == "0.1.0"
    assert meta.requires_display is False
    assert "win32" in meta.supported_platforms


@pytest.mark.asyncio
async def test_bridge_handshake_and_ping(mock_mc_config: MinecraftConfig) -> None:
    """Verify that MinecraftBridge launches daemon and completes handshake and ping."""
    bridge = MinecraftBridge(config=mock_mc_config)
    try:
        started = await bridge.start()
        assert started is True
        assert bridge.is_running is True
        assert bridge.is_connected is True
        assert bridge.is_simulated is True

        # Ping command
        ping_res = await bridge.send_command("ping")
        assert ping_res.get("pong") is True
        assert "timestamp" in ping_res

        # Status command
        status_res = await bridge.send_command("status")
        assert status_res.get("connected") is True
        assert status_res.get("mode") == "simulated"
        assert status_res.get("username") == "TestBot"
        assert status_res.get("health") == 20
    finally:
        await bridge.stop()
        assert bridge.is_running is False


@pytest.mark.asyncio
async def test_bridge_event_notifications(mock_mc_config: MinecraftConfig) -> None:
    """Verify that unsolicited daemon bot_event notifications trigger registered listeners."""
    bridge = MinecraftBridge(config=mock_mc_config)
    events_received: list[dict[str, Any]] = []

    def _on_event(payload: dict[str, Any]) -> None:
        events_received.append(payload)

    bridge.add_event_listener("health", _on_event)

    try:
        await bridge.start()
        # Initial connect emits spawn and health events in simulated mode
        await asyncio.sleep(0.15)

        assert any(e.get("event") == "health" for e in events_received)
        assert bridge.last_health == 20
        assert bridge.last_food == 20
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_minecraft_tools_execution(mock_mc_config: MinecraftConfig) -> None:
    """Verify execution of all Minecraft action tools via MinecraftAdapter."""
    mcp_config = GamingMCPConfig()
    mcp_config.adapters.minecraft = mock_mc_config

    adapter = MinecraftAdapter(config=mcp_config)
    tool_registry = ToolRegistry()
    resource_registry = ResourceRegistry()
    prompt_registry = PromptRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)
    adapter.register_resources(resource_registry)
    adapter.register_prompts(prompt_registry)

    try:
        # 1. mc_navigate_to
        res_nav = await tool_registry.execute(
            "mc_navigate_to",
            {"x": 100, "y": 65, "z": -200, "timeout_seconds": 10},
        )
        assert res_nav.get("isError") is False
        assert "Navigated to" in res_nav["content"][0]["text"]

        # 2. mc_mine_block
        res_mine = await tool_registry.execute(
            "mc_mine_block",
            {"x": 100, "y": 64, "z": -200, "block_name": "iron_ore"},
        )
        assert res_mine.get("isError") is False
        assert "Mined block" in res_mine["content"][0]["text"]

        # 3. mc_craft_item
        res_craft = await tool_registry.execute(
            "mc_craft_item",
            {"item_name": "wooden_pickaxe", "quantity": 1},
        )
        assert res_craft.get("isError") is False
        assert "Crafted 1x wooden_pickaxe" in res_craft["content"][0]["text"]

        # 4. mc_equip_gear
        res_equip = await tool_registry.execute(
            "mc_equip_gear",
            {"slot": "hand", "item_name": "iron_pickaxe"},
        )
        assert res_equip.get("isError") is False
        assert "Equipped iron_pickaxe in hand" in res_equip["content"][0]["text"]

        # 5. mc_attack_target
        res_atk = await tool_registry.execute(
            "mc_attack_target",
            {"entity_type": "zombie", "max_distance": 16.0},
        )
        assert res_atk.get("isError") is False
        assert "Attack result" in res_atk["content"][0]["text"]

        # 6. mc_inspect_surroundings
        res_inspect = await tool_registry.execute(
            "mc_inspect_surroundings",
            {"radius": 16},
        )
        assert res_inspect.get("isError") is False
        assert "plains" in res_inspect["content"][0]["text"]

        # 7. mc_chat
        res_chat = await tool_registry.execute(
            "mc_chat",
            {"message": "Hello world from Gaming MCP"},
        )
        assert res_chat.get("isError") is False
        assert "Sent chat message" in res_chat["content"][0]["text"]

        # Health check
        health = await adapter.health_check()
        assert health["status"] == "healthy"
        assert health["bot_connected"] is True
        assert health["mode"] == "simulated"
    finally:
        await adapter.shutdown()
        assert adapter.is_initialized is False


@pytest.mark.asyncio
async def test_minecraft_resources_and_prompts(mock_mc_config: MinecraftConfig) -> None:
    """Verify Minecraft resources and prompt templates."""
    mcp_config = GamingMCPConfig()
    mcp_config.adapters.minecraft = mock_mc_config

    adapter = MinecraftAdapter(config=mcp_config)
    resource_registry = ResourceRegistry()
    prompt_registry = PromptRegistry()

    await adapter.initialize()
    adapter.register_resources(resource_registry)
    adapter.register_prompts(prompt_registry)

    try:
        # Resource: inventory
        res_inv = await resource_registry.read("minecraft://player/inventory")
        assert "contents" in res_inv
        inv_data = json.loads(res_inv["contents"][0]["text"])
        assert "inventory" in inv_data
        assert len(inv_data["inventory"]) > 0

        # Resource: stats
        res_stats = await resource_registry.read("minecraft://player/stats")
        stats_data = json.loads(res_stats["contents"][0]["text"])
        assert stats_data.get("health") == 20
        assert stats_data.get("food") == 20

        # Resource: world info
        res_world = await resource_registry.read("minecraft://world/biome_and_time")
        world_data = json.loads(res_world["contents"][0]["text"])
        assert world_data.get("biome") == "plains"

        # Prompt: strategy
        prompt_res = await prompt_registry.render(
            "minecraft_strategy",
            {"objective": "find diamond ore"},
        )
        assert len(prompt_res) == 1
        assert "find diamond ore" in prompt_res[0]["content"]["text"]
    finally:
        await adapter.shutdown()


@pytest.mark.asyncio
async def test_bridge_resilience_malformed_ndjson(mock_mc_config: MinecraftConfig) -> None:
    """Verify that non-JSON strings on stdout are ignored without crashing the bridge."""
    bridge = MinecraftBridge(config=mock_mc_config)
    await bridge.start()
    try:
        # Send invalid command
        res = await bridge.send_command("ping")
        assert res.get("pong") is True

        # Unknown method returns JSON-RPC error
        with pytest.raises(AdapterError) as exc_info:
            await bridge.send_command("non_existent_method_xyz")
        assert "Method not found" in str(exc_info.value)
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_restart_and_reconnect(mock_mc_config: MinecraftConfig) -> None:
    """Verify that bridge restart re-spawns process and re-establishes connectivity."""
    bridge = MinecraftBridge(config=mock_mc_config)
    await bridge.start()
    try:
        assert bridge.is_running is True
        old_pid = bridge._process.pid if bridge._process else None

        ok = await bridge.restart()
        assert ok is True
        assert bridge.is_running is True
        new_pid = bridge._process.pid if bridge._process else None
        assert new_pid is not None
        assert new_pid != old_pid
    finally:
        await bridge.stop()
