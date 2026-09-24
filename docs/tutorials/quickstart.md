# Quickstart: Controlling Video Games with Claude Desktop in Under 10 Minutes

This tutorial guides you through installing `gaming-mcp`, connecting it to Claude Desktop as a Model Context Protocol (MCP) server, and directing your first autonomous game interaction.

---

## Learning Objectives

By the end of this tutorial, you will:

1. Install `gaming-mcp` and its core dependencies using `uv`.
2. Configure Claude Desktop to connect to `gaming-mcp` over the standard input/output (stdio) transport.
3. Observe a live game window, capture an optimized screenshot, and execute mouse and keyboard inputs via natural language prompts.
4. Verify safety mechanisms, including window boundary clamping and the emergency hardware kill-switch.

---

## Prerequisites

Before beginning, ensure you have:

* **Operating System:** Windows 10/11 (recommended for native DXGI Desktop Duplication and Win32 hardware scan codes; Linux and macOS supported via MSS fallback).
* **Python Runtime:** Python 3.11 or later.
* **Package Manager:** `uv` installed (`pip install uv` or via official installer).
* **MCP Client:** Claude Desktop installed and updated to the latest release.
* **Target Application:** A windowed game or puzzle, such as Windows Minesweeper, Solitaire, or any windowed DirectX title.

---

## Step 1: Install the Server

Open a terminal (PowerShell on Windows) and install `gaming-mcp`:

```powershell
# Create a dedicated working directory
mkdir gaming-mcp-workspace
cd gaming-mcp-workspace

# Install gaming-mcp with core dependencies
uv pip install gaming-mcp
```

To enable virtual Xbox 360 controller emulation (via ViGEmBus) and WASAPI loopback audio event detection, install the optional hardware dependencies:

```powershell
uv pip install "gaming-mcp[gamepad,audio]"
```

*Note on Drivers:* If you wish to use virtual gamepad controls, ensure the ViGEmBus driver is installed on your Windows host. If absent, `gaming-mcp` automatically falls back to keyboard/mouse actuation and returns an informative advisory notice upon gamepad requests without crashing.

---

## Step 2: Validate Server Health

Verify that the CLI entry point resolves and dependencies initialize cleanly:

```powershell
uv run python -m gaming_mcp --adapter computer_use --log-level INFO
```

When started interactively over `stdio`, the server listens for JSON-RPC 2.0 messages. Diagnostic log output is routed exclusively to `stderr` to preserve protocol hygiene on `stdout`.

Press `Ctrl+C` to stop the test process.

---

## Step 3: Configure Claude Desktop

Claude Desktop discovers local MCP servers through its central configuration file.

1. Open the Claude Desktop configuration file:
   * **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
   * **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   * **Linux:** `~/.config/Claude/claude_desktop_config.json`

2. If the file does not exist, create it. Add the `gaming-mcp` server configuration:

```json
{
  "mcpServers": {
    "gaming-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--with",
        "gaming-mcp",
        "gaming-mcp",
        "--adapter",
        "computer_use",
        "--transport",
        "stdio"
      ],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

3. Save the file and restart Claude Desktop.

4. In Claude Desktop, look for the hammer icon in the prompt composer. You should see tools registered under `gaming-mcp`, including `screenshot`, `mouse_click`, `send_keys`, and `window_focus`.

---

## Step 4: Your First Autonomous Game Interaction

Now test the end-to-end perception and actuation loop.

1. Launch your target game (for example, Minesweeper or any simple windowed application).
2. Ensure the game window is visible on your primary monitor.
3. In Claude Desktop, enter the following prompt:

```text
Please locate the Minesweeper window using window_focus, capture a screenshot to observe the board, and click on the top-left tile to start the game.
```

### What Happens Behind the Scenes

1. **Window Acquisition:** Claude invokes `window_focus(title_regex="Minesweeper")`. The server queries the Win32 window manager, brings the game to the foreground, and registers its boundary rectangle.
2. **Optimized Screen Capture:** Claude invokes `screenshot(format="jpeg", quality=85, skip_if_static=false)`. The server acquires the frame using DXGI Desktop Duplication (under 8 milliseconds), downscales it to 1024x576, and transmits the base64 JPEG payload.
3. **Spatial Grounding:** Claude analyzes the visual grid and calculates the target pixel coordinates relative to the window or desktop.
4. **Driver-Level Actuation:** Claude invokes `mouse_click(x=..., y=..., button="left")`. The server verifies that the coordinates lie within the active window boundaries, interpolates smooth movement along a minimum-jerk polynomial curve, and executes the click via Win32 `SendInput`.

---

## Step 5: Hardware Safety and Emergency Stop

Safety guardrails are active throughout execution:

* **Window Boundary Clamping:** Coordinates outside the bound game window rect are rejected or clamped, preventing unwanted clicks onto other desktop apps.
* **Process Blacklist:** Inputs targeted at system shells (`cmd.exe`, `powershell.exe`, `Taskmgr.exe`) are rejected with `SecurityViolationError` (-32010).
* **Emergency Kill-Switch:** Press `Ctrl + Alt + Shift + Pause/Break` at any moment to instantaneously sever all motor outputs and release physical/virtual keys.

---

## Next Steps

Now that you have completed basic setup and verified visual control:

* Explore [Configuration Guide](../how_to/configuration_guide.md) to set up ViGEmBus gamepads, WASAPI audio, and Minecraft or Libretro adapters.
* Consult the [Tools and Resources Reference](../reference/tools_and_resources.md) for exhaustive parameter specifications of all 35+ tools.
* Read the [Theoretical Architecture Explanation](../explanation/pomdp_and_token_economics.md) to understand POMDP latency modeling, Action Chunking, and 64-bit dHash token economics.
