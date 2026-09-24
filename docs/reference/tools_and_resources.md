# Tools and Resources Reference

This document provides the authoritative reference specification for all Model Context Protocol (MCP) tools, resources, prompts, and error codes across all adapters in `gaming-mcp`.

---

## 1. Core Server Built-in Interface

### Built-in Tools

#### `server_health`
* **Description:** Retrieve real-time server telemetry, uptime, memory, and subsystem health status.
* **Input Schema:** None.
* **Return Payload:**
  * `server_version` (string): Semantic version of the running server.
  * `uptime_seconds` (number): Elapsed seconds since server initialization.
  * `transport` (string): Active transport protocol (`stdio`, `sse`, or `http`).
  * `active_adapter` (string): Identifier of the active game adapter.
  * `adapters_available` (array of string): List of registered adapter IDs.
  * `screen_capture_backend` (string): Preferred capture backend (`dxgi`, `mss`, or `pillow`).
  * `input_backend` (string): Preferred actuation backend (`scancode`, `vigem`, or `auto`).
  * `audio_enabled` (boolean): Whether WASAPI loopback audio capture is active.
  * `kill_switch_armed` (boolean): Liveness status of the emergency kill-switch hook.
  * `active_subscriptions` (integer): Total number of active resource subscribers.
  * `tools_registered` (integer): Total number of MCP tools currently exposed.
  * `memory_rss_mb` (number): Working set memory footprint of the host process in megabytes.

#### `ping`
* **Description:** Verify server connectivity and clock synchronization.
* **Input Schema:** None.
* **Return Payload:** `status: "pong"`, `timestamp: "<ISO 8601 UTC>"`.

#### `switch_adapter`
* **Description:** Hot-swap the active game adapter at runtime without dropping client transport connections.
* **Input Parameters:**
  * `adapter_id` (string, required): Identifier of adapter to activate (`computer_use`, `minecraft`, `retro`, `gymnasium`).

### Built-in Resources

#### `system://server/health`
* **MIME Type:** `application/json`
* **Description:** Live diagnostic metrics, memory utilization, and subsystem connectivity status.

---

## 2. Universal VLA Computer Use Adapter (`computer_use`)

### Tools

#### `screenshot`
* **Description:** Capture visual display of active game window or desktop. Supports dynamic dHash delta gating, downscaling, and Set-of-Marks visual grid annotations.
* **Input Parameters:**
  * `format` (string, default `"jpeg"`): Image format (`"jpeg"` or `"png"`).
  * `quality` (integer, range 1-100, default 85): JPEG compression quality.
  * `skip_if_static` (boolean, default false): If true, calculates 64-bit dHash and returns text confirmation if visual mutation is below 2.5%, saving tokens.
  * `som_grid` (boolean, default false): If true, renders a labeled Set-of-Marks coordinate grid overlay.
  * `som_spacing` (integer, range 25-500, default 100): Pixel spacing between grid markers.

#### `mouse_click`
* **Description:** Move mouse cursor to target screen coordinates and execute click.
* **Input Parameters:**
  * `x` (integer, required): Target X pixel coordinate.
  * `y` (integer, required): Target Y pixel coordinate.
  * `button` (string, default `"left"`): Mouse button (`"left"`, `"right"`, `"middle"`).
  * `modifiers` (array of string, optional): Modifier keys held during click (`"ctrl"`, `"shift"`, `"alt"`, `"win"`).

#### `mouse_drag`
* **Description:** Execute smooth mouse drag interpolation between two screen coordinates for inventory management or camera rotation.
* **Input Parameters:**
  * `start_x` (integer, required): Starting X pixel coordinate.
  * `start_y` (integer, required): Starting Y pixel coordinate.
  * `end_x` (integer, required): Ending X pixel coordinate.
  * `end_y` (integer, required): Ending Y pixel coordinate.
  * `button` (string, default `"left"`): Drag button (`"left"`, `"right"`, `"middle"`).
  * `duration_ms` (integer, range 50-5000, default 300): Total interpolation duration.
  * `steps` (integer, range 5-100, default 20): Number of intermediate trajectory steps.

