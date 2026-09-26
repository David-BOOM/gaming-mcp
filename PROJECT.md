# Project: Universal Game Control and Automatic Adapter Startup

## Architecture
Universal, game-agnostic control function and automatic adapter startup for gaming-mcp that operates seamlessly across any video game without game-specific customization.

```
MCP Client (Claude Desktop, Cursor, Custom Agent)
       |
       v (JSON-RPC 2.0 via stdio or SSE)
+-------------------------------------------------------------------+
| GamingMCPServer (src/gaming_mcp/server.py)                        |
| - Automatic startup initialization (activates default adapter)    |
| - CancellationManager listening to notifications/cancelled        |
| - MCP ToolRegistry exposing game_control, ping, switch_adapter    |
+---------------------------------+---------------------------------+
                                  |
                                  v
+---------------------------------+---------------------------------+
| AdapterRouter (src/gaming_mcp/adapters/router.py)                 |
| - Active adapter: ComputerUseAdapter (default)                    |
| - Dynamic hot-swapping preserved via switch_adapter tool          |
+---------------------------------+---------------------------------+
                                  |
                                  v
+---------------------------------+---------------------------------+
| ComputerUseAdapter (src/gaming_mcp/adapters/computer_use.py)      |
| - Exposes game_control tool with Pydantic v2 schemas              |
| - Maps high-level commands to actuation primitives                |
+--------+------------------------+-------------------+-------------+
         |                        |                   |
         v                        v                   v
+--------------------+   +-------------------+   +------------------+
| Win32InputInjector |   | GamepadController |   | ActionScheduler  |
| - PS/2 scan codes  |   | - ViGEmBus Xbox   |   | - Microsecond    |
| - Relative mouse   |   |   360 emulation   |   |   compound chunk |
| - Minimum-jerk     |   | - Mock fallback   |   |   execution      |
|   smooth look      |   |   in headless     |   | - Motor reset on |
| - Software fallback|   +-------------------+   |   cancellation   |
+--------------------+                           +------------------+
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Git feature branch setup & pre-flight fixes | Create branch feature/general-game-control, fix pyproject.toml pythonpath, fix MCPServer import, fix params.requestId | M1 | Survey |
| 2 | Minimum-jerk smooth camera look | Implement mouse_look_smooth in Win32InputInjector using generate_relative_camera_deltas | M1 | Survey / R3 |
| 3 | Driver absence and headless fallback | Robust graceful fallback to MockGamepadController and software tracking when drivers are absent | M1 | R3 |
| 4 | Game control Pydantic v2 schemas | Typed schemas for movement, look, interaction, slot, chord, compound sequence | M2 | R1 |
| 5 | game_control tool implementation | High-level unified tool executing movement, camera look, interactions, chords, sequences | M2 | R1 |
| 6 | Cancellation safety integration | Instant release of held keys/sticks and aborting running action sequences upon notifications/cancelled | M2 | R1 / R3 |
| 7 | Built-in adapter auto-registration | Populate router with built-in adapters during server initialization | M3 | R2 |
| 8 | Asynchronous default adapter startup | Server automatically activates default adapter on boot before transport loop starts | M3 | R2 |
| 9 | Dynamic hot-swapping and graceful shutdown | Preserve runtime switch_adapter and ensure clean shutdown releasing inputs | M3 | R2 |
| 10 | E2E Test Suite (Tiers 1-4) | Comprehensive opaque-box test suite for game_control, auto-startup, and fallbacks | E2E Track | ORIGINAL_REQUEST |
| 11 | Final Integration, 100% Pass, Merge, and Push | Full test pass, zero-emoji verification, clean git merge to main, and remote push | M4 | R4 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Requirement-driven test suite (Tiers 1-4) published via TEST_READY.md | none | DONE (TEST_READY.md published, 87/87 pass) |
| 1 | Actuation Engine & Fallback | Git branch setup, pre-flight fixes, mouse_look_smooth, fallback handling | none | DONE (commit a229e86, 315/315 pass) |
| 2 | Game Control Tool Interface | Pydantic v2 schemas and game_control tool implementation with cancellation | M1 | DONE (87/87 pass) |
| 3 | Auto Adapter Startup Lifecycle | Auto-register adapters, auto-activate default adapter on boot, shutdown cleanup | M2 | DONE (319/319 pass) |
| 4 | Final Integration, E2E Pass & Merge | Pass 100% E2E tests, zero emoji audit, clean git merge to main, remote push | E2E, M3 | DONE (363/363 pass, merged to main) |

## Interface Contracts

### game_control Tool Contract
- Tool Name: `game_control`
- Description: "Execute general, game-agnostic control commands: directional movement, camera look, interactions, hotbar slot selection, chords, and compound action sequences."
- Input Schema (`GameControlInput`):
  - `movement`: Optional enum (`forward`, `backward`, `strafe_left`, `strafe_right`, `jump`, `sprint`, `crouch`)
  - `look`: Optional object with fields:
    - `direction`: Optional enum (`look_up`, `look_down`, `look_left`, `look_right`)
    - `dx`: Optional integer relative horizontal delta
    - `dy`: Optional integer relative vertical delta
    - `yaw`: Optional float yaw rotation degrees
    - `pitch`: Optional float pitch rotation degrees
    - `smooth`: Optional boolean (default True) for minimum-jerk trajectory splining
  - `action`: Optional enum (`primary_action`, `secondary_action`, `interact`, `reload`, `pause`, `menu`)
  - `slot`: Optional integer (1 to 9)
  - `chord`: Optional list of strings (e.g. `["shift", "w"]`)
  - `sequence`: Optional list of action sequence steps with delay offsets
  - `hold_duration_ms`: Optional integer hold duration in ms (default 50ms)
- Output Schema:
  - `success: bool`
  - `status: str`
  - `action_type: str`
  - `details: dict[str, Any]`

### Win32InputInjector Smooth Look Contract
- Method: `mouse_look_smooth(total_dx: int, total_dy: int, duration_ms: int = 100, samples: int = 15) -> bool`
- Uses `generate_relative_camera_deltas(total_dx, total_dy, samples)` from `src/gaming_mcp/utils/curves.py`.
- Emits discrete relative deltas using `MOUSEEVENTF_MOVE`.

### GamingMCPServer Startup Lifecycle Contract
- Method: `async def initialize(self) -> None`
- Actions:
  1. Ensures built-in adapters are registered in `self.router`.
  2. Awaits `self.router.switch_adapter(self.config.adapters.default_adapter, self)`.
  3. Binds adapter tools into `self.mcp_server`.
- Invocation:
  - Invoked automatically in `start()`, `run_stdio()`, `run_sse()`, and `run_streamable_http()` prior to awaiting `mcp_server.run_*_async()`.

## Code Layout
- `src/gaming_mcp/schemas/game_control.py`: Pydantic v2 schemas for game_control tool.
- `src/gaming_mcp/io/input.py`: Low-level scan code keyboard and relative/smooth mouse actuation.
- `src/gaming_mcp/io/gamepad.py`: ViGEmBus Xbox 360 controller emulation and mock fallback.
- `src/gaming_mcp/adapters/computer_use.py`: Universal adapter implementing game_control tool.
- `src/gaming_mcp/server.py`: Automatic startup initialization, default adapter activation, and cancellation handling.
- `tests/test_game_control/`: Comprehensive test suite for game control schemas, actuation, and lifecycle.
