"""Automated test suite for RetroAdapter, SimulatedRetroCore, and Libretro integration."""

from __future__ import annotations

import base64
import io
import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from gaming_mcp.adapters.retro import (
    NativeRetroBackend,
    RetroAdapter,
    SimulatedRetroCore,
)
from gaming_mcp.config import GamingMCPConfig, RetroConfig
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry
from gaming_mcp.server import GamingMCPServer


@pytest.fixture
def retro_config() -> GamingMCPConfig:
    """Fixture providing a GamingMCPConfig with retro configuration."""
    cfg = GamingMCPConfig()
    cfg.adapters.retro = RetroConfig(
        game="SuperMarioBros-Nes",
        core="fceumm",
        mock_mode=True,
    )
    return cfg


# -----------------------------------------------------------------------------
# Metadata and Attributes
# -----------------------------------------------------------------------------


def test_retro_adapter_metadata() -> None:
    """Verify RetroAdapter metadata conforms to SPI specification."""
    adapter = RetroAdapter()
    meta = adapter.metadata
    assert meta.id == "retro"
    assert meta.display_name == "Retro & Emulation Adapter"
    assert meta.version == "0.1.0"
    assert meta.requires_display is False
    assert meta.requires_admin_privileges is False
    assert "win32" in meta.supported_platforms
    assert "linux" in meta.supported_platforms
    assert "darwin" in meta.supported_platforms


# -----------------------------------------------------------------------------
# Lifecycle and Capability Probing
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retro_adapter_lifecycle_simulation(retro_config: GamingMCPConfig) -> None:
    """Verify initialization, health checks, and shutdown in simulation mode."""
    adapter = RetroAdapter(config=retro_config)
    assert adapter.is_initialized is False

    # Health check before initialization
    initial_health = await adapter.health_check()
    assert initial_health["status"] == "uninitialized"
    assert initial_health["adapter_id"] == "retro"

    await adapter.initialize()
    assert adapter.is_initialized is True
    assert adapter.backend is not None
    assert adapter.backend.is_simulated is True
    assert adapter.backend.backend_name == "simulation"

    # Health check after initialization
    active_health = await adapter.health_check()
    assert active_health["status"] == "healthy"
    assert active_health["backend"] == "simulation"
    assert active_health["is_simulated"] is True
    assert active_health["game"] == "SuperMarioBros-Nes"
    assert active_health["frame_count"] == 0

    await adapter.shutdown()
    assert adapter.is_initialized is False
    assert adapter.backend is None


@pytest.mark.asyncio
async def test_retro_capability_probing_fallback() -> None:
    """Verify capability probing falls back cleanly to simulation when packages missing."""
    cfg = GamingMCPConfig()
    cfg.adapters.retro.mock_mode = False

    with patch("gaming_mcp.adapters.retro.probe_retro_backend", return_value=(None, None)):
        adapter = RetroAdapter(config=cfg)
        await adapter.initialize()
        try:
            assert adapter.is_initialized is True
            assert adapter.backend is not None
            assert adapter.backend.is_simulated is True
            assert isinstance(adapter.backend, SimulatedRetroCore)
        finally:
            await adapter.shutdown()


@pytest.mark.asyncio
async def test_retro_capability_probing_native_failure_fallback() -> None:
    """Verify capability probing falls back to simulation if native init raises error."""
    cfg = GamingMCPConfig()
    cfg.adapters.retro.mock_mode = False

    mock_retro_mod = MagicMock()
    mock_retro_mod.make.side_effect = RuntimeError("ROM not found: SuperMarioBros-Nes")

    with patch(
        "gaming_mcp.adapters.retro.probe_retro_backend",
        return_value=("stable_retro", mock_retro_mod),
    ):
        adapter = RetroAdapter(config=cfg)
        await adapter.initialize()
        try:
            assert adapter.is_initialized is True
            assert adapter.backend is not None
            assert adapter.backend.is_simulated is True
        finally:
            await adapter.shutdown()


