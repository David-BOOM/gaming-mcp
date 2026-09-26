"""Adversarial stress-testing suite for GamingMCPServer lifecycle and hot-swapping.

Tests cover:
1. Repeated and concurrent initialize() idempotence.
2. AdapterNotFoundError (-32001) on unregistered adapter hot-swap attempts.
3. Clean tool, resource, and prompt rebinding during hot-swapping.
4. Server shutdown error resilience, motor release, and idempotent cleanup.
5. Repository-wide zero emojis invariant verification.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.core.exceptions import AdapterNotFoundError
from gaming_mcp.server import GamingMCPServer

if TYPE_CHECKING:
    from gaming_mcp.config import GamingMCPConfig
    from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry


class SecondaryTestAdapter(GameAdapter):
    """Secondary mock game adapter with distinct tools and resources for hot-swap testing."""

    def __init__(self, config: GamingMCPConfig, adapter_id: str = "secondary_game") -> None:
        super().__init__(config)
        self._id = adapter_id
        self.init_count = 0
        self.shutdown_count = 0
        self.action_invoked = False

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            id=self._id,
            display_name=f"Secondary Test Game {self._id}",
            version="1.0.0",
            description="Secondary adapter for empirical hot-swap verification",
            author="Empirical Challenger",
        )

    async def initialize(self) -> None:
        self.init_count += 1
        self.is_initialized = True

    async def shutdown(self) -> None:
        self.shutdown_count += 1
        self.is_initialized = False

    def register_tools(self, registry: ToolRegistry) -> None:
        async def _secondary_scan() -> dict[str, Any]:
            self.action_invoked = True
            return {"status": "scanned", "adapter": self._id}

        async def _secondary_strike(power: int = 10) -> dict[str, Any]:
            return {"status": "strike_executed", "power": power}

        registry.register(
            name=f"{self._id}_scan",
            handler=_secondary_scan,
            description="Scan secondary game state",
        )
        registry.register(
            name=f"{self._id}_strike",
            handler=_secondary_strike,
            description="Execute secondary strike command",
        )

    def register_resources(self, registry: ResourceRegistry) -> None:
        async def _secondary_telemetry() -> dict[str, Any]:
            return {"adapter": self._id, "telemetry_online": True}

        registry.register(
            uri=f"game://{self._id}/telemetry",
            reader=_secondary_telemetry,
            name=f"{self._id} Telemetry",
            description="Live telemetry stream for secondary game",
        )

    def register_prompts(self, registry: PromptRegistry) -> None:
        async def _secondary_plan() -> list[dict[str, Any]]:
            return [{"role": "user", "content": f"Tactical plan for {self._id}"}]

        registry.register(
            name=f"{self._id}_tactics",
            generator=_secondary_plan,
            description="Generate tactics for secondary game",
        )


class FailingShutdownAdapter(GameAdapter):
    """Adapter whose shutdown() raises an exception to stress test error resilience."""

    def __init__(self, config: GamingMCPConfig) -> None:
        super().__init__(config)
        self.init_count = 0

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            id="failing_adapter",
            display_name="Failing Shutdown Adapter",
            version="1.0.0",
            description="Adapter that explodes on shutdown",
            author="Empirical Challenger",
        )

    async def initialize(self) -> None:
        self.init_count += 1
        self.is_initialized = True

    async def shutdown(self) -> None:
        self.is_initialized = False
        raise RuntimeError("Hardware communication severed during adapter shutdown")

    def register_tools(self, registry: ToolRegistry) -> None:
        async def _failing_ping() -> str:
            return "alive"

        registry.register("failing_ping", _failing_ping)

    def register_resources(self, registry: ResourceRegistry) -> None:
        pass

    def register_prompts(self, registry: PromptRegistry) -> None:
        pass


# ---------------------------------------------------------------------------
# 1. Startup Lifecycle and Idempotent Initialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_sequential_initialization() -> None:
    """Verify GamingMCPServer.initialize is strictly idempotent across 10 sequential calls."""
    server = GamingMCPServer()
    assert server.is_initialized is False
    assert server.router.active_adapter_id is None

    # First initialization
    await server.initialize()
    assert server.is_initialized is True
    assert server.router.active_adapter_id == "computer_use"

    initial_tool_names = {t.name for t in server.tools.list_tools()}
    assert "game_control" in initial_tool_names
    assert "screenshot" in initial_tool_names
    assert "mouse_click" in initial_tool_names
    assert "server_health" in initial_tool_names
    assert "ping" in initial_tool_names
    assert "switch_adapter" in initial_tool_names
    initial_count = len(initial_tool_names)

    # 10 sequential re-initializations
    for _ in range(10):
        await server.initialize()
        assert server.is_initialized is True
        assert server.router.active_adapter_id == "computer_use"
        current_tools = {t.name for t in server.tools.list_tools()}
        assert len(current_tools) == initial_count
        assert current_tools == initial_tool_names

    # Ensure tools remain executable and functional
    res = await server.tools.execute("ping")
    assert res["isError"] is False
    assert res["content"][0]["text"] != ""

    await server.shutdown()


@pytest.mark.asyncio
async def test_idempotent_concurrent_initialization() -> None:
    """Verify concurrent initialize calls do not cause race conditions or duplicate bindings."""
    server = GamingMCPServer()

    # Launch 20 concurrent initialization calls
    init_tasks = [server.initialize() for _ in range(20)]
    results = await asyncio.gather(*init_tasks, return_exceptions=True)
    for res in results:
        assert not isinstance(res, Exception), f"Concurrent initialize raised: {res}"

    assert server.is_initialized is True
    assert server.router.active_adapter_id == "computer_use"

    tool_names = [t.name for t in server.tools.list_tools()]
    assert len(tool_names) == len(set(tool_names)), "Duplicate tool registrations detected"
    assert "game_control" in tool_names

    await server.shutdown()


@pytest.mark.asyncio
async def test_initialize_preserves_active_session_when_already_initialized() -> None:
    """Verify initialize on an initialized server does not clobber switched adapter."""
    server = GamingMCPServer()
    secondary = SecondaryTestAdapter(server.config, "secondary_game")
    server.router.register_adapter(secondary)

    await server.initialize()
    assert server.router.active_adapter_id == "computer_use"

    # Switch to secondary
    await server.router.switch_adapter("secondary_game", server)
    assert server.router.active_adapter_id == "secondary_game"

    # Re-invoking initialize should be a no-op and NOT revert to computer_use
    await server.initialize()
    assert server.router.active_adapter_id == "secondary_game"
    assert server.tools.get("secondary_game_scan") is not None

    await server.shutdown()


# ---------------------------------------------------------------------------
# 2. Unregistered Adapter and -32001 Error Handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_to_unregistered_adapter_raises_32001() -> None:
    """Verify switching to an unregistered adapter raises AdapterNotFoundError with code -32001."""
    server = GamingMCPServer()
    await server.initialize()

    with pytest.raises(AdapterNotFoundError) as exc_info:
        await server.router.switch_adapter("nonexistent_game_999", server)

    err = exc_info.value
    assert err.error_code == -32001
    assert "nonexistent_game_999" in err.message
    json_err = err.to_jsonrpc_error()
    assert json_err["code"] == -32001
    assert json_err["data"]["adapter_id"] == "nonexistent_game_999"

    # Server must remain running and previous adapter must remain active and functional
    assert server.router.active_adapter_id == "computer_use"
    assert server.tools.get("game_control") is not None

    await server.shutdown()


@pytest.mark.asyncio
async def test_switch_adapter_tool_returns_32001_error_envelope() -> None:
    """Verify switch_adapter MCP tool returns structured JSON-RPC error envelope with -32001."""
    server = GamingMCPServer()
    await server.initialize()

    res = await server.tools.execute("switch_adapter", {"adapter_id": "ghost_adapter"})
    assert res["isError"] is True
    assert res["error_code"] == -32001
    assert "ghost_adapter" in res["content"][0]["text"]
    assert res["data"]["adapter_id"] == "ghost_adapter"

    # Validate server health is unaffected
    health = server.get_health()
    assert health["active_adapter"] == "computer_use"

    await server.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_id",
    [
        "",
        "   ",
        "../../../../../../etc/passwd",
        "; DROP TABLE adapters; --",
        "null\x00byte",
        "a" * 10000,
        "adapter with\r\nnewlines",
    ],
)
async def test_switch_adapter_adversarial_inputs_do_not_crash(malicious_id: str) -> None:
    """Verify adversarial adapter IDs are safely rejected with -32001 without crashing."""
    server = GamingMCPServer()
    await server.initialize()

    res = await server.tools.execute("switch_adapter", {"adapter_id": malicious_id})
    assert res["isError"] is True
    assert res["error_code"] == -32001

    # Verify server is intact and accepting other commands
    ping_res = await server.tools.execute("ping")
    assert ping_res["isError"] is False

    await server.shutdown()


# ---------------------------------------------------------------------------
# 3. Hot-Swapping and Clean Tool Rebinding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hot_swap_between_computer_use_and_secondary_adapter() -> None:
    """Verify hot-swapping between computer_use and secondary adapter rebinds tools."""
    server = GamingMCPServer()
    secondary = SecondaryTestAdapter(server.config, "secondary_game")
    server.router.register_adapter(secondary)

    # 1. Boot server to default adapter
    await server.initialize()
    assert server.router.active_adapter_id == "computer_use"
    assert server.tools.get("game_control") is not None
    assert server.tools.get("secondary_game_scan") is None
    assert server.resources.get("game://secondary_game/telemetry") is None
    assert server.prompts.get("secondary_game_tactics") is None

    # 2. Hot-swap from computer_use to secondary_game
    switched = await server.router.switch_adapter("secondary_game", server)
    assert switched is secondary
    assert server.router.active_adapter_id == "secondary_game"
    assert secondary.is_initialized is True
    assert secondary.init_count == 1

    # Verify computer_use tools detached and secondary tools attached
    assert server.tools.get("game_control") is None
    assert server.tools.get("screenshot") is None
    assert server.tools.get("secondary_game_scan") is not None
    assert server.tools.get("secondary_game_strike") is not None
    assert server.resources.get("game://secondary_game/telemetry") is not None
    assert server.prompts.get("secondary_game_tactics") is not None

    # Verify calling former tool returns not-found (-32601)
    stale_tool_res = await server.tools.execute("game_control", {"action": "interact"})
    assert stale_tool_res["isError"] is True
    assert stale_tool_res["error_code"] == -32601

    # Verify calling new secondary tool succeeds
    sec_tool_res = await server.tools.execute("secondary_game_scan")
    assert sec_tool_res["isError"] is False
    assert secondary.action_invoked is True

    # 3. Hot-swap back to computer_use
    reverted = await server.router.switch_adapter("computer_use", server)
    assert reverted.metadata.id == "computer_use"
    assert server.router.active_adapter_id == "computer_use"
    assert secondary.is_initialized is False
    assert secondary.shutdown_count == 1

    # Verify secondary tools detached and computer_use tools restored
    assert server.tools.get("secondary_game_scan") is None
    assert server.tools.get("secondary_game_strike") is None
    assert server.resources.get("game://secondary_game/telemetry") is None
    assert server.prompts.get("secondary_game_tactics") is None

    assert server.tools.get("game_control") is not None
    assert server.tools.get("screenshot") is not None
    assert server.tools.get("mouse_click") is not None

    await server.shutdown()


@pytest.mark.asyncio
async def test_hot_swap_mcp_server_rebinding_with_spy() -> None:
    """Verify remove_tool and add_tool hooks are called on mcp_server during hot-swaps."""
    server = GamingMCPServer()
    secondary = SecondaryTestAdapter(server.config, "secondary_game")
    server.router.register_adapter(secondary)

    # Attach spy methods to mcp_server
    added_tools: list[str] = []
    removed_tools: list[str] = []

    def _spy_add(_handler: Any, name: str, description: str = "") -> None:
        added_tools.append(name)

    def _spy_remove(name: str) -> None:
        removed_tools.append(name)

    server.mcp_server.add_tool = MagicMock(side_effect=_spy_add)
    server.mcp_server.remove_tool = MagicMock(side_effect=_spy_remove)

    # Initialize server (activates computer_use)
    await server.initialize()
    assert "game_control" in added_tools

    # Clear tracking lists
    added_tools.clear()
    removed_tools.clear()

    # Switch to secondary adapter
    await server.router.switch_adapter("secondary_game", server)

    # Verify old tools were un-registered and new tools registered
    assert "game_control" in removed_tools
    assert "secondary_game_scan" in added_tools
    assert "secondary_game_strike" in added_tools

    # Clear tracking lists
    added_tools.clear()
    removed_tools.clear()

    # Switch back to computer_use
    await server.router.switch_adapter("computer_use", server)

    assert "secondary_game_scan" in removed_tools
    assert "secondary_game_strike" in removed_tools
    assert "game_control" in added_tools

    await server.shutdown()


@pytest.mark.asyncio
async def test_rapid_alternating_hot_swaps_stress() -> None:
    """Verify rapid repeated adapter transitions do not corrupt state or leave orphaned tools."""
    server = GamingMCPServer()
    secondary = SecondaryTestAdapter(server.config, "secondary_game")
    server.router.register_adapter(secondary)

    await server.initialize()

    # Alternate 20 times between computer_use and secondary_game
    for i in range(20):
        target = "secondary_game" if i % 2 == 0 else "computer_use"
        await server.router.switch_adapter(target, server)
        assert server.router.active_adapter_id == target

        if target == "secondary_game":
            assert server.tools.get("secondary_game_scan") is not None
            assert server.tools.get("game_control") is None
        else:
            assert server.tools.get("game_control") is not None
            assert server.tools.get("secondary_game_scan") is None

    # End state check
    health = server.get_health()
    assert health["active_adapter"] == "computer_use"
    assert health["tools_registered"] >= 5

    await server.shutdown()


# ---------------------------------------------------------------------------
# 4. Server Shutdown Resilience and Motor Safety Release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_releases_inputs_and_unregisters_adapter() -> None:
    """Verify shutdown releases all inputs, resets gamepads, and detaches active adapter cleanly."""
    server = GamingMCPServer()
    await server.initialize()

    motor_reset_triggered = False

    def _on_motor_reset() -> None:
        nonlocal motor_reset_triggered
        motor_reset_triggered = True

    server.cancellation_manager.register_callback(_on_motor_reset)

    active_adapter = server.router.active_adapter
    assert active_adapter is not None
    assert active_adapter.is_initialized is True

    # Spy on input injector and gamepad release
    if hasattr(active_adapter, "input_injector") and active_adapter.input_injector:
        active_adapter.input_injector.release_all = MagicMock(
            wraps=active_adapter.input_injector.release_all
        )
    if hasattr(active_adapter, "gamepad") and active_adapter.gamepad:
        active_adapter.gamepad.reset = MagicMock(wraps=active_adapter.gamepad.reset)

    await server.shutdown()

    assert server.is_running is False
    assert server.is_initialized is False
    assert server.router.active_adapter_id is None
    assert motor_reset_triggered is True

    if hasattr(active_adapter, "input_injector") and active_adapter.input_injector:
        active_adapter.input_injector.release_all.assert_called()
    if hasattr(active_adapter, "gamepad") and active_adapter.gamepad:
        active_adapter.gamepad.reset.assert_called()


@pytest.mark.asyncio
async def test_shutdown_without_transport_started() -> None:
    """Verify shutdown operates cleanly when initialize was called but transport never started."""
    server = GamingMCPServer()
    await server.initialize()
    assert server.is_running is False
    assert server.is_initialized is True

    # Shutdown should still clean up active adapter and reset motors
    await server.shutdown()
    assert server.is_initialized is False
    assert server.router.active_adapter_id is None

    # Calling shutdown again must be an idempotent safe no-op
    await server.shutdown()
    assert server.is_initialized is False


@pytest.mark.asyncio
async def test_shutdown_uninitialized_server_is_noop() -> None:
    """Verify shutdown on a brand new uninitialized server runs safely without error."""
    server = GamingMCPServer()
    assert server.is_running is False
    assert server.is_initialized is False

    await server.shutdown()
    assert server.is_running is False
    assert server.is_initialized is False

    # Second call
    await server.shutdown()


@pytest.mark.asyncio
async def test_repeated_and_concurrent_shutdown() -> None:
    """Verify repeated and concurrent shutdown calls do not crash or raise exceptions."""
    server = GamingMCPServer()
    await server.initialize()

    # 5 sequential shutdowns
    for _ in range(5):
        await server.shutdown()
        assert server.is_running is False
        assert server.is_initialized is False

    # New server with concurrent shutdowns
    server2 = GamingMCPServer()
    await server2.initialize()

    shutdown_tasks = [server2.shutdown() for _ in range(10)]
    results = await asyncio.gather(*shutdown_tasks, return_exceptions=True)
    for res in results:
        assert not isinstance(res, Exception), f"Concurrent shutdown raised: {res}"

    assert server2.is_running is False
    assert server2.is_initialized is False


@pytest.mark.asyncio
async def test_shutdown_resilience_when_adapter_shutdown_explodes() -> None:
    """Verify server shutdown executes motor safety reset even if active adapter shutdown fails."""
    server = GamingMCPServer()
    failing_adapter = FailingShutdownAdapter(server.config)
    server.router.register_adapter(failing_adapter)

    await server.initialize()
    await server.router.switch_adapter("failing_adapter", server)
    assert server.router.active_adapter_id == "failing_adapter"

    motor_reset_executed = False

    def _motor_reset() -> None:
        nonlocal motor_reset_executed
        motor_reset_executed = True

    server.cancellation_manager.register_callback(_motor_reset)

    # Server shutdown must NOT propagate the RuntimeError from failing_adapter
    await server.shutdown()

    # State must be fully clean and motor reset MUST have executed
    assert server.is_running is False
    assert server.is_initialized is False
    assert motor_reset_executed is True


# ---------------------------------------------------------------------------
# 5. Invariant: Absolute Zero Emojis Repository-Wide
# ---------------------------------------------------------------------------


def test_zero_emojis_in_repository() -> None:
    """Empirically scan source, tests, and challenger files for emoji Unicode characters."""
    forbidden_ranges = [
        (0x1F000, 0x1FFFF),  # Supplemental symbols, pictographs, emoticons
        (0x2600, 0x27BF),    # Miscellaneous symbols, Dingbats
        (0x2B50, 0x2B55),    # Stars and other symbols
    ]

    infractions: list[str] = []

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    target_dirs = [
        os.path.join(root_dir, "src"),
        os.path.join(root_dir, "tests"),
        os.path.join(root_dir, ".agents", "teamwork", "teamwork_preview_challenger_m2_m3_2"),
    ]

    for target_dir in target_dirs:
        if not os.path.exists(target_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(target_dir):
            dirnames[:] = [
                d for d in dirnames if d not in (".git", ".venv", "__pycache__", ".pytest_cache")
            ]

            for filename in filenames:
                if not filename.endswith((".py", ".md", ".json", ".toml")):
                    continue

                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, encoding="utf-8", errors="ignore") as f:
                        for line_no, line in enumerate(f, start=1):
                            for char in line:
                                cp = ord(char)
                                for start, end in forbidden_ranges:
                                    if start <= cp <= end:
                                        rel_path = os.path.relpath(filepath, root_dir)
                                        infractions.append(
                                            f"{rel_path}:{line_no} U+{cp:04X} ({char})"
                                        )
                except Exception as read_err:
                    infractions.append(f"Failed to read {filepath}: {read_err}")

    assert not infractions, (
        f"Found {len(infractions)} emoji infractions:\n"
        + "\n".join(infractions[:10])
    )

