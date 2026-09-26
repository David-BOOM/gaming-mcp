# Test Infrastructure Specification: Universal Game Control and Auto-Startup

## 1. Executive Summary and Testing Philosophy

This document defines the end-to-end (E2E) test infrastructure, methodologies, and test catalog for the Universal Game Control and Automatic Default Adapter Startup in `gaming-mcp`.

The test infrastructure employs a rigorous four-tier methodology:
1. **Tier 1 - Feature Coverage (Category-Partition Testing)**: Systematically partitions input and configuration domains into valid equivalence classes, ensuring each discrete capability (movement, camera look, interactions, slots, chords, compound sequences, auto-startup, dynamic hot-swapping, cancellation, and driver fallback) has at least 5 targeted test cases.
2. **Tier 2 - Boundary Value Analysis (BVA) and Negative Robustness**: Tests edge cases, off-nominal inputs, extreme values, out-of-range boundaries, malformed syntax, concurrency races, and adversarial cancellation timings.
3. **Tier 3 - Cross-Feature Combinations (Pairwise / Combinatorial Testing)**: Exercises 2-way interactions across orthogonal subsystems (e.g., simultaneous locomotion and camera panning, sprint-jumping, hotbar switching while strafing, chorded input during primary action).
4. **Tier 4 - Real-World Application Workloads**: Simulates multi-stage real-world gameplay sequences representing production agent workloads (first-person navigation, tactical combat, inventory management, headless exploration, and emergency aborts).

### Invariants and Standards
- **Zero Emojis Policy (Absolute)**: Strictly 0 emoji or pictogram Unicode characters (ranges 0x1F000-0x1FFFF, 0x2600-0x27BF, 0x2B50-0x2B55, etc.) in all code, tests, docs, and outputs.
- **Strict Static Typing**: 100% compliance with `mypy --strict` on Python 3.12.
- **Clean Linting**: Zero errors or warnings under `ruff check`.
- **Deterministic and Isolated**: Tests must not rely on external hardware or real display servers, using high-fidelity in-memory injectors and mock controllers where appropriate.

---

## 2. Test Harness Architecture

The test harness operates at the Model Context Protocol (MCP) tool execution layer and the adapter SPI layer:

```
+-------------------------------------------------------------------------+
| Pytest Test Runner (pytest -o pythonpath=src)                           |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| Test Harness Fixtures (tests/test_game_control/)                        |
| - MockScreenCapturer: In-memory synthetic frame buffers                 |
| - MockInputInjector: Records keystrokes, relative mouse, smooth look    |
| - MockGamepadController: Records thumbstick vectors and button presses  |
| - MockWindowManager: Returns deterministic window handles and bounds    |
| - MockActionScheduler: Sub-millisecond timing and chunk dispatch        |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| Universal Game Control Engine (Under Test)                              |
| - GameControlInput / Pydantic v2 schemas: Strict parameter validation   |
| - ComputerUseAdapter / game_control: High-level command translation     |
| - GamingMCPServer / AdapterRouter: Auto-startup and dynamic hot-swap    |
| - CancellationManager: notifications/cancelled and emergency motor cut  |
| - Win32InputInjector: PS/2 scan codes and minimum-jerk smooth look      |
+-------------------------------------------------------------------------+
```

### Key Test Fixtures
- `mock_input_injector`: Intercepts and records `send_keys`, `mouse_click`, `mouse_drag`, `mouse_look_smooth`, `key_down`, `key_up`, and `release_all`.
- `mock_gamepad`: In-memory virtual gamepad tracking thumbsticks, triggers, and buttons without requiring physical hardware or ViGEmBus kernel drivers.
- `mock_screen_capturer`: Supplies synthetic 200x200 RGB frames and tracks frame acquisitions.
- `mock_window_manager`: Simulates foreground game windows and background system processes for boundary clipping and blacklist verification.
- `cancellation_manager`: Validates prompt cancellation and motor safety resets upon `notifications/cancelled`.
- `game_control_adapter`: Wired `ComputerUseAdapter` instance populated with mock I/O subsystems for end-to-end tool execution.
- `test_server`: Server instance verifying auto-startup initialization, default adapter activation, and tool exposure in `tools/list`.

---

## 3. Four-Tier Test Catalog

### Tier 1: Feature Coverage (Category-Partition)