# -----------------------------------------------------------------------------
# Tool Execution: retro_send_pad
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_retro_send_pad_movement(retro_config: GamingMCPConfig) -> None:
    """Verify gamepad actuation moves the character and advances simulation frames."""
    adapter = RetroAdapter(config=retro_config)
    tool_registry = ToolRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)

    try:
        # Move right for 10 frames
        result = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["RIGHT"], "frames": 10},
        )
        assert result.get("isError") is False
        assert "Pad actuated with ['RIGHT']" in result["content"][0]["text"]
        assert result["state"]["x_pos"] > 40
        assert result["total_frames"] == 10
        assert result["state"]["frame_count"] == 10
        assert result["frames_stepped"] == 10

        # Move left for 5 frames
        result_left = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["LEFT"], "frames": 5},
        )
        assert result_left.get("isError") is False
        assert result_left["total_frames"] == 15
        assert result_left["state"]["frame_count"] == 15
    finally:
        await adapter.shutdown()


@pytest.mark.asyncio
async def test_tool_retro_send_pad_sprint_and_jump(retro_config: GamingMCPConfig) -> None:
    """Verify sprint multiplier and jump kinematics in simulated core."""
    adapter = RetroAdapter(config=retro_config)
    tool_registry = ToolRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)

    try:
        # Test sprint with B button
        res_walk = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["RIGHT"], "frames": 1},
        )
        pos_after_walk = res_walk["state"]["x_pos"]

        res_sprint = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["RIGHT", "B"], "frames": 1},
        )
        pos_after_sprint = res_sprint["state"]["x_pos"]
        # Sprint step should be larger than walk step
        assert (pos_after_sprint - pos_after_walk) > (pos_after_walk - 40)

        # Test jump with A button
        res_jump = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["A"], "frames": 5},
        )
        assert res_jump["state"]["y_pos"] < 176  # Elevated off the ground

        # Wait for jump to land
        res_land = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": [], "frames": 25},
        )
        assert res_land["state"]["y_pos"] == 176  # Returned to ground level
    finally:
        await adapter.shutdown()


@pytest.mark.asyncio
async def test_tool_retro_send_pad_case_insensitive_and_pause(
    retro_config: GamingMCPConfig,
) -> None:
    """Verify button inputs are case-insensitive and START toggles pause."""
    adapter = RetroAdapter(config=retro_config)
    tool_registry = ToolRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)

    try:
        # Lowercase button strings
        res = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["right", "a"], "frames": 2},
        )
        assert res.get("isError") is False

        # Toggle pause
        res_pause = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["start"], "frames": 1},
        )
        assert res_pause.get("isError") is False
        assert res_pause["state"]["status"] == "paused"

        # Toggle unpause
        res_unpause = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["START"], "frames": 1},
        )
        assert res_unpause.get("isError") is False
        assert res_unpause["state"]["status"] == "running"
    finally:
        await adapter.shutdown()


