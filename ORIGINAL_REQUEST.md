# Original User Request

## 2026-09-24T09:26:21Z

Please launch multiple agents in an agent team to speed up the process of implementing and verifying the Gaming MCP Server (gaming-mcp) according to implementation_plan.md and GEMINI38-TEAM-LOOP-PROMPT.md.

Working directory: c:\Users\david\Desktop\Projects\gaming-mcp
Integrity mode: development

## Requirements

### R1. Core Foundation & Protocol Dispatcher (Phase 1)
Implement the core MCP protocol engine supporting JSON-RPC 2.0 lifecycle (`initialize`, `initialized`, `shutdown`, `ping`), dual transports (`stdio` for Claude Desktop / Cursor and `SSE/HTTP` via Starlette/Uvicorn), typed registries (`ToolRegistry`, `ResourceRegistry`, `PromptRegistry`) with strict Pydantic v2 schemas, cancellation tokens listening for `notifications/cancelled` with immediate motor safety release, and progress tokens via `notifications/progress`.

### R2. Adapter SPI & Router Architecture (Phase 1.2)
Implement the abstract `GameAdapter` Service Provider Interface (SPI) with asynchronous initialization, shutdown, tool registration, resource subscription, and health check hooks. Implement dynamic adapter routing allowing runtime switching between adapters without disconnecting the client.

### R3. Universal VLA Computer Use Engine (Phase 2)
Implement hardware-accelerated screen capture (DXGI Desktop Duplication ctypes wrapper with ACES tone-mapping, falling back to MSS), 64-bit dHash perceptual delta gating (<2.5% variation suppresses image transmission), WASAPI loopback audio event detector, Win32 PS/2 Set 1 hardware scan-code keyboard injection, ViGEmBus virtual Xbox 360 controller emulation, minimum-jerk polynomial mouse trajectory splining, Set-of-Marks coordinate grid overlays, window boundary clipping, process blacklisting, and global emergency hardware kill-switch (`Ctrl+Alt+Shift+Pause`).

### R4. Game Adapters, Skill Memory & Benchmarks (Phases 3 to 6)
Implement the Node.js Mineflayer NDJSON IPC bridge for Minecraft Java Edition, Libretro/Gymnasium emulator wrappers, Voyager-style SQLite vector macro store with semantic retrieval and self-repair execution loops, and the 4-tier game evaluation benchmark matrix.

### R5. Non-Negotiable Invariants and Zero Emojis Policy
1. Absolute Zero Emojis: Strictly 0 emoji or pictogram characters anywhere in source code, docstrings, plans, task files, commit messages, or test outputs.
2. Full static type safety with Mypy (`--strict`) and clean Ruff linting.
3. Automated test suites targeting >95% coverage on core protocol modules.
4. Conventional Commits for all logical slices.

## Verification Resources

The repository contains established verification fixtures and scripts:
- Pre-commit zero-emoji validator script.
- Ruff and Mypy configurations in `pyproject.toml`.
- Pytest suite under `tests/` with coverage reporting.
- Canonical state files: `LOOP_STATE.json`, `RESUME.md`, `MEMORY.md`, and `PROGRESS.md`.

## Acceptance Criteria

### Static Quality and Type Safety
- [ ] `ruff check src tests` reports 0 errors and 0 warnings.
- [ ] `mypy src tests` passes with 0 type errors under `--strict`.
- [ ] Zero emoji verification script confirms 0 Unicode emoji code points across all repository files.

### Protocol and Engine Conformance
- [ ] JSON-RPC 2.0 handshake completes cleanly over stdio and SSE transports.
- [ ] Tool execution respects input validation schemas and translates exceptions into standard MCP error envelopes.
- [ ] Aborting a long-running action chunk via `notifications/cancelled` releases all held keys within 10ms.
- [ ] Test coverage exceeds 95% on `src/gaming_mcp/core/`.

