# Gaming MCP Server -- Persistent Memory and System Knowledge Base

**Purpose:** This document records architectural invariants, core system configurations, failure modes, subtle platform traps, and proven, replicable solutions. Any agent or developer joining or resuming work on this codebase must consult this file to avoid repeating previously resolved mistakes.

---

## 1. Architectural Invariants and Non-Negotiables

### A. Absolute Zero Emojis Policy (AGENTS.md Rule 1)
* **Standard:** Strictly zero emoji or pictogram characters (Unicode ranges 0x1F000-0x1FFFF, 0x2600-0x27BF, 0x2B50-0x2B55, etc.) are permitted anywhere in this repository (code, docstrings, markdown, task trackers, commits, logs, or agent outputs).
* **Enforcement:** Automated Python Unicode scanner runs in pre-commit and CI. 0 infractions permitted.

### B. Dual-Paradigm Classification
* **Tier 1 (Deterministic High-Fidelity APIs):** Programmatic integration for games with modding or research APIs (Minecraft Mineflayer NDJSON IPC, Libretro cores, OpenAI Gymnasium).
* **Tier 2 (Universal VLA Computer Use):** Game-agnostic screen capture (DXGI Desktop Duplication), WASAPI audio loopback, and driver-level input (ViGEmBus virtual gamepad, Win32 hardware scan codes).
* **Tier 3 (Telemetry & Memory Introspection):** Direct state extraction (RCON, UDP packets, shared memory).

### C. Protocol Conformance
* **MCP Specifications:** Strict adherence to MCP v2025-06-18 and v2026-07-28.
* **Mandatory Primitives:**
  - Cancellation: `notifications/cancelled` must immediately release all held keys and stop action chunks.
  - Progress: Report progress via `notifications/progress` for multi-step routines.
  - Subscriptions: Reactive resource updates via `resources/subscribe` and `notifications/resources/updated`.
  - Human Elicitation: `elicitation/createMessage` is mandatory prior to destructive or irreversible actions.
* **Strict Typing:** All schemas defined using Pydantic v2 models with exhaustive field descriptions.

### D. Autonomy Level L3 and Action Blast Radius T2
* **Autonomy Level L3:** Supervised goal-directed autonomy. The agent team plans, delegates, executes, and verifies with self-healing anti-stall logic.
* **Action Blast Radius T2:** Local execution authority (file edits, test runs, virtual gamepad emulation, local commits).
* **Hard Autonomy Yield:** The ONLY operations that pause for human confirmation are T4 irreversible actions (production database destruction, force-pushing remote branches, secret rotation, financial transactions).

---

## 2. Replicable Knowledge Base: Past Mistakes, Traps, and Proven Corrections

### Case 1: DirectInput / DirectX Games Ignoring Keyboard Input
* **Trap / Mistake:**
  Using `pyautogui.typewrite()` or Win32 `keybd_event` with virtual key codes (`VK_W`, `VK_SPACE`). DirectX, Vulkan, and RawInput games read low-level scan codes directly from the keyboard driver or hardware buffer; user-space virtual key events are completely ignored.
* **Root Cause:**
  Windows GUI event queues (`WM_KEYDOWN`) decouple virtual key codes from scan codes. 3D games using DirectInput inspect the hardware scan code field (`KEYBDINPUT.wScan`). If `wScan` is 0 or `KEYEVENTF_SCANCODE` is omitted, the game engine registers no keypress.
* **Proven Replicable Solution:**
  1. Map virtual keys to PS/2 Set 1 hardware scan codes using `MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC_EX, 0)`.
  2. Call Win32 `SendInput` with `KEYBDINPUT`:
     - Set `dwFlags = KEYEVENTF_SCANCODE` (or `KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP` for release).
     - For extended keys (arrow keys, Insert, Delete, Right Ctrl, Right Alt, Numpad Enter), also set `KEYEVENTF_EXTENDEDKEY` and prefix the scan code with `0xE0`.
     - Set `wVk = 0` to prevent Windows from synthesizing conflicting virtual key events.
* **Code Reference:** `src/gaming_mcp/io/input.py` (`Win32InputInjector`).

---

### Case 2: ViGEmBus Kernel Driver Absence Crashing the Server
* **Trap / Mistake:**
  Directly calling `vgamepad.VX360Gamepad()` during server startup on a machine without the ViGEmBus driver raises a fatal `RuntimeError` / `WindowsError` (driver device interface not found), causing the entire MCP server process to crash on boot.
* **Root Cause:**
  The `vgamepad` Python C-extension attempts to open a handle to `\\.\ViGEmBus`. If the kernel driver is not installed or the service is stopped, `CreateFileW` fails with `ERROR_FILE_NOT_FOUND` (0x2).