#### `send_keys`
* **Description:** Inject discrete keyboard strokes or continuous key hold sequences using Win32 PS/2 Set 1 hardware scan codes.
* **Input Parameters:**
  * `keys` (array of string, required): List of key names (e.g. `["w"]`, `["space"]`, `["ctrl", "s"]`).
  * `hold_duration_ms` (integer, range 10-15000, default 100): Duration key is held down.

#### `execute_action_chunk`
* **Description:** Execute a timed sequence of keyboard, mouse, and gamepad actions locally to overcome cloud inference latency.
* **Input Parameters:**
  * `actions` (array of ActionStep, required): Sequence of timed actions with relative offsets.
  * `max_duration_ms` (integer, default 5000): Maximum allowable duration before timeout.

#### `gamepad_control`
* **Description:** Manipulate a virtual Xbox 360 controller via ViGEmBus driver emulation.
* **Input Parameters:**
  * `left_stick_x` (number, range -1.0 to 1.0, default 0.0): Left stick horizontal axis.
  * `left_stick_y` (number, range -1.0 to 1.0, default 0.0): Left stick vertical axis.
  * `right_stick_x` (number, range -1.0 to 1.0, default 0.0): Right stick horizontal axis.
  * `right_stick_y` (number, range -1.0 to 1.0, default 0.0): Right stick vertical axis.
  * `left_trigger` (number, range 0.0 to 1.0, default 0.0): Left trigger analog pressure.
  * `right_trigger` (number, range 0.0 to 1.0, default 0.0): Right trigger analog pressure.
  * `buttons_down` (array of string, optional): Buttons to press down (`"a"`, `"b"`, `"x"`, `"y"`, `"lb"`, `"rb"`, `"start"`, `"back"`).
  * `buttons_up` (array of string, optional): Buttons to release.
  * `duration_ms` (integer, default 100): Duration to hold state before auto-resetting.

#### `window_focus`
* **Description:** Locate game window by title regex, bring to foreground, and lock cursor capture rect.
* **Input Parameters:**
  * `title_regex` (string, required): Regular expression matching window title.
  * `bring_to_top` (boolean, default true): Bring matched window to top of z-order.

### Resources

#### `game://audio/events`
* **MIME Type:** `application/json`
* **Description:** Stream of tactical acoustic cues (loudness spikes, alarms, footsteps) detected via WASAPI loopback.

#### `game://screen/info`
* **MIME Type:** `application/json`
* **Description:** Real-time display resolution, monitor count, and foreground window status.

### Prompts

#### `gameplay_strategy`
* **Arguments:** `game_title` (optional), `objective` (optional).
* **Description:** Scaffolding prompt for autonomous game strategy, visual grounding, and coordinate translation.

---

## 3. Minecraft High-Fidelity Adapter (`minecraft`)

### Tools

#### `mc_navigate_to`
* **Description:** Compute and execute 3D voxel pathfinding to target coordinates using A* heuristics.
* **Input Parameters:** `x` (number), `y` (number), `z` (number), `timeout_seconds` (number, default 30.0).

#### `mc_mine_block`
* **Description:** Equip optimal harvest tool and dig block at specified voxel coordinates.
* **Input Parameters:** `x` (integer), `y` (integer), `z` (integer).

#### `mc_craft_item`
* **Description:** Craft an item from internal recipe graph, navigating to crafting table if required.
* **Input Parameters:** `item_name` (string), `count` (integer, default 1).

#### `mc_equip_gear`
* **Description:** Equip armor, weapon, or utility item into a body slot.
* **Input Parameters:** `item_name` (string), `destination` (string: `"hand"`, `"head"`, `"torso"`, `"legs"`, `"feet"`, `"off-hand"`).

#### `mc_attack_target`
* **Description:** Face and execute combat attacks against nearest entity matching query.
* **Input Parameters:** `entity_id` (integer, optional), `entity_type` (string, optional), `duration_seconds` (number, default 5.0).

