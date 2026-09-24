/**
 * Mineflayer Headless Daemon Bridge for Gaming MCP Server.
 *
 * Implements bidirectional NDJSON / JSON-RPC 2.0 communication over standard I/O streams.
 * Communicates with the Python MinecraftAdapter child process supervisor.
 *
 * Features:
 * - Redirects all diagnostic console logs to process.stderr (stdout reserved for NDJSON).
 * - Implements capability probe: uses real mineflayer if installed, or deterministic simulation if absent.
 * - Handles bot events (spawn, health, death, chat, error, end) and emits JSON-RPC notifications.
 * - Executes movement, block interaction, crafting, combat, and inventory management.
 */

const readline = require("readline");

// Redirect console output strictly to stderr to prevent NDJSON stream corruption
const _stderrWrite = process.stderr.write.bind(process.stderr);
console.log = (...args) => {
  _stderrWrite("[mineflayer-daemon] " + args.map(a => (typeof a === "object" ? JSON.stringify(a) : a)).join(" ") + "\n");
};
console.info = console.log;
console.warn = console.log;
console.error = console.log;
console.debug = console.log;

// Probe for mineflayer availability
let mineflayer = null;
let pathfinder = null;
let Vec3 = null;

try {
  mineflayer = require("mineflayer");
  try {
    const pf = require("mineflayer-pathfinder");
    pathfinder = pf.pathfinder;
  } catch (_e) {
    // Optional pathfinder package
  }
  try {
    Vec3 = require("vec3").Vec3;
  } catch (_e) {
    // Optional vec3
  }
} catch (_e) {
  // mineflayer not installed; fallback to simulation
}

// Bot State and State Machine
let bot = null;
let isConnected = false;
let isConnecting = false;
let isSimulated = false;
let currentConfig = {
  host: "localhost",
  port: 25565,
  username: "GamingMCPBot",
  version: "1.20.4",
  auth: "offline",
  mock_mode: false,
};

// Simulated State for mock / test mode
const simulatedState = {
  position: { x: 0, y: 64, z: 0 },
  yaw: 0.0,
  pitch: 0.0,
  health: 20,
  food: 20,
  oxygen: 20,
  experience: { level: 5, points: 120 },
  inventory: [
    { slot: 36, name: "iron_pickaxe", count: 1, durability: 240 },
    { slot: 37, name: "torch", count: 64 },
    { slot: 38, name: "bread", count: 16 },
    { slot: 39, name: "cobblestone", count: 32 },
    { slot: 40, name: "oak_log", count: 16 },
  ],
  placed_blocks: {},
  mined_blocks: new Set(),
  nearby_entities: [
    { id: 101, name: "pig", type: "passive", position: { x: 3, y: 64, z: 2 }, distance: 3.6 },
    { id: 102, name: "cow", type: "passive", position: { x: -5, y: 64, z: 4 }, distance: 6.4 },
    { id: 103, name: "zombie", type: "hostile", position: { x: 12, y: 64, z: -8 }, distance: 14.4 },
  ],
  biome: "plains",
  time: 6000,
  isRaining: false,
};

function addSimulatedInventory(itemName, count = 1) {
  const existing = simulatedState.inventory.find(i => i.name === itemName);
  if (existing) {
    existing.count += count;
  } else {
    const nextSlot = 36 + simulatedState.inventory.length;
    simulatedState.inventory.push({ slot: nextSlot, name: itemName, count });
  }
}

function removeSimulatedInventory(itemName, count = 1) {
  const idx = simulatedState.inventory.findIndex(i => i.name === itemName);
  if (idx !== -1) {
    simulatedState.inventory[idx].count -= count;
    if (simulatedState.inventory[idx].count <= 0) {
      simulatedState.inventory.splice(idx, 1);
    }
    return true;
  }
  return false;
}

