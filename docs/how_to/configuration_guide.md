# Configuration Guide: Goal-Oriented Recipes

This guide provides practical recipes for configuring `gaming-mcp` across different operational scenarios, including virtual gamepad emulation, hardware-accelerated screen capture, Minecraft IPC integration, retro game emulation, and security hardening.

---

## Configuration Layering and Priority

`gaming-mcp` evaluates configuration settings using a strict four-tier hierarchy:

1. **Command-Line Arguments:** `--adapter`, `--transport`, `--port`, `--host`, `--config`, `--log-level`.
2. **Environment Variables:** `GAMING_MCP_ADAPTER`, `GAMING_MCP_TRANSPORT`, `GAMING_MCP_CONFIG`.
3. **JSON Configuration File:** `config.json` in the current working directory, or specified via `--config`.
4. **Built-in Defaults:** Standard defaults defined in `gaming_mcp.config.GamingMCPConfig`.

---

## Recipe 1: Configuring ViGEmBus Virtual Gamepad Emulation

### Objective
Enable analog thumbstick movement, 360-degree camera rotation, and pressure-sensitive trigger control for controller-optimized 3D games (such as racing, sports, or third-person action titles).

### Step 1: Install the ViGEmBus Kernel Driver
1. Download the official ViGEmBus driver installer from the Nefarius GitHub release repository (`ViGEmBus_Setup_1.22.0.exe` or later).
2. Run the installer with administrative privileges and restart your system if prompted.
3. Verify driver status in Windows Device Manager under **System devices** > **Virtual Gamepad Emulation Bus**.

### Step 2: Install Python Gamepad Dependencies
Install `vgamepad` within your virtual environment:

```powershell
uv pip install "gaming-mcp[gamepad]"
```

### Step 3: Configure Preferred Backend
In your `config.json`, set the preferred input backend to `"vigem"` or `"auto"`:

```json
{
  "input": {
    "preferred_backend": "auto",
    "mouse_smoothing": true,
    "jitter_range_px": 2
  }
}
```

When set to `"auto"`, the server probes for driver availability upon startup. If the driver is present, it registers a virtual Xbox 360 controller (`Xbox360Gamepad`). If the driver is absent, the server logs an advisory notice and routes keyboard/mouse operations through Win32 `SendInput` without failing.

### Step 4: Validate Virtual Controller
Verify that Windows detects the virtual controller:
1. Press `Win + R`, type `joy.cpl`, and press Enter.
2. When `gamepad_control` is invoked by an agent, verify that "Controller (XBOX 360 For Windows)" appears in the list of installed game controllers.

---

## Recipe 2: Configuring High-Speed DXGI Screen Capture

### Objective
Acquire uncompressed desktop or game frames in under 8 milliseconds using DirectX Graphics Infrastructure (DXGI) Desktop Duplication with ACES filmic HDR-to-SDR tone-mapping.

### Step 1: Configure Screen Capture Settings
Add the `screen` section to `config.json`:

```json
{
  "screen": {
    "preferred_backend": "dxgi",
    "monitor_index": 0,
    "default_format": "jpeg",
    "jpeg_quality": 85,
    "downscale_resolution": [1024, 576],
    "dhash_threshold": 3,
    "som_grid_spacing": 100
  }
}
```

### Key Parameters
* `preferred_backend`: `"dxgi"` for Windows GPU zero-copy capture, or `"mss"` for cross-platform compatibility.
* `monitor_index`: 0-indexed monitor selector for multi-display setups.
* `jpeg_quality`: Balance between compression speed, bandwidth, and visual fidelity (default 85 yields 120-180 KB per frame).
* `dhash_threshold`: Hamming distance cutoff (0 to 64). A value of 3 suppresses transmission when visual differences are under 2.5%, saving up to 80% in token costs on static screens.

### Handling Fullscreen Mode Shifts
If a game transitions into exclusive fullscreen mode, DXGI may raise `DXGI_ERROR_ACCESS_LOST` (0x887A0026). The `CompositeScreenCapturer` automatically attempts re-initialization up to 3 times before seamlessly falling back to the Tier 2 MSS capturer.

---