| Test ID | Category | Target Feature | Partition / Input | Expected Observable Behavior |
|---------|----------|----------------|-------------------|------------------------------|
| T1-MOV-01 | Movement | forward | `movement="forward"` | Injects forward key ('w') with hold duration; returns success |
| T1-MOV-02 | Movement | backward | `movement="backward"` | Injects backward key ('s') with hold duration; returns success |
| T1-MOV-03 | Movement | strafe_left | `movement="strafe_left"` | Injects strafe left key ('a'); returns success |
| T1-MOV-04 | Movement | strafe_right | `movement="strafe_right"` | Injects strafe right key ('d'); returns success |
| T1-MOV-05 | Movement | jump | `movement="jump"` | Injects jump key ('space'); returns success |
| T1-MOV-06 | Movement | sprint | `movement="sprint"` | Injects sprint key ('shift'); returns success |
| T1-MOV-07 | Movement | crouch | `movement="crouch"` | Injects crouch key ('ctrl'); returns success |
| T1-LOK-01 | Camera Look | look_up | `look={"direction": "look_up"}` | Injects upward relative mouse delta (`dy < 0`) |
| T1-LOK-02 | Camera Look | look_down | `look={"direction": "look_down"}` | Injects downward relative mouse delta (`dy > 0`) |
| T1-LOK-03 | Camera Look | look_left | `look={"direction": "look_left"}` | Injects leftward relative mouse delta (`dx < 0`) |
| T1-LOK-04 | Camera Look | look_right | `look={"direction": "look_right"}` | Injects rightward relative mouse delta (`dx > 0`) |
| T1-LOK-05 | Camera Look | relative deltas | `look={"dx": 120, "dy": -80}` | Injects exact relative mouse deltas `(120, -80)` |
| T1-LOK-06 | Camera Look | pitch and yaw | `look={"yaw": 45.0, "pitch": -15.0}` | Converts angular degrees to relative deltas based on sensitivity |
| T1-LOK-07 | Camera Look | smooth trajectory | `look={"dx": 100, "dy": 50, "smooth": True}` | Emits discrete sliced deltas summing to `(100, 50)` via minimum-jerk |
| T1-ACT-01 | Interaction | primary_action | `action="primary_action"` | Emits left mouse click or primary gamepad trigger |
| T1-ACT-02 | Interaction | secondary_action | `action="secondary_action"` | Emits right mouse click or secondary gamepad trigger |
| T1-ACT-03 | Interaction | interact | `action="interact"` | Emits interact key ('e' or 'f'); returns success |
| T1-ACT-04 | Interaction | reload | `action="reload"` | Emits reload key ('r'); returns success |
| T1-ACT-05 | Interaction | pause | `action="pause"` | Emits pause key ('escape'); returns success |
| T1-ACT-06 | Interaction | menu | `action="menu"` | Emits menu key ('tab' or 'm'); returns success |
| T1-SLT-01 | Hotbar | slot 1 | `slot=1` | Injects number key '1'; returns success |
| T1-SLT-02 | Hotbar | slot 3 | `slot=3` | Injects number key '3'; returns success |
| T1-SLT-03 | Hotbar | slot 5 | `slot=5` | Injects number key '5'; returns success |
| T1-SLT-04 | Hotbar | slot 7 | `slot=7` | Injects number key '7'; returns success |
| T1-SLT-05 | Hotbar | slot 9 | `slot=9` | Injects number key '9'; returns success |
| T1-CHD-01 | Chords | sprint forward | `chord=["shift", "w"]` | Holds shift and w concurrently, then releases both |
| T1-CHD-02 | Chords | jump forward | `chord=["w", "space"]` | Holds w and space concurrently, then releases both |
| T1-CHD-03 | Chords | crouch walk | `chord=["ctrl", "w"]` | Holds ctrl and w concurrently, then releases both |
| T1-CHD-04 | Chords | inventory drop | `chord=["ctrl", "q"]` | Holds ctrl and q concurrently, then releases both |
| T1-CHD-05 | Chords | sprint jump strafe | `chord=["shift", "w", "space"]` | Holds 3-key chord concurrently, then releases all |
| T1-SEQ-01 | Sequence | move and look | `sequence=[{"movement": "forward"}, {"look": {"dx": 50}}]` | Executes step 1 then step 2 in sequential order |
| T1-SEQ-02 | Sequence | slot and interact | `sequence=[{"slot": 2}, {"action": "interact"}]` | Selects slot 2 then performs interact action |
| T1-SEQ-03 | Sequence | pause and menu | `sequence=[{"action": "pause"}, {"action": "menu"}]` | Executes pause followed by menu |
| T1-SEQ-04 | Sequence | attack and reload | `sequence=[{"action": "primary_action"}, {"action": "reload"}]` | Executes primary action followed by reload |
| T1-SEQ-05 | Sequence | multi-step patrol | 4-step sequence (forward, look, forward, pause) | Executes all 4 steps chronologically; returns success |
| T1-AUT-01 | Auto-Startup | default activation | Server boot without `switch_adapter` | `router.active_adapter_id` equals `computer_use` |
| T1-AUT-02 | Auto-Startup | tool exposure | `tools/list` on fresh server | `game_control` tool is present in tool list |
| T1-AUT-03 | Auto-Startup | tool execution | Execute `game_control` on fresh server | Executes successfully without requiring prior adapter switch |
| T1-AUT-04 | Auto-Startup | health reflects active | `get_health()` on fresh server | `active_adapter` is `computer_use` and `is_initialized` is True |
| T1-AUT-05 | Auto-Startup | resource exposure | `resources/list` on fresh server | Adapter resources are active and queryable |
| T1-DYN-01 | Dynamic Swap | switch to minecraft | `switch_adapter("minecraft")` | Deactivates `computer_use`, activates `minecraft`, updates tools |
| T1-DYN-02 | Dynamic Swap | switch back to default | `switch_adapter("computer_use")` | Reactivates `computer_use`, re-exposes `game_control` |
| T1-DYN-03 | Dynamic Swap | switch to retro | `switch_adapter("retro")` | Activates `retro`, exposes retro tools |
| T1-DYN-04 | Dynamic Swap | switch to gymnasium | `switch_adapter("gymnasium")` | Activates `gymnasium`, exposes gym tools |
| T1-DYN-05 | Dynamic Swap | clean resource unbind | Adapter hot-swap | Old adapter tools and resources are cleanly detached |
| T1-CAN-01 | Cancellation | abort running sequence | `cancel_request(request_id)` during sequence | Sequence terminates early, returns cancelled status |
| T1-CAN-02 | Cancellation | key release on cancel | `cancel_request(request_id)` while keys held | `release_all()` invoked, clearing all active scan codes |
| T1-CAN-03 | Cancellation | stick reset on cancel | `cancel_request(request_id)` while stick deflected | Virtual gamepad sticks reset to `(0.0, 0.0)` |
| T1-CAN-04 | Cancellation | emergency reset hook | `emergency_reset()` invoked | Both keyboard and gamepad actuators fully released |
| T1-CAN-05 | Cancellation | cancelled notification | Protocol `notifications/cancelled` | Low-level cancellation handler halts active token |
| T1-FLB-01 | Fallback | missing ViGEmBus | ViGEmBus driver not present | Gracefully falls back to MockGamepadController |
| T1-FLB-02 | Fallback | gamepad actuation mock | Gamepad control commands on headless system | Records thumbstick and button operations without error |
| T1-FLB-03 | Fallback | software input tracking | Physical display or driver unavailable | In-memory key tracking records all pressed/released keys |
| T1-FLB-04 | Fallback | non-Windows platform | Host platform simulated as Linux/Darwin | Bypasses Win32 SendInput without uncaught exceptions |
| T1-FLB-05 | Fallback | screen capture fallback | DXGI access lost or unavailable | Gracefully falls back to MSS capturer without dropping frames |