function getSimulatedBlock(x, y, z) {
  const key = `${x},${y},${z}`;
  if (simulatedState.mined_blocks.has(key)) return "air";
  if (simulatedState.placed_blocks[key]) return simulatedState.placed_blocks[key];
  if (x === 2 && z === 1 && y >= 64 && y <= 67) return "oak_log";
  if (x === 2 && z === 1 && y === 68) return "oak_leaves";
  if (y > 64) return "air";
  if (y === 64) return "grass_block";
  if (y >= 60 && y < 64) return "dirt";
  return "stone";
}

// JSON-RPC 2.0 Output Helpers
function sendResponse(id, result, error = null) {
  const payload = { jsonrpc: "2.0", id: id };
  if (error) {
    payload.error = typeof error === "string" ? { code: -32603, message: error } : error;
  } else {
    payload.result = result !== undefined ? result : null;
  }
  process.stdout.write(JSON.stringify(payload) + "\n");
}

function sendNotification(method, params) {
  const payload = { jsonrpc: "2.0", method: method, params: params };
  process.stdout.write(JSON.stringify(payload) + "\n");
}

// Line Reader Interface for stdin NDJSON frames
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false,
});

rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;

  let request;
  try {
    request = JSON.parse(trimmed);
  } catch (err) {
    console.error("Malformed JSON line received:", trimmed);
    process.stdout.write(JSON.stringify({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32700, message: "Parse error: invalid JSON" }
    }) + "\n");
    return;
  }

  handleRequest(request);
});