* **Proven Replicable Solution:**
  1. Wrap gamepad initialization inside a guarded capability probe during server startup:
     ```python
     try:
         import vgamepad
         gamepad = vgamepad.VX360Gamepad()
         gamepad_available = True
     except Exception as exc:
         logger.warning("ViGEmBus kernel driver not detected: %s", exc)
         gamepad_available = False
     ```
  2. If unavailable, register a stub gamepad handler. Do NOT abort server startup.
  3. When an agent invokes a gamepad tool (`gamepad_control`), return a typed `AdapterError` (-32002):
     `"ViGEmBus driver is not installed. Download from https://github.com/nefarius/ViGEmBus/releases. Keyboard and mouse input remain fully operational."`
  4. Keyboard, mouse, and screen capture operations continue without interruption.

---

### Case 3: DXGI Desktop Duplication Lost Surface in Fullscreen Games
* **Trap / Mistake:**
  The DXGI Desktop Duplication API throws `DXGI_ERROR_ACCESS_LOST` (0x887A0026) or `DXGI_ERROR_INVALID_CALL` (0x887A0001) when a video game switches display modes, enters exclusive fullscreen, or during UAC / lock-screen transitions. If unhandled, screen capture dies permanently.
* **Root Cause:**
  The Windows Desktop Duplication Manager interface is tied to the current desktop surface. When a mode switch occurs, the DirectX device loses ownership and the `IDXGIOutputDuplication` COM interface is invalidated by the OS.
* **Proven Replicable Solution:**
  1. Catch `DXGI_ERROR_ACCESS_LOST` in the frame acquisition loop.
  2. Explicitly release the existing `IDXGIOutputDuplication` and D3D11 device interfaces.
  3. Attempt re-initialization up to 3 times with exponential backoff (50ms, 100ms, 200ms).
  4. If re-acquisition fails after 3 attempts, automatically fall back to Tier 2 (MSS multi-screen capture) with window-handle cropping.
  5. Emit an advisory log to `sys.stderr` and continue serving screenshots via MSS.
* **Code Reference:** `src/gaming_mcp/io/screen.py` (`DXGIScreenCapturer.capture()`).

---

### Case 4: Action Latency Overshoot and Anti-Macro Detection
* **Trap / Mistake:**
  Emitting instantaneous mouse teleports (`SetCursorPos(x, y)`) causes two critical failures:
  1. In 2D games, instantaneous jumps trigger heuristic anti-bot detection and fail spatial button hitboxes that require hover states.
  2. In 3D first-person / third-person games, absolute cursor positioning causes violent, disorienting 360-degree camera spins because the game engine tracks relative mouse raw input (`WM_INPUT` / DirectInput `GetDeviceData`), not absolute coordinates.
* **Root Cause:**
  3D cameras operate on relative mouse deltas $(dx, dy)$ centered at the window midpoint. Teleporting the cursor creates massive delta vectors.
* **Proven Replicable Solution:**
  1. For 2D / UI mouse motion: Interpolate cursor coordinates using minimum-jerk polynomials (Flash & Hogan, 1985) satisfying Fitts' Law:
     $$x(t) = x_0 + (x_f - x_0) \left( 10 (t/T)^3 - 15 (t/T)^4 + 6 (t/T)^5 \right)$$
     with duration $T \in [80\text{ ms}, 250\text{ ms}]$ proportional to distance.
  2. For 3D camera control: Use relative mouse deltas via `mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)` chunked into 16.6ms frame steps with cubic Bezier speed ramps.
  3. Inject Gaussian keypress duration jitter ($\mu = 45\text{ ms}, \sigma = 6\text{ ms}$) on discrete keyboard taps to simulate human motor dispersion.
* **Code Reference:** `src/gaming_mcp/io/trajectory.py` and `src/gaming_mcp/io/input.py`.

---

### Case 5: Stuck Keys on MCP Tool Cancellation
* **Trap / Mistake:**
  When an agent or client cancels an in-flight tool call (e.g. `execute_action_chunk` holding `W` for 2000ms) by sending `notifications/cancelled`, the Python asyncio task is cancelled. If cleanup is not deterministic, the `W` key remains permanently depressed in the game engine, causing the avatar to walk continuously into hazards.
* **Root Cause:**
  `asyncio.CancelledError` unwinds the coroutine stack immediately. If the `key_up` call was scheduled in a future step, it is never reached.
* **Proven Replicable Solution:**
  1. Maintain a thread-safe registry of currently depressed hardware scan codes and active gamepad button masks: `active_keys: set[int]`.
  2. In the cancellation listener (`notifications/cancelled`), execute an immediate, unconditional safety release:
     ```python
     def emergency_motor_reset():
         for scan_code in list(active_keys):
             send_key_event(scan_code, is_up=True)
         active_keys.clear()
         if gamepad_available:
             gamepad.reset()
             gamepad.update()
     ```
  3. Ensure all action chunk loops wrap execution in `try ... finally: emergency_motor_reset()`.