---

### Tier 2: Boundary Value Analysis and Corner Cases

| Test ID | Category | Target Boundary | Input / Condition | Expected Observable Behavior |
|---------|----------|-----------------|-------------------|------------------------------|
| T2-BVA-01 | Parameters | empty input | `{}` (no fields populated) | Returns validation error or graceful no-op with warning |
| T2-BVA-02 | Hotbar | slot lower bound - 1 | `slot=0` | Pydantic validation error (`ge=1`); returns error code -32602 |
| T2-BVA-03 | Hotbar | slot upper bound + 1 | `slot=10` | Pydantic validation error (`le=9`); returns error code -32602 |
| T2-BVA-04 | Hotbar | slot negative | `slot=-5` | Validation error; rejected prior to actuation |
| T2-BVA-05 | Hotbar | slot exactly 1 | `slot=1` | Accepted and correctly maps to key '1' |
| T2-BVA-06 | Hotbar | slot exactly 9 | `slot=9` | Accepted and correctly maps to key '9' |
| T2-BVA-07 | Look Deltas | zero deltas | `look={"dx": 0, "dy": 0}` | Accepted; performs zero-displacement camera update |
| T2-BVA-08 | Look Deltas | extreme positive delta | `look={"dx": 10000, "dy": 5000}` | Clamped or splined without integer overflow or crash |
| T2-BVA-09 | Look Deltas | extreme negative delta | `look={"dx": -10000, "dy": -5000}` | Clamped or splined safely; sum equals original delta |
| T2-BVA-10 | Hold Time | zero hold duration | `hold_duration_ms=0` | Accepted; emits immediate tap without sleep |
| T2-BVA-11 | Hold Time | negative hold duration | `hold_duration_ms=-50` | Pydantic validation error (`ge=0`); rejected |
| T2-BVA-12 | Hold Time | very large hold duration | `hold_duration_ms=60000` | Rejected or clamped by safety limits |
| T2-BVA-13 | Invalid Enum | unknown movement | `movement="teleport"` | Pydantic validation error; rejected with valid options |
| T2-BVA-14 | Invalid Enum | unknown action | `action="super_laser"` | Pydantic validation error; rejected with valid options |
| T2-BVA-15 | Invalid Enum | unknown look direction | `look={"direction": "diagonal"}` | Pydantic validation error; rejected with valid options |
| T2-BVA-16 | Malformed | empty chord list | `chord=[]` | Handled cleanly as no-op or validation rejection |
| T2-BVA-17 | Malformed | chord with unknown key | `chord=["nonexistent_key_xyz"]` | Returns clear error describing unrecognized key token |
| T2-BVA-18 | Concurrency | rapid sequential commands | 10 rapid successive `game_control` calls | All 10 execute sequentially without deadlock or race |
| T2-BVA-19 | Concurrency | concurrent async calls | 5 parallel `asyncio.gather` tool executions | Registry handles or serializes safely without corruption |
| T2-BVA-20 | Cancellation | cancel before start | Cancel token pre-cancelled prior to tool call | Execution halts immediately without performing any actuation |
| T2-BVA-21 | Cancellation | cancel mid-sequence | Cancel triggered during step 2 of 5-step sequence | Steps 1-2 execute, steps 3-5 abort, all keys released |
| T2-BVA-22 | Cancellation | cancel after completion | Cancel triggered after sequence completes | Returns cleanly; no effect on completed action |
| T2-BVA-23 | Safety | blacklisted process focus | Target window is `cmd.exe` or `powershell.exe` | Action rejected with `SecurityViolationError` |
| T2-BVA-24 | Safety | out-of-bounds mouse | Click coordinates outside game window rect | Clamped to window boundary or rejected |
| T2-BVA-25 | Emergency | kill-switch combo | `Ctrl+Alt+Shift+Pause` triggered | Global emergency hook immediately severs all actuation |