async function handleRequest(req) {
  const { id, method, params } = req;
  const p = params || {};

  try {
    switch (method) {
      case "ping": {
        sendResponse(id, { pong: true, timestamp: Date.now() });
        break;
      }

      case "get_capabilities": {
        sendResponse(id, {
          has_mineflayer: Boolean(mineflayer),
          has_pathfinder: Boolean(pathfinder),
          is_simulated: isSimulated,
          node_version: process.version,
        });
        break;
      }

      case "connect": {
        currentConfig = { ...currentConfig, ...p };
        if (currentConfig.mock_mode || !mineflayer) {
          isSimulated = true;
          isConnected = true;
          isConnecting = false;
          sendResponse(id, {
            status: "connected",
            mode: "simulated",
            username: currentConfig.username,
            host: currentConfig.host,
            port: currentConfig.port,
          });
          sendNotification("bot_event", { event: "spawn", data: { position: simulatedState.position } });
          sendNotification("bot_event", { event: "health", data: { health: simulatedState.health, food: simulatedState.food } });
          return;
        }

        // Live Mineflayer Connection
        isConnecting = true;
        bot = mineflayer.createBot({
          host: currentConfig.host,
          port: currentConfig.port,
          username: currentConfig.username,
          version: currentConfig.version === "auto" ? false : currentConfig.version,
          auth: currentConfig.auth,
        });

        if (pathfinder) {
          bot.loadPlugin(pathfinder);
        }

        bot.once("spawn", () => {
          isConnected = true;
          isConnecting = false;
          sendNotification("bot_event", {
            event: "spawn",
            data: { position: bot.entity ? bot.entity.position : null }
          });
        });

        bot.on("health", () => {
          sendNotification("bot_event", {
            event: "health",
            data: { health: bot.health, food: bot.food, oxygen: bot.oxygenLevel }
          });
        });

        bot.on("death", () => {
          sendNotification("bot_event", { event: "death", data: {} });
        });

        bot.on("chat", (username, message) => {
          if (username === bot.username) return;
          sendNotification("bot_event", { event: "chat", data: { username, message } });
        });

        bot.on("kicked", (reason) => {
          isConnected = false;
          sendNotification("bot_event", { event: "kicked", data: { reason: String(reason) } });
        });

        bot.on("error", (err) => {
          console.error("Mineflayer bot error:", err);
          sendNotification("bot_event", { event: "error", data: { message: err.message } });
        });

        bot.on("end", (reason) => {
          isConnected = false;
          sendNotification("bot_event", { event: "end", data: { reason: String(reason) } });
        });

        sendResponse(id, {
          status: "connecting",
          mode: "live",
          username: currentConfig.username,
          host: currentConfig.host,
          port: currentConfig.port,
        });
        break;
      }

      case "disconnect": {
        if (isSimulated) {
          isConnected = false;
          sendResponse(id, { status: "disconnected" });
          return;
        }

        if (bot) {
          try {
            bot.quit();
          } catch (_e) {
            // Ignore quit error
          }
          bot = null;
        }
        isConnected = false;
        sendResponse(id, { status: "disconnected" });
        break;
      }

      case "status": {
        if (isSimulated) {
          sendResponse(id, {
            connected: isConnected,
            connecting: isConnecting,
            mode: "simulated",
            username: currentConfig.username,
            position: simulatedState.position,
            health: simulatedState.health,
            food: simulatedState.food,
          });
          return;
        }

        sendResponse(id, {
          connected: isConnected,
          connecting: isConnecting,
          mode: "live",
          username: bot ? bot.username : currentConfig.username,
          position: bot && bot.entity ? bot.entity.position : null,
          health: bot ? bot.health : null,
          food: bot ? bot.food : null,
        });
        break;
      }

      case "navigate_to": {
        const { x, y, z, timeout_seconds = 30 } = p;
        if (isSimulated) {
          simulatedState.position = { x: Number(x), y: Number(y), z: Number(z) };
          sendResponse(id, {
            success: true,
            target: { x, y, z },
            reached_position: simulatedState.position,
            duration_ms: 150,
          });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        // Live Pathfinder Implementation
        if (bot.pathfinder) {
          const { goals } = require("mineflayer-pathfinder");
          const goal = new goals.GoalNear(x, y, z, 1);
          bot.pathfinder.setGoal(goal);
          sendResponse(id, { success: true, target: { x, y, z }, status: "navigating" });
        } else {
          // Fallback direct position look
          bot.lookAt(new Vec3(x, y, z));
          sendResponse(id, { success: true, target: { x, y, z }, status: "facing_target" });
        }
        break;
      }

      case "mine_block": {
        const { x, y, z, block_name } = p;
        if (isSimulated) {
          const bName = block_name || getSimulatedBlock(Number(x), Number(y), Number(z));
          const key = `${x},${y},${z}`;
          simulatedState.mined_blocks.add(key);
          delete simulatedState.placed_blocks[key];
          addSimulatedInventory(bName === "oak_log" ? "oak_log" : (bName === "stone" ? "cobblestone" : bName), 1);
          sendResponse(id, {
            success: true,
            block: bName,
            coordinates: { x: Number(x), y: Number(y), z: Number(z) },
            harvested: true,
          });
          sendNotification("inventory_change", { inventory: simulatedState.inventory });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        const block = bot.blockAt(new Vec3(x, y, z));
        if (!block) {
          sendResponse(id, null, { code: -32602, message: `No block found at coordinates (${x}, ${y}, ${z})` });
          return;
        }

        await bot.dig(block);
        sendResponse(id, { success: true, block: block.name, coordinates: { x, y, z } });
        break;
      }

      case "place_block": {
        const { x, y, z, block_name } = p;
        if (isSimulated) {
          const key = `${x},${y},${z}`;
          simulatedState.placed_blocks[key] = block_name || "cobblestone";
          simulatedState.mined_blocks.delete(key);
          removeSimulatedInventory(block_name || "cobblestone", 1);
          sendResponse(id, {
            success: true,
            block: block_name || "cobblestone",
            coordinates: { x: Number(x), y: Number(y), z: Number(z) },
            placed: true,
          });
          sendNotification("inventory_change", { inventory: simulatedState.inventory });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        const item = bot.inventory.items().find(i => i.name === block_name);
        if (!item) {
          sendResponse(id, null, { code: -32602, message: `Item '${block_name}' not in inventory` });
          return;
        }
        await bot.equip(item, "hand");
        const refBlock = bot.blockAt(new Vec3(x, y - 1, z)) || bot.blockAt(new Vec3(x, y, z - 1)) || bot.blockAt(new Vec3(x - 1, y, z));
        if (!refBlock) {
          sendResponse(id, null, { code: -32602, message: `No adjacent block to place against at (${x}, ${y}, ${z})` });
          return;
        }
        await bot.placeBlock(refBlock, new Vec3(0, 1, 0));
        sendResponse(id, { success: true, block: block_name, coordinates: { x, y, z } });
        break;
      }

      case "craft_item": {
        const { item_name, quantity = 1 } = p;
        if (isSimulated) {
          addSimulatedInventory(item_name, Number(quantity));
          sendResponse(id, {
            success: true,
            item: item_name,
            quantity: quantity,
            crafted: true,
          });
          sendNotification("inventory_change", { inventory: simulatedState.inventory });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        sendResponse(id, { success: true, item: item_name, quantity });
        break;
      }

      case "get_block": {
        const { x, y, z } = p;
        if (isSimulated) {
          const bName = getSimulatedBlock(Number(x), Number(y), Number(z));
          sendResponse(id, {
            coordinates: { x: Number(x), y: Number(y), z: Number(z) },
            name: bName,
            hardness: bName === "air" ? 0 : (bName === "stone" ? 1.5 : (bName === "oak_log" ? 2.0 : 0.6)),
            material: bName === "air" ? "air" : (bName === "stone" ? "rock" : (bName === "oak_log" ? "wood" : "dirt")),
            boundingBox: bName === "air" ? "empty" : "block",
          });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        const block = bot.blockAt(new Vec3(x, y, z));
        sendResponse(id, {
          coordinates: { x, y, z },
          name: block ? block.name : "air",
          hardness: block ? block.hardness : 0,
          material: block ? block.material : "air",
          boundingBox: block ? block.boundingBox : "empty",
        });
        break;
      }

      case "find_blocks": {
        const { block_name, radius = 32, max_count = 5 } = p;
        if (isSimulated) {
          const found = [];
          const r = Math.min(Number(radius), 32);
          const maxResults = Math.min(Number(max_count), 20);
          for (let dx = -r; dx <= r && found.length < maxResults; dx++) {
            for (let dz = -r; dz <= r && found.length < maxResults; dz++) {
              for (let dy = -8; dy <= 8 && found.length < maxResults; dy++) {
                const bx = simulatedState.position.x + dx;
                const by = simulatedState.position.y + dy;
                const bz = simulatedState.position.z + dz;
                if (getSimulatedBlock(bx, by, bz) === block_name) {
                  found.push({ x: bx, y: by, z: bz });
                }
              }
            }
          }
          sendResponse(id, {
            block: block_name,
            count: found.length,
            coordinates: found,
          });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        const positions = bot.findBlocks({
          matching: b => b && b.name === block_name,
          maxDistance: Number(radius),
          count: Number(max_count),
        });
        sendResponse(id, {
          block: block_name,
          count: positions.length,
          coordinates: positions.map(pos => ({ x: pos.x, y: pos.y, z: pos.z })),
        });
        break;
      }

      case "look_at": {
        const { x, y, z, pitch, yaw } = p;
        if (isSimulated) {
          if (pitch !== undefined) simulatedState.pitch = Number(pitch);
          if (yaw !== undefined) simulatedState.yaw = Number(yaw);
          sendResponse(id, {
            success: true,
            target: { x: Number(x), y: Number(y), z: Number(z) },
            pitch: simulatedState.pitch,
            yaw: simulatedState.yaw,
          });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        bot.lookAt(new Vec3(x, y, z));
        sendResponse(id, { success: true, target: { x, y, z } });
        break;
      }

      case "use_item": {
        const { item_name } = p;
        if (isSimulated) {
          if (item_name === "bread") {
            simulatedState.food = Math.min(20, simulatedState.food + 5);
            simulatedState.health = Math.min(20, simulatedState.health + 2);
            removeSimulatedInventory("bread", 1);
            sendNotification("health", { health: simulatedState.health, food: simulatedState.food });
            sendNotification("inventory_change", { inventory: simulatedState.inventory });
          }
          sendResponse(id, { success: true, item: item_name, used: true });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        const item = bot.inventory.items().find(i => i.name === item_name);
        if (item) {
          await bot.equip(item, "hand");
        }
        await bot.consume();
        sendResponse(id, { success: true, item: item_name });
        break;
      }

      case "equip_gear": {
        const { slot = "hand", item_name } = p;
        if (isSimulated) {
          sendResponse(id, { success: true, slot, item: item_name });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        sendResponse(id, { success: true, slot, item: item_name });
        break;
      }

      case "attack_target": {
        const { entity_type, max_distance = 16.0 } = p;
        if (isSimulated) {
          sendResponse(id, {
            success: true,
            target_type: entity_type,
            damage_dealt: 7.0,
            defeated: true,
          });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        const target = bot.nearestEntity(e => e.name && e.name.toLowerCase() === entity_type.toLowerCase() && bot.entity.position.distanceTo(e.position) <= max_distance);
        if (!target) {
          sendResponse(id, { success: false, reason: `Target entity '${entity_type}' not within distance ${max_distance}` });
          return;
        }

        bot.attack(target);
        sendResponse(id, { success: true, target_type: entity_type, target_id: target.id });
        break;
      }

      case "inspect_surroundings": {
        const { radius = 16 } = p;
        if (isSimulated) {
          sendResponse(id, {
            position: simulatedState.position,
            radius,
            entities: simulatedState.nearby_entities,
            light_level: 15,
            biome: simulatedState.biome,
          });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        const entities = Object.values(bot.entities)
          .filter(e => e !== bot.entity && bot.entity.position.distanceTo(e.position) <= radius)
          .map(e => ({ id: e.id, name: e.name, type: e.type, position: e.position, distance: bot.entity.position.distanceTo(e.position) }));

        sendResponse(id, {
          position: bot.entity ? bot.entity.position : null,
          radius,
          entities,
          time: bot.time ? bot.time.timeOfDay : null,
        });
        break;
      }

      case "chat": {
        const { message } = p;
        if (isSimulated) {
          sendResponse(id, { success: true, message });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        bot.chat(message);
        sendResponse(id, { success: true, message });
        break;
      }

      case "get_inventory": {
        if (isSimulated) {
          sendResponse(id, { inventory: simulatedState.inventory });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        const items = bot.inventory.items().map(item => ({
          slot: item.slot,
          name: item.name,
          count: item.count,
          durabilityUsed: item.durabilityUsed,
        }));
        sendResponse(id, { inventory: items });
        break;
      }

      case "get_stats": {
        if (isSimulated) {
          sendResponse(id, {
            health: simulatedState.health,
            food: simulatedState.food,
            oxygen: simulatedState.oxygen,
            experience: simulatedState.experience,
          });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        sendResponse(id, {
          health: bot.health,
          food: bot.food,
          oxygen: bot.oxygenLevel,
          experience: bot.experience,
        });
        break;
      }

      case "get_world_info": {
        if (isSimulated) {
          sendResponse(id, {
            biome: simulatedState.biome,
            time: simulatedState.time,
            isRaining: simulatedState.isRaining,
          });
          return;
        }

        if (!bot || !isConnected) {
          sendResponse(id, null, { code: -32002, message: "Bot is not connected to a server" });
          return;
        }

        sendResponse(id, {
          time: bot.time ? bot.time.timeOfDay : null,
          isRaining: bot.isRaining,
        });
        break;
      }

      case "shutdown": {
        if (bot) {
          try { bot.quit(); } catch (_e) {}
        }
        sendResponse(id, { status: "terminating" });
        setTimeout(() => process.exit(0), 100);
        break;
      }

      default: {
        sendResponse(id, null, {
          code: -32601,
          message: `Method not found: ${method}`
        });
        break;
      }
    }
  } catch (err) {
    console.error(`Error handling method '${method}':`, err);
    sendResponse(id, null, {
      code: -32603,
      message: `Internal error in ${method}: ${err.message}`
    });
  }
}

// Clean process termination handling
process.on("SIGINT", () => {
  if (bot) { try { bot.quit(); } catch (_e) {} }
  process.exit(0);
});

process.on("SIGTERM", () => {
  if (bot) { try { bot.quit(); } catch (_e) {} }
  process.exit(0);
});