## Recipe 3: Configuring the Minecraft Survival Bridge

### Objective
Connect an autonomous survival agent to a Minecraft Java Edition server using the high-fidelity Mineflayer Node.js IPC daemon.

### Step 1: Verify Node.js Environment
Ensure Node.js 18.0 or later is installed:

```powershell
node --version
npm --version
```

### Step 2: Configure Minecraft Adapter Settings
In `config.json`, configure the target server and credentials:

```json
{
  "adapters": {
    "default_adapter": "minecraft",
    "minecraft": {
      "host": "127.0.0.1",
      "port": 25565,
      "username": "VoyagerBot",
      "auth_type": "offline",
      "version": "1.20.4",
      "auto_reconnect": true,
      "heartbeat_interval_sec": 5.0
    }
  }
}
```

### Step 3: Launch with Minecraft Adapter
Launch the server specifying the Minecraft adapter:

```powershell
uv run python -m gaming_mcp --adapter minecraft --transport stdio
```

### Process Lifecycle and Self-Healing
The Python adapter spawns the Node.js bridge (`src/gaming_mcp/adapters/minecraft_daemon.js`) as a managed subprocess using bidirectional NDJSON streams. If the Minecraft server kicks the bot or restarts, the Python supervisor applies an exponential backoff loop to automatically reconnect without requiring an MCP server restart.

---

## Recipe 4: Configuring Libretro and Stable-Retro Emulation

### Objective
Interface with Libretro emulator cores for frame-stepping, instantaneous memory snapshotting (`retro_save_state` / `retro_load_state`), and RAM inspection.

### Step 1: Install Retro Dependencies
Install the optional retro package group:

```powershell
uv pip install "gaming-mcp[retro]"
```

### Step 2: Configure Emulator Core and Game Target
Configure the retro adapter in `config.json`:

```json
{
  "adapters": {
    "default_adapter": "retro",
    "retro": {
      "game": "SuperMarioBros-Nes",
      "state": null,
      "scenario": null
    }
  }
}
```

### Step 3: Simulated Core Fallback
If native emulator binaries or copyrighted game ROMs are not present on the host system, the adapter automatically activates `SimulatedRetroCore`. This high-fidelity simulation reproduces NES Super Mario Bros physics, horizontal scrolling, and byte-accurate RAM register offsets (such as `0x0086` for player X-coordinate and `0x075A` for lives) for testing and development.

---

## Recipe 5: Hardening Security Envelopes and Safety Bounds

### Objective
Prevent agents from accidentally interacting with system utilities, personal documents, or sensitive processes during gameplay.

### Step 1: Configure Safety Envelopes
In `config.json`, specify boundary clamping, process blacklists, and privacy redaction zones:

```json
{
  "security": {
    "enable_kill_switch": true,
    "kill_switch_combo": ["ctrl", "alt", "shift", "pause"],
    "window_boundary_clipping": true,
    "blacklisted_processes": [
      "cmd.exe",
      "powershell.exe",
      "pwsh.exe",
      "Taskmgr.exe",
      "regedit.exe",
      "mmc.exe",
      "explorer.exe",
      "chrome.exe",
      "msedge.exe"
    ],
    "privacy_redaction_zones": [
      {
        "x": 0,
        "y": 1040,
        "width": 1920,
        "height": 40
      }
    ]
  }
}
```

### Security Defenses Explained
1. **Window Boundary Clipping:** When `window_boundary_clipping` is enabled, any click or drag target outside the focused game window rectangle is rejected with `SecurityViolationError` (-32010).
2. **Process Blacklist:** Before executing keyboard or mouse injections, the server inspects the process name of the active foreground window. If it matches an entry in `blacklisted_processes`, the action is blocked.
3. **Privacy Redaction Zones:** Specified coordinate rectangles (such as the Windows Taskbar or system clock) are zeroed out with black fill before screenshot serialization.
4. **Emergency Hardware Kill-Switch:** A dedicated background thread monitors global low-level keyboard input for `Ctrl + Alt + Shift + Pause/Break`. Pressing this combination instantaneously releases all held keys, resets virtual gamepad sticks, and clears the action queue.