---

### Tier 3: Cross-Feature Combinations (Pairwise Testing)

| Test ID | Primary Feature | Secondary Feature | Combination Description | Expected Observable Behavior |
|---------|-----------------|-------------------|-------------------------|------------------------------|
| T3-PRW-01 | Movement | Camera Look | Move forward while panning camera right | 'w' key held while relative mouse deltas `(dx=80, dy=0)` emitted |
| T3-PRW-02 | Movement | Movement | Sprint while jumping | 'shift' and 'space' actuated concurrently or in rapid succession |
| T3-PRW-03 | Chord | Interaction | Chord `["shift", "w"]` followed by primary action | Sprint forward maintained, primary action (click) triggered |
| T3-PRW-04 | Hotbar | Movement | Select slot 4 while strafing left | 'a' key held while slot key '4' tapped |
| T3-PRW-05 | Sequence | Movement + Look + Action | Compound sequence: forward -> look up -> primary action | Steps executed in exact order with configured hold durations |
| T3-PRW-06 | Camera Look | Interaction | Camera look down-left with secondary action (aim & interact) | Relative deltas `(-50, 50)` emitted followed by right click |
| T3-PRW-07 | Movement | Hotbar | Crouch while cycling hotbar slots 1 -> 2 -> 3 | 'ctrl' held continuously across slot selections |
| T3-PRW-08 | Auto-Startup | Dynamic Swap | Server boot default adapter -> swap -> swap back | State machine correctly transitions across adapter boundaries |