* **Code Reference:** `src/gaming_mcp/core/cancellation.py` and `src/gaming_mcp/io/input.py`.

---

### Case 6: Stdout Pollution Corrupting stdio Transport
* **Trap / Mistake:**
  Standard Python `print()` statements, third-party library banners, or unhandled tracebacks written to `sys.stdout` corrupt the JSON-RPC stream in Claude Desktop or Cursor, causing the client to drop the MCP connection with parse errors.
* **Root Cause:**
  Under `stdio` transport, `sys.stdout` is the raw JSON-RPC 2.0 communication channel. Any non-JSON-RPC text violates protocol framing.
* **Proven Replicable Solution:**
  1. At server startup under `stdio` transport, immediately redirect root logger output to `sys.stderr`:
     ```python
     logging.basicConfig(stream=sys.stderr, level=logging.INFO, format=...)
     ```
  2. Intercept unhandled exceptions with `sys.excepthook` and write structured JSON error traces to `sys.stderr`.
  3. In `pyproject.toml`, set `pytest` to capture stdout (`--capture=sys`).

---

### Case 7: Perceptual dHash False Positives on Animated UI Elements
* **Trap / Mistake:**
  Pulsing HUD elements (e.g., flashing health bar, blinking chat cursor, animated minimap radar) cause the 64-bit difference hash (dHash) to produce a Hamming distance >= 3 even when the player is idle and the scene has not materially changed, defeating token savings.
* **Root Cause:**
  Global 9x8 grayscale dHash evaluates pixel intensity across the entire screen. A high-contrast animation occupying even 5% of the frame alters multiple hash bits.
* **Proven Replicable Solution:**
  1. Support Dynamic Region of Interest (ROI) Slicing: Allow tools to request bounding-box crops (`crop_rect: [x, y, w, h]`), computing dHash only over the relevant gameplay area.
  2. Implement configurable HUD masking: Allow `config.json` to define exclusion rectangles (e.g. status bar at bottom-left) that are blacked out prior to hash calculation.
  3. Keep the Hamming distance threshold configurable (`screen.dhash_threshold = 3`).

---

### Case 8: Mineflayer IPC Bridge Process Desynchronization
* **Trap / Mistake:**
  The Node.js Mineflayer daemon writing diagnostic `console.log()` messages to `process.stdout` desynchronizes the Python NDJSON parser, resulting in dropped game events or JSON decoding crashes.
* **Root Cause:**
  NDJSON (Newline-Delimited JSON) requires every single line on the IPC stream to be valid, parsable JSON.
* **Proven Replicable Solution:**
  1. In the Node.js daemon (`bridge.js`), override `console.log` to redirect all debugging output to `process.stderr`.
  2. Reserve `process.stdout.write(JSON.stringify(payload) + "\n")` exclusively for validated JSON-RPC message frames.
  3. In the Python bridge supervisor (`MinecraftBridge`), validate every received line using `json.loads()` inside a try/except block; log malformed lines to stderr without dropping the IPC socket.
* **Code Reference:** `src/gaming_mcp/adapters/minecraft/bridge.js` and `bridge.py`.

---

## 3. Core System Configuration Reference

### Error Code Allocation Matrix
All application errors map to standard JSON-RPC 2.0 application ranges (-32000 to -32099):
* `-32000`: `GamingMCPError` (Base application error)
* `-32001`: `HardwareIOError` (DXGI capture, Win32 SendInput failure)
* `-32002`: `AdapterError` (ViGEmBus missing, game process not found)
* `-32003`: `ActionExecutionTimeoutError` (Action chunk or pathfinding timeout)
* `-32004`: `SecurityViolationError` (Process blacklist hit, window boundary violation)
* `-32005`: `SafetyKillSwitchTriggered` (Emergency `Ctrl+Alt+Shift+Pause/Break` activated)
* `-32006`: `ElicitationDeniedError` (Human authorization declined)

### Default Performance Constraints
* Frame Grab Target Latency: < 15ms (DXGI), < 35ms (MSS).
* Turbo-JPEG Compression: Quality 85, default resolution 1024x576.
* dHash Threshold: Hamming distance < 3 considered static (<2.5% delta).
* Keyboard Hold Duration: 50ms default with +-6ms Gaussian jitter.
* Emergency Kill-Switch Hook: `Ctrl + Alt + Shift + Pause/Break` (VK_PAUSE = 0x13).
* Process Blacklist: `cmd.exe`, `powershell.exe`, `pwsh.exe`, `Taskmgr.exe`, `CredentialUIBroker.exe`.