#### `mc_inspect_surroundings`
* **Description:** Return structured spatial report of nearby entities, light levels, biome, and time of day.
* **Input Parameters:** `radius` (integer, range 1-64, default 16).

#### `mc_place_block`
* **Description:** Place a block from inventory at designated voxel coordinates.
* **Input Parameters:** `x` (integer), `y` (integer), `z` (integer), `face` (string: `"top"`, `"bottom"`, `"north"`, `"south"`, `"east"`, `"west"`).

#### `mc_craft_recipe`
* **Description:** Intelligently resolve and craft a target item, recursively crafting required prerequisites.
* **Input Parameters:** `recipe_name` (string), `quantity` (integer, default 1), `auto_craft_prerequisites` (boolean, default true).

#### `mc_get_block`
* **Description:** Inspect voxel block properties (name, hardness, bounding box) at coordinates.
* **Input Parameters:** `x` (integer), `y` (integer), `z` (integer).

#### `mc_find_blocks`
* **Description:** Scan 3D space within a radius for matching blocks (e.g. `oak_log`, `iron_ore`).
* **Input Parameters:** `block_name` (string), `radius` (integer, default 32), `max_count` (integer, default 5).

#### `mc_look_at`
* **Description:** Orient bot pitch and yaw angles toward target coordinates.
* **Input Parameters:** `x` (number), `y` (number), `z` (number), `pitch` (number, optional), `yaw` (number, optional).

#### `mc_use_item`
* **Description:** Consume or activate held item from inventory.
* **Input Parameters:** `item_name` (string).

#### `mc_chat`
* **Description:** Send text message or slash command to Minecraft server.
* **Input Parameters:** `message` (string).

#### `mc_reconnect`
* **Description:** Force child process daemon restart and reconnect to Minecraft server.
* **Input Parameters:** `force` (boolean, default true).

### Resources

#### `minecraft://player/inventory`
* **MIME Type:** `application/json`
* **Description:** Real-time breakdown of player inventory slots, off-hand, armor, and item counts.

#### `minecraft://player/stats`
* **MIME Type:** `application/json`
* **Description:** Current health (0-20), food level, oxygen, and experience metrics.

#### `minecraft://world/surroundings`
* **MIME Type:** `application/json`
* **Description:** Report of nearby entities, threat assessments, and lighting levels.

#### `minecraft://world/biome_and_time`
* **MIME Type:** `application/json`
* **Description:** Current biome name, celestial tick time, and weather status.

---

## 4. Retro & Emulation Adapter (`retro`)

### Tools

#### `retro_send_pad`
* **Description:** Send gamepad button inputs to emulator core for exact frame duration.
* **Input Parameters:**
  * `buttons` (array of string, required): Buttons to actuate (`"A"`, `"B"`, `"UP"`, `"DOWN"`, `"LEFT"`, `"RIGHT"`, `"SELECT"`, `"START"`).
  * `frames` (integer, range 1-120, default 1): Number of frame steps buttons remain depressed.

#### `retro_save_state`
* **Description:** Serialize emulator memory, CPU registers, and frame state into named snapshot slot.
* **Input Parameters:** `slot_name` (string, required).

#### `retro_load_state`
* **Description:** Restore emulator state from a previously saved snapshot slot.
* **Input Parameters:** `slot_name` (string, required).

#### `retro_read_ram`
* **Description:** Directly read arbitrary RAM memory bytes by start address and length.
* **Input Parameters:**
  * `address` (integer, required): Starting memory byte address.
  * `length` (integer, range 1-1024, default 1): Number of sequential bytes to read.

### Resources

#### `retro://screen`
* **MIME Type:** `image/png`
* **Description:** Raw unscaled emulator frame buffer serialized as lossless PNG.

#### `retro://ram/variables`
* **MIME Type:** `application/json`
* **Description:** Pre-mapped game telemetry extracted directly from RAM (score, lives, position, timer).

---

## 5. Gymnasium RL Adapter (`gymnasium`)