---

### Tier 4: Real-World Application Workloads

| Test ID | Scenario Name | Workflow Description | Expected Multi-Stage Outcome |
|---------|---------------|----------------------|------------------------------|
| T4-SCN-01 | First-Person Navigation | Sprint forward for 200ms, rotate camera 90 degrees right (`dx=150`), jump over obstacle | 'shift'+'w' pressed for 200ms -> smooth minimum-jerk camera deltas -> 'space' pressed -> all released |
| T4-SCN-02 | Tactical Combat Cycle | Strafe left (`'a'`), look down-left (`dx=-60, dy=40`), click primary action, reload (`'r'`), crouch (`'ctrl'`) | Discrete actuation of each tactical phase; verified key and mouse sequence; verified weapon reload |
| T4-SCN-03 | Inventory Interaction | Press menu (`'tab'`), select hotbar slot 3, primary action click at slot coordinates, close menu (`'tab'`) | Menu opened -> slot 3 activated -> click executed -> menu closed; verifies UI loop |
| T4-SCN-04 | Headless Exploration Loop | Continuous automated loop: 3 iterations of timed forward movement, randomized camera panning, and periodic jump | All iterations complete without memory leak or state accumulation; verified timing stability |
| T4-SCN-05 | Emergency Abort Mid-Sequence | Client requests cancellation during step 3 of a 10-step complex compound sequence | Cancellation token fires -> sequence halts immediately -> `release_all()` severs all keys within 10ms |

---

## 4. Test Runner and Execution Conventions

### Test Execution Commands
```powershell
# Run the complete E2E Game Control test suite
pytest -o pythonpath=src tests/test_game_control/test_e2e_game_control.py -v

# Run with test coverage metrics
pytest -o pythonpath=src --cov=gaming_mcp.adapters.computer_use --cov=gaming_mcp.schemas.game_control --cov=gaming_mcp.server tests/test_game_control/test_e2e_game_control.py

# Run specific tier tests using keyword filtering
pytest -o pythonpath=src tests/test_game_control/test_e2e_game_control.py -k "tier1"
pytest -o pythonpath=src tests/test_game_control/test_e2e_game_control.py -k "tier2"
pytest -o pythonpath=src tests/test_game_control/test_e2e_game_control.py -k "tier3"
pytest -o pythonpath=src tests/test_game_control/test_e2e_game_control.py -k "tier4"
```

### Static Analysis and Linting Verification
```powershell
# Strict static type checking
mypy src tests --strict

# Automated linting and style verification
ruff check src tests

# Unicode zero emoji verification
python -c "import pathlib, sys; from tests.test_distribution import check_no_emojis; p = pathlib.Path('tests/test_game_control'); bad = [(f, check_no_emojis(f.read_text(encoding='utf-8'))) for f in p.glob('*.py')]; errs = [x for x in bad if x[1]]; sys.exit(1 if errs else 0)"
```

---

## 5. Requirement Traceability Matrix

| Requirement | Description | Test Tier | Test Case IDs |
|-------------|-------------|-----------|---------------|
| R1 | Unified General Game Control Tool Interface | Tier 1, Tier 2, Tier 3 | T1-MOV-01..07, T1-LOK-01..07, T1-ACT-01..06, T1-SLT-01..05, T1-CHD-01..05, T1-SEQ-01..05, T2-BVA-01..17, T3-PRW-01..07 |
| R2 | Automatic Default Adapter Startup & Lifecycle | Tier 1, Tier 3 | T1-AUT-01..05, T1-DYN-01..05, T3-PRW-08 |
| R3 | Driver-Level Actuation with Emulation Fallback | Tier 1, Tier 2, Tier 4 | T1-FLB-01..05, T1-CAN-01..05, T2-BVA-08..09, T2-BVA-20..25, T4-SCN-01..05 |
| R4 | Protocol Safety, Cancellation & Zero Emojis | All Tiers | T1-CAN-01..05, T2-BVA-20..25, T4-SCN-05, all automated audits |