# -----------------------------------------------------------------------------
# Tool Execution: retro_save_state & retro_load_state
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_retro_save_and_load_state(retro_config: GamingMCPConfig) -> None:
    """Verify state snapshot serialization and branching recovery."""
    adapter = RetroAdapter(config=retro_config)
    tool_registry = ToolRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)

    try:
        # 1. Advance to position 1
        await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["RIGHT"], "frames": 10},
        )
        vars_slot1 = adapter.backend.get_variables().copy()  # type: ignore[union-attr]
        pos_slot1 = vars_slot1["x_pos"]

        # 2. Save snapshot to checkpoint_1
        save_res1 = await tool_registry.execute(
            "retro_save_state",
            {"slot_name": "checkpoint_1"},
        )
        assert save_res1.get("isError") is False
        assert "Successfully serialized state" in save_res1["content"][0]["text"]
        assert save_res1["slot_name"] == "checkpoint_1"
        assert save_res1["size_bytes"] > 0

        # 3. Advance to position 2
        await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["RIGHT"], "frames": 20},
        )
        vars_slot2 = adapter.backend.get_variables().copy()  # type: ignore[union-attr]
        assert vars_slot2["x_pos"] > pos_slot1

        # 4. Save snapshot to checkpoint_2
        save_res2 = await tool_registry.execute(
            "retro_save_state",
            {"slot_name": "checkpoint_2"},
        )
        assert save_res2.get("isError") is False

        # 5. Restore checkpoint_1
        load_res1 = await tool_registry.execute(
            "retro_load_state",
            {"slot_name": "checkpoint_1"},
        )
        assert load_res1.get("isError") is False
        assert "Successfully restored state" in load_res1["content"][0]["text"]

        current_vars = adapter.backend.get_variables()  # type: ignore[union-attr]
        assert current_vars["x_pos"] == pos_slot1
        assert current_vars["score"] == vars_slot1["score"]

        # 6. Restore checkpoint_2
        load_res2 = await tool_registry.execute(
            "retro_load_state",
            {"slot_name": "checkpoint_2"},
        )
        assert load_res2.get("isError") is False
        current_vars2 = adapter.backend.get_variables()  # type: ignore[union-attr]
        assert current_vars2["x_pos"] == vars_slot2["x_pos"]
    finally:
        await adapter.shutdown()


# -----------------------------------------------------------------------------
# Tool Execution: retro_read_ram
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_retro_read_ram(retro_config: GamingMCPConfig) -> None:
    """Verify memory reading of NES Super Mario Bros registers."""
    adapter = RetroAdapter(config=retro_config)
    tool_registry = ToolRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)

    try:
        # Read lives remaining at 0x075A
        res_lives = await tool_registry.execute(
            "retro_read_ram",
            {"address": SimulatedRetroCore.RAM_ADDR_LIVES, "length": 1},
        )
        assert res_lives.get("isError") is False
        assert res_lives["bytes"] == [3]
        assert res_lives["hex"] == "03"

        # Advance character to test player X register at 0x0086
        await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["RIGHT"], "frames": 5},
        )
        vars_dict = adapter.backend.get_variables()  # type: ignore[union-attr]
        expected_x = vars_dict["x_pos"] & 0xFF

        res_x = await tool_registry.execute(
            "retro_read_ram",
            {"address": SimulatedRetroCore.RAM_ADDR_PLAYER_X_SCREEN, "length": 1},
        )
        assert res_x.get("isError") is False
        assert res_x["bytes"] == [expected_x]

        # Read multiple bytes from zero-page memory
        res_block = await tool_registry.execute(
            "retro_read_ram",
            {"address": 0x0000, "length": 8},
        )
        assert res_block.get("isError") is False
        assert len(res_block["bytes"]) == 8
        assert "Read 8 byte(s) from 0x0000" in res_block["content"][0]["text"]
    finally:
        await adapter.shutdown()


# -----------------------------------------------------------------------------
# Resources: retro://screen & retro://ram/variables
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_screen(retro_config: GamingMCPConfig) -> None:
    """Verify retro://screen produces a valid base64 PNG frame matching 256x240."""
    adapter = RetroAdapter(config=retro_config)
    resource_registry = ResourceRegistry()

    await adapter.initialize()
    adapter.register_resources(resource_registry)

    try:
        read_res = await resource_registry.read("retro://screen")
        assert "contents" in read_res
        item = read_res["contents"][0]
        assert item["uri"] == "retro://screen"
        assert item["mimeType"] == "image/png"
        assert "blob" in item

        # Verify decoded base64 is a valid PNG with 256x240 resolution
        img_bytes = base64.b64decode(item["blob"])
        pil_img = Image.open(io.BytesIO(img_bytes))
        assert pil_img.size == (256, 240)
        assert pil_img.format == "PNG"
    finally:
        await adapter.shutdown()