### Actuation and Safety Guardrails
- [ ] Keyboard input injects PS/2 Set 1 hardware scan codes (`KEYEVENTF_SCANCODE`).
- [ ] Virtual gamepad operations gracefully degrade with advisory `AdapterError` (-32002) if ViGEmBus driver is absent.
- [ ] Window clipping prevents mouse actuation outside the targeted game window rect.
- [ ] Process blacklist refuses input injection into `cmd.exe`, `powershell.exe`, `Taskmgr.exe`, and sensitive OS utilities.
- [ ] Emergency kill-switch severs all held inputs immediately when triggered.

## 2026-09-24T15:36:58Z

Implement Phase 2 Milestone 2.1 of the Gaming MCP Server: Hardware-Accelerated Display and Audio Capture, providing low-latency DXGI screen acquisition, MSS fallback, 64-bit dHash perceptual gating, and WASAPI master loopback audio capture for AI game agents.

Working directory: c:\Users\david\Desktop\Projects\gaming-mcp
Integrity mode: development

Requested team: Agent team for Phase 2 Milestone 2.1 (Hardware-Accelerated Display and Audio Capture)

## Requirements

### R1. Screen Capture Engine with Native DXGI Duplication and MSS Fallback
Implement `src/gaming_mcp/io/screen.py` containing:
- `DXGIScreenCapturer`: ctypes-based Windows DirectX 11 / DXGI Desktop Duplication wrapper acquiring desktop frames with low latency (<15ms target) and ACES filmic HDR-to-SDR tone-mapping.
- `MSSScreenCapturer`: High-speed multi-monitor cross-platform fallback capturer with target window handle (`HWND`) coordinate clipping and cropping.
- `CompositeScreenCapturer`: High-level capturer that prioritizes DXGI on Windows, intercepts `DXGI_ERROR_ACCESS_LOST` (0x887A0026) with automatic re-acquisition and seamless fallback to MSS without dropping frames.
- Integrated perceptual delta gating using `PerceptualGater` (`src/gaming_mcp/io/vision.py`) and image serialization via `encode_image` (`src/gaming_mcp/utils/image.py`).

### R2. WASAPI Loopback Audio Capture Engine
Implement `src/gaming_mcp/io/audio.py` containing:
- `WASAPIAudioCapturer`: Audio capture worker utilizing `sounddevice` with WASAPI loopback mode to stream master system/game audio.
- Audio feature extraction computing RMS energy levels, peak decibel metrics, and tactical cue detection (e.g., silence thresholding vs. active audio transients).
- Graceful degradation returning clear advisory status if no default output device or WASAPI loopback stream is active.

### R3. Comprehensive Automated Verification Suite
Implement `tests/test_io/test_screen.py` and `tests/test_io/test_audio.py` containing:
- Unit and mock tests for DXGI ctypes initialization, buffer memory layout, and error recovery on lost device surface.
- Runtime tests for MSS capture, window cropping, and Set-of-Marks grid overlays.
- Perceptual dHash verification tests verifying that static scenes yield Hamming distance < 3 and animated changes yield Hamming distance >= 3.
- WASAPI loopback capture unit and mock stream tests.
- 100% pass rate under `pytest`, zero warnings in `ruff check`, and zero type errors in `mypy --strict`.

## Acceptance Criteria

### Correctness and Protocol Safety
- [ ] `DXGIScreenCapturer` correctly initializes Direct3D 11 device and output duplication interface via ctypes, handling surface acquisition cleanly.
- [ ] If DXGI is unavailable or encounters access loss, `CompositeScreenCapturer` falls back to `MSSScreenCapturer` without throwing uncaught exceptions.
- [ ] `compute_dhash` and `PerceptualGater` accurately suppress redundant static frames when Hamming distance is below the configured threshold.
- [ ] `WASAPIAudioCapturer` records PCM buffers and computes audio energy levels without blocking the asyncio event loop.
- [ ] Emergency cleanup: all COM interfaces and audio streams are explicitly closed on `close()` / shutdown.