### Tools

#### `gym_step`
* **Description:** Step active Gymnasium environment by executing an action.
* **Input Parameters:** `action` (integer, array of float, or array of integer).
* **Return Payload:** `observation`, `reward` (float), `terminated` (bool), `truncated` (bool), `info` (dict).

#### `gym_reset`
* **Description:** Reset Gymnasium environment to initial state.
* **Input Parameters:** `seed` (integer, optional).

#### `gym_action_space`
* **Description:** Retrieve specification, bounds, shape, and type of environment action space.
* **Input Parameters:** None.

#### `gym_observation_space`
* **Description:** Retrieve specification, bounds, shape, and type of environment observation space.
* **Input Parameters:** None.

#### `gym_render`
* **Description:** Render environment frame and return as base64-encoded image.
* **Input Parameters:** `format` (string: `"png"` or `"jpeg"`).

### Resources

#### `gym://observation`
* **MIME Type:** `application/json`
* **Description:** Real-time observation vector and transition metadata.

#### `gym://state`
* **MIME Type:** `application/json`
* **Description:** Cumulative reward, episode count, step count, and space configurations.

---

## 6. Voyager-Style Skill Library Manager (`skills`)

### Tools

#### `skill_search`
* **Description:** Search persistent library for relevant macros using semantic vector similarity.
* **Input Parameters:** `query` (string, required), `top_k` (integer, default 5), `tags` (array of string, optional).

#### `skill_register`
* **Description:** Register reusable composite macro skill with parameter templates and compensation steps.
* **Input Parameters:** `name` (string), `description` (string), `parameters` (dict), `steps` (array of MacroStep), `tags` (array of string).

#### `skill_execute`
* **Description:** Execute registered composite skill with parameter binding and auto-repair.
* **Input Parameters:** `name` (string), `parameters` (dict), `auto_repair` (boolean, default true).

#### `skill_delete`
* **Description:** Delete a composite skill from persistent library.
* **Input Parameters:** `name` (string).

#### `skill_get`
* **Description:** Retrieve full specification and parameter schema of registered skill.
* **Input Parameters:** `name` (string).

#### `skill_list`
* **Description:** List registered skills in library with optional tag filtering.
* **Input Parameters:** `tags` (array of string, optional).

### Resources

#### `skills://registry`
* **MIME Type:** `application/json`
* **Description:** Full catalog of registered composite macros and performance metrics.

#### `skills://history`
* **MIME Type:** `application/json`
* **Description:** Log of recent macro execution traces, step latencies, and self-repair actions.

---

## 7. Error Code Reference

`gaming-mcp` maps all exceptions to standardized JSON-RPC 2.0 error responses:

| Code   | Error Name                   | Meaning and Recovery Action |
|--------|------------------------------|-----------------------------|
| -32700 | `ParseError`                 | Invalid JSON-RPC payload received by server. |
| -32600 | `InvalidRequest`             | Message is not a valid JSON-RPC 2.0 request. |
| -32601 | `MethodNotFound`             | Requested tool, resource, or prompt name is not registered. |
| -32602 | `InvalidParams`              | Tool parameters failed Pydantic schema validation. |
| -32603 | `InternalError`              | Uncaught exception in server dispatcher. |
| -32000 | `GamingMCPError`             | Base application error. Inspect `message` for context. |
| -32001 | `AdapterNotFoundError`       | Requested `adapter_id` not found in registry. Call `server_health` to view available adapters. |
| -32002 | `AdapterInitializationError` | Hardware driver or child process failed to start. Verify prerequisites. |
| -32003 | `CaptureError`               | Frame acquisition failure. Capturer automatically falls back to MSS. |
| -32004 | `InputInjectionError`        | Hardware scan code or virtual gamepad write failed. |
| -32010 | `SecurityViolationError`     | Action blocked by window boundary clipping or process blacklist. |
| -32015 | `SkillExecutionError`        | Composite macro failed during step execution. |
| -32020 | `ElicitationDeniedError`     | Human user denied authorization for an action. |