@pytest.mark.asyncio
async def test_resource_ram_variables(retro_config: GamingMCPConfig) -> None:
    """Verify retro://ram/variables returns formatted dictionary of memory variables."""
    adapter = RetroAdapter(config=retro_config)
    resource_registry = ResourceRegistry()

    await adapter.initialize()
    adapter.register_resources(resource_registry)

    try:
        read_res = await resource_registry.read("retro://ram/variables")
        assert "contents" in read_res
        item = read_res["contents"][0]
        assert item["uri"] == "retro://ram/variables"
        assert item["mimeType"] == "application/json"

        data = json.loads(item["text"])
        assert data["game"] == "SuperMarioBros-Nes"
        assert data["score"] == 0
        assert data["lives"] == 3
        assert data["x_pos"] == 40
        assert data["y_pos"] == 176
        assert data["timer"] == 400
        assert data["coins"] == 0
        assert data["world"] == "1-1"
        assert data["status"] == "running"
    finally:
        await adapter.shutdown()


# -----------------------------------------------------------------------------
# Prompt: retro_speedrun_strategy
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_speedrun_strategy(retro_config: GamingMCPConfig) -> None:
    """Verify retro_speedrun_strategy prompt rendering with default and custom arguments."""
    adapter = RetroAdapter(config=retro_config)
    prompt_registry = PromptRegistry()

    await adapter.initialize()
    adapter.register_prompts(prompt_registry)

    try:
        # Default arguments
        rendered_default = await prompt_registry.render("retro_speedrun_strategy")
        assert len(rendered_default) == 1
        msg = rendered_default[0]
        assert msg["role"] == "user"
        assert "Super Mario Bros" in msg["content"]["text"]
        assert "retro_send_pad" in msg["content"]["text"]
        assert "retro_save_state" in msg["content"]["text"]
        assert "retro_load_state" in msg["content"]["text"]

        # Custom arguments
        rendered_custom = await prompt_registry.render(
            "retro_speedrun_strategy",
            {"game_title": "Mega Man 2", "objective": "Defeat Metal Man without taking damage"},
        )
        assert len(rendered_custom) == 1
        custom_msg = rendered_custom[0]
        assert "Mega Man 2" in custom_msg["content"]["text"]
        assert "Defeat Metal Man" in custom_msg["content"]["text"]
    finally:
        await adapter.shutdown()


# -----------------------------------------------------------------------------
# Error Handling
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_handling_uninitialized() -> None:
    """Verify tool execution fails gracefully when adapter is uninitialized."""
    adapter = RetroAdapter()
    tool_registry = ToolRegistry()
    adapter.register_tools(tool_registry)

    res = await tool_registry.execute(
        "retro_send_pad",
        {"buttons": ["RIGHT"], "frames": 1},
    )
    assert res.get("isError") is True
    assert "RetroAdapter is not initialized" in res["content"][0]["text"]


@pytest.mark.asyncio
async def test_error_handling_invalid_button(retro_config: GamingMCPConfig) -> None:
    """Verify tool execution fails when unknown button name is provided."""
    adapter = RetroAdapter(config=retro_config)
    tool_registry = ToolRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)

    try:
        res = await tool_registry.execute(
            "retro_send_pad",
            {"buttons": ["INVALID_BUTTON_XYZ"], "frames": 1},
        )
        assert res.get("isError") is True
        assert "Invalid gamepad buttons" in res["content"][0]["text"]
    finally:
        await adapter.shutdown()


@pytest.mark.asyncio
async def test_error_handling_load_nonexistent_slot(retro_config: GamingMCPConfig) -> None:
    """Verify loading from non-existent slot returns an informative error."""
    adapter = RetroAdapter(config=retro_config)
    tool_registry = ToolRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)

    try:
        res = await tool_registry.execute(
            "retro_load_state",
            {"slot_name": "slot_does_not_exist"},
        )
        assert res.get("isError") is True
        assert "Saved state slot 'slot_does_not_exist' not found" in res["content"][0]["text"]
    finally:
        await adapter.shutdown()


