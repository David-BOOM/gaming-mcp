"""Minecraft High-Fidelity Bridge Adapter for Gaming MCP Server.

Leverages a headless Node.js child process executing Mineflayer, Mineflayer-Pathfinder,
and Prismarine libraries over a bidirectional NDJSON standard I/O stream.

Provides programmatic, voxel-level spatial navigation, block mining, recipe crafting,
combat actuation, and reactive resources for player inventory and world state.
Includes automatic process supervision, heartbeat monitoring, and auto-reconnect loops.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.config import GamingMCPConfig, MinecraftConfig
from gaming_mcp.core.exceptions import AdapterError, AdapterInitializationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry

logger = logging.getLogger("gaming_mcp.adapters.minecraft")


# -----------------------------------------------------------------------------
# Tool Input Schemas
# -----------------------------------------------------------------------------


class NavigateToInput(BaseModel):
    """Input parameters for mc_navigate_to tool."""

    x: int = Field(description="Target world X coordinate")
    y: int = Field(description="Target world Y coordinate (elevation)")
    z: int = Field(description="Target world Z coordinate")
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Maximum seconds to allow pathfinding before aborting",
    )


class MineBlockInput(BaseModel):
    """Input parameters for mc_mine_block tool."""

    x: int = Field(description="Target block X coordinate")
    y: int = Field(description="Target block Y coordinate")
    z: int = Field(description="Target block Z coordinate")
    block_name: str | None = Field(
        default=None,
        description="Optional expected block identifier (e.g. 'iron_ore', 'oak_log')",
    )


class CraftItemInput(BaseModel):
    """Input parameters for mc_craft_item tool."""

    item_name: str = Field(
        description="Target item identifier to craft (e.g. 'wooden_pickaxe', 'furnace')"
    )
    quantity: int = Field(
        default=1,
        ge=1,
        le=64,
        description="Number of items to craft",
    )


class EquipGearInput(BaseModel):
    """Input parameters for mc_equip_gear tool."""

    slot: Literal["head", "torso", "legs", "feet", "hand", "off-hand"] = Field(
        default="hand",
        description="Armor or inventory slot to equip into",
    )
    item_name: str = Field(
        description="Item identifier to equip (e.g. 'iron_sword', 'shield')"
    )


class AttackTargetInput(BaseModel):
    """Input parameters for mc_attack_target tool."""

    entity_type: str = Field(
        description="Target entity type to attack (e.g. 'zombie', 'skeleton', 'creeper')"
    )
    max_distance: float = Field(
        default=16.0,
        ge=1.0,
        le=64.0,
        description="Maximum search radius to engage the target",
    )


class InspectSurroundingsInput(BaseModel):
    """Input parameters for mc_inspect_surroundings tool."""

    radius: int = Field(
        default=16,
        ge=1,
        le=64,
        description="Radius in blocks around the player to inspect",
    )


class ChatInput(BaseModel):
    """Input parameters for mc_chat tool."""

    message: str = Field(
        min_length=1,
        max_length=256,
        description="Chat message or server command to send",
    )


class ReconnectInput(BaseModel):
    """Input parameters for mc_reconnect tool."""

    force: bool = Field(
        default=False,
        description="Force child process termination and full re-initialization",
    )


# -----------------------------------------------------------------------------
# Mineflayer Process Supervisor & IPC Bridge
# -----------------------------------------------------------------------------


class MinecraftBridge:
    """Supervises the Node.js Mineflayer daemon and manages bidirectional NDJSON IPC."""

    def __init__(
        self,
        config: MinecraftConfig | None = None,
        daemon_path: str | Path | None = None,
    ) -> None:
        self.config = config or MinecraftConfig()
        if daemon_path is not None:
            self.daemon_path = Path(daemon_path)
        elif self.config.daemon_path:
            self.daemon_path = Path(self.config.daemon_path)
        else:
            self.daemon_path = Path(__file__).parent / "minecraft_daemon.js"

        self._process: asyncio.subprocess.Process | None = None
        self._is_running = False
        self._is_connected = False
        self._is_simulated = False
        self._reconnect_attempts = 0

        self._next_request_id = 1
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._event_listeners: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}

        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Cached state
        self.last_position: dict[str, float] | None = None
        self.last_health: float | None = None
        self.last_food: float | None = None
        self.last_stats: dict[str, Any] = {}

    @property
    def is_running(self) -> bool:
        """Return True if the child supervisor process is currently alive."""
        return self._is_running and self._process is not None and self._process.returncode is None

    @property
    def is_connected(self) -> bool:
        """Return True if the bot has confirmed connection to the Minecraft server."""
        return self._is_connected

    @property
    def is_simulated(self) -> bool:
        """Return True if the daemon is running in mock/simulation mode."""
        return self._is_simulated

    def add_event_listener(
        self,
        event_name: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Register a callback for unsolicited bot events emitted by the daemon."""
        if event_name not in self._event_listeners:
            self._event_listeners[event_name] = []
        if handler not in self._event_listeners[event_name]:
            self._event_listeners[event_name].append(handler)

    def remove_event_listener(
        self,
        event_name: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Unregister an event listener callback."""
        if event_name in self._event_listeners:
            self._event_listeners[event_name] = [
                h for h in self._event_listeners[event_name] if h != handler
            ]

    async def start(self) -> bool:
        """Spawn the Node.js daemon and perform initial handshake."""
        if self.is_running:
            return True

        if not self.daemon_path.exists():
            raise AdapterInitializationError(
                "minecraft",
                f"Mineflayer daemon script not found at {self.daemon_path}",
            )

        logger.info(
            "Starting Mineflayer daemon: %s %s",
            self.config.node_binary,
            self.daemon_path,
        )

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.config.node_binary,
                str(self.daemon_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._is_running = True
        except FileNotFoundError as exc:
            raise AdapterInitializationError(
                "minecraft",
                f"Node.js binary '{self.config.node_binary}' not found on system PATH: {exc}",
            ) from exc
        except Exception as exc:
            raise AdapterInitializationError(
                "minecraft",
                f"Failed spawning Mineflayer daemon child process: {exc}",
            ) from exc

        # Spawn asynchronous reader loops
        self._stdout_task = asyncio.create_task(self._stdout_reader_loop())
        self._stderr_task = asyncio.create_task(self._stderr_reader_loop())

        # Perform ping handshake to verify process responsiveness
        try:
            ping_resp = await self.send_command("ping", timeout_seconds=5.0)
            if not ping_resp.get("pong"):
                raise AdapterInitializationError(
                    "minecraft", "Daemon responded to ping without pong flag"
                )
        except Exception as exc:
            await self.stop()
            raise AdapterInitializationError(
                "minecraft", f"Initial daemon ping handshake failed: {exc}"
            ) from exc

        # Check capabilities
        try:
            caps = await self.send_command("get_capabilities", timeout_seconds=5.0)
            logger.info("Mineflayer daemon capabilities: %s", caps)
        except Exception as exc:
            logger.warning("Could not query daemon capabilities: %s", exc)

        # Trigger connection request
        try:
            connect_params = {
                "host": self.config.host,
                "port": self.config.port,
                "username": self.config.username,
                "version": self.config.version,
                "auth": self.config.auth,
                "mock_mode": self.config.mock_mode,
            }
            conn_resp = await self.send_command(
                "connect",
                params=connect_params,
                timeout_seconds=15.0,
            )
            if conn_resp.get("status") in ("connected", "connecting"):
                self._is_connected = True
                self._is_simulated = conn_resp.get("mode") == "simulated"
                self._reconnect_attempts = 0
                logger.info(
                    "Mineflayer bridge established (mode=%s, username=%s)",
                    conn_resp.get("mode"),
                    conn_resp.get("username"),
                )
        except Exception as exc:
            logger.warning("Initial Minecraft server connection error: %s", exc)

        # Start periodic heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return True

    async def stop(self) -> None:
        """Terminate the Node.js daemon and release resources."""
        self._is_running = False
        self._is_connected = False

        # Cancel heartbeat
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        # Send graceful shutdown command
        if self._process and self._process.returncode is None:
            with contextlib.suppress(Exception):
                await self.send_command("shutdown", timeout_seconds=2.0)

        # Close process streams
        if self._process:
            if self._process.stdin and not self._process.stdin.is_closing():
                with contextlib.suppress(Exception):
                    self._process.stdin.close()

            try:
                await asyncio.wait_for(self._process.wait(), timeout=1.5)
            except TimeoutError:
                logger.warning("Mineflayer daemon did not exit within timeout; terminating.")
                try:
                    self._process.terminate()
                    await asyncio.wait_for(self._process.wait(), timeout=1.0)
                except Exception:
                    self._process.kill()

            self._process = None

        # Cancel readers and background tasks
        for task in (self._stdout_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        self._stdout_task = None
        self._stderr_task = None

        for bg_task in list(self._background_tasks):
            if not bg_task.done():
                bg_task.cancel()
        self._background_tasks.clear()

        # Reject any pending futures
        for _req_id, fut in list(self._pending_requests.items()):
            if not fut.done():
                fut.set_exception(AdapterError("Minecraft bridge was shut down"))
        self._pending_requests.clear()
        logger.info("Mineflayer bridge terminated cleanly")

    async def restart(self) -> bool:
        """Restart the daemon process and reconnect."""
        logger.info("Restarting Mineflayer bridge...")
        await self.stop()
        await asyncio.sleep(self.config.reconnect_delay_sec)
        return await self.start()

    async def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: float = 30.0,
    ) -> Any:
        """Send a JSON-RPC 2.0 command over stdin and wait for matching response."""
        if not self._is_running or not self._process or not self._process.stdin:
            raise AdapterError(f"Cannot send '{method}': Mineflayer daemon is not running")

        req_id = self._next_request_id
        self._next_request_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        encoded = json.dumps(payload) + "\n"

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending_requests[req_id] = future

        try:
            self._process.stdin.write(encoded.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as exc:
            self._pending_requests.pop(req_id, None)
            raise AdapterError(f"Failed writing command '{method}' to daemon stdin: {exc}") from exc

        try:
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            self._pending_requests.pop(req_id, None)
            raise AdapterError(
                f"Command '{method}' timed out after {timeout_seconds}s",
                error_code=-32003,
            ) from exc

    async def _stdout_reader_loop(self) -> None:
        """Read NDJSON frames from child process stdout and dispatch responses."""
        if not self._process or not self._process.stdout:
            return

        while self._is_running:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    logger.warning("Mineflayer daemon stdout reached EOF")
                    break

                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                try:
                    data = json.loads(text)
                except Exception as exc:
                    logger.debug("Non-JSON stdout from daemon: %s (err=%s)", text, exc)
                    continue

                # 1. Handle Response
                if "id" in data and data["id"] is not None:
                    req_id = data["id"]
                    fut = self._pending_requests.pop(req_id, None)
                    if fut and not fut.done():
                        if data.get("error"):
                            err_info = data["error"]
                            msg = (
                                err_info.get("message", "Unknown daemon error")
                                if isinstance(err_info, dict)
                                else str(err_info)
                            )
                            code = (
                                err_info.get("code", -32603)
                                if isinstance(err_info, dict)
                                else -32603
                            )
                            fut.set_exception(AdapterError(msg, error_code=code))
                        else:
                            fut.set_result(data.get("result"))

                # 2. Handle Notification / Event
                elif "method" in data:
                    method = data.get("method")
                    params = data.get("params", {})
                    self._handle_daemon_notification(method, params)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in daemon stdout reader loop: %s", exc)
                break

        # Process exited unexpectedly
        if self._is_running:
            self._handle_unexpected_exit()

    def _handle_daemon_notification(self, method: str | None, params: dict[str, Any]) -> None:
        """Process unsolicited notifications (e.g. bot_event)."""
        if method == "bot_event":
            event_type = params.get("event", "unknown")
            event_data = params.get("data", {})

            # Cache key telemetry
            if event_type == "spawn":
                self._is_connected = True
                if event_data.get("position"):
                    self.last_position = event_data["position"]
            elif event_type == "health":
                self.last_health = event_data.get("health")
                self.last_food = event_data.get("food")
            elif event_type in ("kicked", "end"):
                self._is_connected = False

            # Dispatch to listeners
            handlers = (
                self._event_listeners.get(event_type, [])
                + self._event_listeners.get("*", [])
            )
            for handler in handlers:
                try:
                    res = handler(params)
                    if asyncio.iscoroutine(res):
                        task = asyncio.create_task(res)
                        self._background_tasks.add(task)
                        task.add_done_callback(self._background_tasks.discard)
                except Exception as exc:
                    logger.error("Error executing bot event handler: %s", exc)

    async def _stderr_reader_loop(self) -> None:
        """Stream child process diagnostic logs from stderr to python logger."""
        if not self._process or not self._process.stderr:
            return

        while self._is_running:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("%s", text)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat loop verifying child process liveness."""
        while self._is_running:
            try:
                await asyncio.sleep(self.config.heartbeat_interval_sec)
                if not self.is_running:
                    break
                await self.send_command("ping", timeout_seconds=3.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Mineflayer heartbeat ping failed: %s", exc)

    def _handle_unexpected_exit(self) -> None:
        """Trigger reconnection supervisor when daemon exits unexpectedly."""
        self._is_running = False
        self._is_connected = False
        returncode = self._process.returncode if self._process else "unknown"
        logger.critical(
            "Mineflayer daemon terminated unexpectedly (returncode: %s)", returncode
        )

        # Reject pending futures
        for _req_id, fut in list(self._pending_requests.items()):
            if not fut.done():
                fut.set_exception(
                    AdapterError(f"Daemon terminated with exit code {returncode}")
                )
        self._pending_requests.clear()

        can_reconnect = (
            self.config.auto_reconnect
            and self._reconnect_attempts < self.config.max_reconnect_attempts
        )
        if can_reconnect:
            self._reconnect_attempts += 1
            delay = self.config.reconnect_delay_sec * (1.5 ** (self._reconnect_attempts - 1))
            logger.info(
                "Scheduling automatic daemon restart (attempt %d/%d in %.1fs)",
                self._reconnect_attempts,
                self.config.max_reconnect_attempts,
                delay,
            )
            reconnect_task = asyncio.create_task(self._do_auto_restart(delay))
            self._background_tasks.add(reconnect_task)
            reconnect_task.add_done_callback(self._background_tasks.discard)

    async def _do_auto_restart(self, delay: float) -> None:
        """Execute delayed auto-restart."""
        await asyncio.sleep(delay)
        try:
            await self.start()
        except Exception as exc:
            logger.error("Auto-restart failed: %s", exc)


# -----------------------------------------------------------------------------
# MinecraftAdapter Implementation
# -----------------------------------------------------------------------------


class MinecraftAdapter(GameAdapter):
    """High-Fidelity Minecraft Java Edition MCP Adapter using Mineflayer."""

    def __init__(
        self,
        config: GamingMCPConfig | None = None,
        custom_bridge: MinecraftBridge | None = None,
    ) -> None:
        super().__init__(config=config or GamingMCPConfig())
        self._custom_bridge = custom_bridge
        self.bridge: MinecraftBridge | None = None

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            id="minecraft",
            display_name="Minecraft High-Fidelity Bridge",
            version="0.1.0",
            description=(
                "High-fidelity Minecraft Java Edition adapter leveraging headless Node.js "
                "Mineflayer daemon for programmatic voxel navigation, inventory management, "
                "crafting, and spatial introspection."
            ),
            supported_platforms=["win32", "linux", "darwin"],
            requires_display=False,
            requires_admin_privileges=False,
        )

    async def initialize(self) -> None:
        """Initialize the Mineflayer child process supervisor and IPC bridge."""
        if self.is_initialized:
            return

        if self._custom_bridge:
            self.bridge = self._custom_bridge
        else:
            mc_config = (
                self.config.adapters.minecraft
                if self.config and self.config.adapters and self.config.adapters.minecraft
                else MinecraftConfig()
            )
            self.bridge = MinecraftBridge(config=mc_config)

        await self.bridge.start()
        self.is_initialized = True
        logger.info("MinecraftAdapter initialized successfully")

    async def shutdown(self) -> None:
        """Gracefully disconnect bot and terminate child process."""
        if not self.is_initialized:
            return

        if self.bridge:
            await self.bridge.stop()
            self.bridge = None

        self.is_initialized = False
        logger.info("MinecraftAdapter shut down cleanly")

    async def health_check(self) -> dict[str, Any]:
        """Return connectivity and process health status."""
        is_alive = self.bridge.is_running if self.bridge else False
        is_conn = self.bridge.is_connected if self.bridge else False
        is_sim = self.bridge.is_simulated if self.bridge else False

        return {
            "adapter_id": self.metadata.id,
            "status": "healthy" if (self.is_initialized and is_alive) else "degraded",
            "process_running": is_alive,
            "bot_connected": is_conn,
            "mode": "simulated" if is_sim else "live",
            "last_position": self.bridge.last_position if self.bridge else None,
            "last_health": self.bridge.last_health if self.bridge else None,
            "last_food": self.bridge.last_food if self.bridge else None,
        }

    # -------------------------------------------------------------------------
    # Tool Registrations
    # -------------------------------------------------------------------------

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register Minecraft action and introspection tools."""
        registry.register(
            name="mc_navigate_to",
            handler=self._tool_navigate_to,
            description=(
                "Compute and execute 3D voxel pathfinding to target coordinates using A* "
                "heuristic algorithms with block breaking and bridging."
            ),
            input_model=NavigateToInput,
        )

        registry.register(
            name="mc_mine_block",
            handler=self._tool_mine_block,
            description=(
                "Equip the optimal harvest tool and dig the block at the specified voxel "
                "coordinates."
            ),
            input_model=MineBlockInput,
        )

        registry.register(
            name="mc_craft_item",
            handler=self._tool_craft_item,
            description=(
                "Craft an item from known recipes in the game's internal recipe graph, "
                "navigating to a nearby crafting table if required."
            ),
            input_model=CraftItemInput,
        )

        registry.register(
            name="mc_equip_gear",
            handler=self._tool_equip_gear,
            description="Equip a specified armor, weapon, or utility item into a body slot.",
            input_model=EquipGearInput,
        )

        registry.register(
            name="mc_attack_target",
            handler=self._tool_attack_target,
            description=(
                "Locate the nearest hostile or target entity, face it, and execute combat "
                "attacks with attack-cooldown timing."
            ),
            input_model=AttackTargetInput,
        )

        registry.register(
            name="mc_inspect_surroundings",
            handler=self._tool_inspect_surroundings,
            description=(
                "Return a structured JSON spatial report: nearby passive/hostile entities, "
                "light levels, biome, and time of day."
            ),
            input_model=InspectSurroundingsInput,
        )

        registry.register(
            name="mc_chat",
            handler=self._tool_chat,
            description="Send a text message or slash command to the Minecraft server.",
            input_model=ChatInput,
        )

        registry.register(
            name="mc_reconnect",
            handler=self._tool_reconnect,
            description="Force child process daemon restart and reconnect to Minecraft server.",
            input_model=ReconnectInput,
        )

    # -------------------------------------------------------------------------
    # Resource Registrations
    # -------------------------------------------------------------------------

    def register_resources(self, registry: ResourceRegistry) -> None:
        """Register reactive Minecraft game state resources."""
        registry.register(
            uri="minecraft://player/inventory",
            reader=self._resource_inventory,
            name="Player Inventory",
            description="Real-time breakdown of all player slots, off-hand, armor, and item counts",
            mime_type="application/json",
        )

        registry.register(
            uri="minecraft://player/stats",
            reader=self._resource_stats,
            name="Player Stats",
            description="Current health (0-20), food level, oxygen, and experience metrics",
            mime_type="application/json",
        )

        registry.register(
            uri="minecraft://world/biome_and_time",
            reader=self._resource_world_info,
            name="World Environment Info",
            description="Current biome name, celestial tick time (day/night), and weather states",
            mime_type="application/json",
        )

    # -------------------------------------------------------------------------
    # Prompt Registrations
    # -------------------------------------------------------------------------

    def register_prompts(self, registry: PromptRegistry) -> None:
        """Register Minecraft gameplay guidance prompts."""
        registry.register(
            name="minecraft_strategy",
            generator=self._prompt_minecraft_strategy,
            description="Strategic orientation prompt for autonomous Minecraft survival gameplay",
            arguments=[
                {
                    "name": "objective",
                    "description": "Specific gameplay goal (e.g., 'mine diamonds')",
                    "required": False,
                }
            ],
        )

    # -------------------------------------------------------------------------
    # Tool Handlers
    # -------------------------------------------------------------------------

    async def _tool_navigate_to(
        self,
        x: int,
        y: int,
        z: int,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        if not self.bridge:
            raise AdapterError("Minecraft bridge is not initialized")

        res = await self.bridge.send_command(
            "navigate_to",
            params={"x": x, "y": y, "z": z, "timeout_seconds": timeout_seconds},
            timeout_seconds=float(timeout_seconds + 5),
        )
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Navigated to ({x}, {y}, {z}): {json.dumps(res)}",
                }
            ],
        }

    async def _tool_mine_block(
        self,
        x: int,
        y: int,
        z: int,
        block_name: str | None = None,
    ) -> dict[str, Any]:
        if not self.bridge:
            raise AdapterError("Minecraft bridge is not initialized")

        res = await self.bridge.send_command(
            "mine_block",
            params={"x": x, "y": y, "z": z, "block_name": block_name},
            timeout_seconds=20.0,
        )
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Mined block at ({x}, {y}, {z}): {json.dumps(res)}",
                }
            ],
        }

    async def _tool_craft_item(
        self,
        item_name: str,
        quantity: int = 1,
    ) -> dict[str, Any]:
        if not self.bridge:
            raise AdapterError("Minecraft bridge is not initialized")

        res = await self.bridge.send_command(
            "craft_item",
            params={"item_name": item_name, "quantity": quantity},
            timeout_seconds=15.0,
        )
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Crafted {quantity}x {item_name}: {json.dumps(res)}",
                }
            ],
        }

    async def _tool_equip_gear(
        self,
        item_name: str,
        slot: Literal["head", "torso", "legs", "feet", "hand", "off-hand"] = "hand",
    ) -> dict[str, Any]:
        if not self.bridge:
            raise AdapterError("Minecraft bridge is not initialized")

        res = await self.bridge.send_command(
            "equip_gear",
            params={"item_name": item_name, "slot": slot},
            timeout_seconds=10.0,
        )
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Equipped {item_name} in {slot}: {json.dumps(res)}",
                }
            ],
        }

    async def _tool_attack_target(
        self,
        entity_type: str,
        max_distance: float = 16.0,
    ) -> dict[str, Any]:
        if not self.bridge:
            raise AdapterError("Minecraft bridge is not initialized")

        res = await self.bridge.send_command(
            "attack_target",
            params={"entity_type": entity_type, "max_distance": max_distance},
            timeout_seconds=15.0,
        )
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Attack result for {entity_type}: {json.dumps(res)}",
                }
            ],
        }

    async def _tool_inspect_surroundings(
        self,
        radius: int = 16,
    ) -> dict[str, Any]:
        if not self.bridge:
            raise AdapterError("Minecraft bridge is not initialized")

        res = await self.bridge.send_command(
            "inspect_surroundings",
            params={"radius": radius},
            timeout_seconds=10.0,
        )
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(res),
                }
            ],
        }

    async def _tool_chat(
        self,
        message: str,
    ) -> dict[str, Any]:
        if not self.bridge:
            raise AdapterError("Minecraft bridge is not initialized")

        _ = await self.bridge.send_command(
            "chat",
            params={"message": message},
            timeout_seconds=10.0,
        )
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Sent chat message: {message}",
                }
            ],
        }

    async def _tool_reconnect(
        self,
        force: bool = False,
    ) -> dict[str, Any]:
        if not self.bridge:
            raise AdapterError("Minecraft bridge is not initialized")

        ok = await self.bridge.restart()
        return {
            "isError": not ok,
            "content": [
                {
                    "type": "text",
                    "text": f"Minecraft bridge restart result: {'success' if ok else 'failed'}",
                }
            ],
        }

    # -------------------------------------------------------------------------
    # Resource Handlers
    # -------------------------------------------------------------------------

    async def _resource_inventory(self) -> dict[str, Any]:
        if not self.bridge:
            return {"inventory": []}
        res = await self.bridge.send_command("get_inventory", timeout_seconds=5.0)
        return dict(res) if isinstance(res, dict) else {"inventory": []}

    async def _resource_stats(self) -> dict[str, Any]:
        if not self.bridge:
            return {"health": 0, "food": 0}
        res = await self.bridge.send_command("get_stats", timeout_seconds=5.0)
        return dict(res) if isinstance(res, dict) else {"health": 0, "food": 0}

    async def _resource_world_info(self) -> dict[str, Any]:
        if not self.bridge:
            return {"biome": "unknown", "time": 0}
        res = await self.bridge.send_command("get_world_info", timeout_seconds=5.0)
        return dict(res) if isinstance(res, dict) else {"biome": "unknown", "time": 0}

    # -------------------------------------------------------------------------
    # Prompt Handlers
    # -------------------------------------------------------------------------

    async def _prompt_minecraft_strategy(
        self,
        objective: str = "Survive, build a shelter, and acquire iron tools",
    ) -> list[dict[str, Any]]:
        text = (
            "You are an autonomous AI playing Minecraft Java Edition via the high-fidelity "
            f"Mineflayer bridge.\nObjective: {objective}\n\n"
            "Operational Guidelines:\n"
            "1. Inspect your surroundings using `mc_inspect_surroundings(radius=16)`.\n"
            "2. Harvest wood and stone using `mc_mine_block(...)`.\n"
            "3. Craft essential tools via `mc_craft_item(item_name='wooden_pickaxe')`.\n"
            "4. Monitor your vitals using the `minecraft://player/stats` resource.\n"
            "5. Navigate between resource veins using `mc_navigate_to(x, y, z)`.\n"
            "6. In combat, use `mc_attack_target(entity_type='zombie')` with optimal cooldown."
        )
        return [
            {
                "role": "user",
                "content": {"type": "text", "text": text},
            }
        ]