### Quality and Verification Standards
- [ ] All unit and integration tests in `tests/test_io/` pass cleanly with pytest.
- [ ] Strict type checking passes with 0 errors via `mypy src/ tests/ --strict`.
- [ ] Linting and code style passes with 0 issues via `ruff check src/ tests/`.
- [ ] Strictly zero emoji or pictogram characters in all source files, docstrings, and tests (AGENTS.md Rule 1).

## 2026-09-25T15:47:24Z

Plan and implement a universal, game-agnostic control function and automatic adapter startup for gaming-mcp that operates seamlessly across any video game without game-specific customization.

Working directory: c:\Users\david\Desktop\Projects\gaming-mcp
Integrity mode: development

## Requirements

### R1. Unified General Game Control Tool Interface
Provide a unified, high-level `game_control` tool exposed to MCP clients that accepts and executes general game commands across any game: directional movement (`forward`, `backward`, `strafe_left`, `strafe_right`, `jump`, `sprint`, `crouch`), camera/look rotation (`look_up`, `look_down`, `look_left`, `look_right`, relative mouse deltas `dx`/`dy`, and yaw/pitch angles), common game interactions (`primary_action`, `secondary_action`, `interact`, `reload`, `pause`, `menu`), hotbar/slot selection, custom key/button chords, and compound multi-step action sequences.

### R2. Automatic Default Adapter Lifecycle and Registration
Ensure the MCP server automatically initializes and activates the universal game control adapter upon server startup, exposing the universal game control tools out of the box to any connecting MCP client without requiring manual `switch_adapter` tool calls, while maintaining dynamic hot-swapping and graceful shutdown.

### R3. Driver-Level Actuation with Robust Emulation Fallback
Execute inputs through low-level hardware scan codes (`KEYEVENTF_SCANCODE`) and ViGEmBus virtual gamepad actuation with minimum-jerk trajectory smoothing, while falling back gracefully to mock/software injection when physical controllers or kernel drivers are absent in headless environments.

### R4. Multi-Agent Git Branching and Clean Merge Discipline
Develop on dedicated git feature branches (`feature/general-game-control`), making incremental commits after each significant step, running pre-commit zero-emoji verification, passing all test suites, and performing clean git merges back into `main` with immediate remote pushes.

## Acceptance Criteria

### MCP Protocol Conformance and Tool Surface
- [ ] The `game_control` tool is registered and visible in `tools/list` on server startup without manual adapter activation.
- [ ] Pydantic v2 input schemas strictly validate all parameters with descriptive field documentation and range bounds.
- [ ] Cancellation notifications (`notifications/cancelled`) promptly abort running action sequences and release active inputs.

### Actuation Fidelity and Generality
- [ ] Movement actions correctly trigger continuous or discrete key presses with configurable hold durations.
- [ ] Camera look actions support both relative pixel deltas and angular rotations with smooth interpolation.
- [ ] Action sequences execute compound timed steps in sequence with sub-millisecond precision.
- [ ] Window targeting and safety guards (boundary clamping, blacklisted processes, emergency kill-switch) remain enforced.

### Test Verification and Zero Emojis
- [ ] Complete test suite passes with 100% test success rate in pytest.
- [ ] Pre-commit verification script confirms exactly 0 emoji or pictogram Unicode infractions repository-wide.
- [ ] Git feature branch cleanly merged into `main` and pushed to remote origin.

## 2026-09-26T07:05:40Z

The environment was restarted. Milestone 1 implementation (commit a229e86: minimum-jerk smooth camera look, fallback_to_mock gamepad support, and pre-flight fixes) has been verified and pushed to origin/feature/general-game-control. Please resume the project orchestrator and active workers, complete the Milestone 1 Verification Gate, and proceed with Milestone 2 (Universal game_control tool interface) and Milestone 3 (automatic default adapter startup lifecycle). Invariants remain: strictly zero emojis, 100% test pass rate, and conventional commits.