@pytest.mark.asyncio
async def test_error_handling_read_ram_bounds(retro_config: GamingMCPConfig) -> None:
    """Verify RAM reading bounds validation."""
    adapter = RetroAdapter(config=retro_config)
    tool_registry = ToolRegistry()

    await adapter.initialize()
    adapter.register_tools(tool_registry)

    try:
        # Out of bounds high address
        res_high = await tool_registry.execute(
            "retro_read_ram",
            {"address": 65530, "length": 10},
        )
        assert res_high.get("isError") is True
        assert "exceeds capacity" in res_high["content"][0]["text"]
    finally:
        await adapter.shutdown()


# -----------------------------------------------------------------------------
# Router and Server Integration
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retro_adapter_router_and_server_integration(
    retro_config: GamingMCPConfig,
) -> None:
    """Verify hot-swapping to RetroAdapter via AdapterRouter on GamingMCPServer."""
    server = GamingMCPServer(retro_config)
    retro_adapter = RetroAdapter(config=retro_config)

    server.router.register_adapter(retro_adapter)
    assert server.router.get_adapter("retro") is retro_adapter

    # Hot-swap to retro adapter
    activated = await server.router.switch_adapter("retro", server)
    assert activated is retro_adapter
    assert server.router.active_adapter_id == "retro"
    assert retro_adapter.is_initialized is True

    # Verify tools registered on server
    tools = {t.name for t in server.tools.list_tools()}
    assert "retro_send_pad" in tools
    assert "retro_save_state" in tools
    assert "retro_load_state" in tools
    assert "retro_read_ram" in tools

    # Verify resources registered on server
    resources = {r.uri for r in server.resources.list_resources()}
    assert "retro://screen" in resources
    assert "retro://ram/variables" in resources

    # Execute tool through server registry
    res = await server.tools.execute(
        "retro_send_pad",
        {"buttons": ["RIGHT"], "frames": 4},
    )
    assert res.get("isError") is False

    # Switch back to computer_use or unregister
    await server.router.unregister_adapter("retro", server)
    assert retro_adapter.is_initialized is False
    tools_after = {t.name for t in server.tools.list_tools()}
    assert "retro_send_pad" not in tools_after


# -----------------------------------------------------------------------------
# Native Retro Backend Mock
# -----------------------------------------------------------------------------


def test_native_retro_backend_mock() -> None:
    """Verify NativeRetroBackend behavior with mocked stable-retro environment."""
    mock_env = MagicMock()
    mock_env.buttons = ["B", "SELECT", "START", "UP", "DOWN", "LEFT", "RIGHT", "A"]
    mock_env.reset.return_value = (np.zeros((240, 256, 3), dtype=np.uint8), {})
    mock_env.step.return_value = (
        np.zeros((240, 256, 3), dtype=np.uint8),
        1.0,
        False,
        False,
        {"score": 50, "lives": 3},
    )
    mock_env.get_ram.return_value = bytes([0x01, 0x02, 0x03, 0x04])
    mock_env.em.get_state.return_value = b"sample_state_bytes"

    mock_mod = MagicMock()
    mock_mod.make.return_value = mock_env

    backend = NativeRetroBackend(
        retro_module=mock_mod,
        game="SuperMarioBros-Nes",
        core="fceumm",
    )

    assert backend.is_simulated is False
    assert backend.game_title == "SuperMarioBros-Nes"
    assert backend.ram_size == 4

    # Step
    frame, info = backend.step(["RIGHT", "A"], frames=2)
    assert frame.shape == (240, 256, 3)
    assert info["score"] == 50
    assert backend.frame_count == 2

    # Save and Load state
    state_bytes = backend.save_state("slot_1")
    assert state_bytes == b"sample_state_bytes"
    assert "slot_1" in backend.saved_states

    backend.load_state("slot_1")
    mock_env.em.set_state.assert_called_with(b"sample_state_bytes")

    # Read RAM
    ram_data = backend.read_ram(0, 2)
    assert ram_data == b"\x01\x02"

    # Close
    backend.close()
    mock_env.close.assert_called_once()
