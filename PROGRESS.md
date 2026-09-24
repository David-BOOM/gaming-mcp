# Gaming MCP Server -- Progress Ledger

This document tracks all completed engineering iterations, empirical evidence links, unexpected discoveries, and immediate next targets across the project lifecycle.

---

## Iteration 0 -- 2026-09-24: Autonomous Team Loop Setup and Foundation Anchors

* **Milestone / Focus:** Pre-Implementation Architectural Transition to Phase 1.
* **Deliverables Completed:**
  - Authored `GEMINI38-TEAM-LOOP-PROMPT.md`: Complete autonomous agent team loop (T2, L3) prompt custom-tailored for Gemini 3.8 Flash, featuring official Google Prompting Strategies (XML delimiters, proactive thinking directives, few-shot exemplars) and model card constraints (1M context, 64k max output, high thinking, zero emojis).
  - Authored `MEMORY.md`: Persistent knowledge base and error catalog capturing 8 concrete failure modes and proven replicable corrections (Win32 scan codes, ViGEmBus missing driver graceful advisory, DXGI access lost recovery, minimum-jerk trajectory splining, cancellation motor cleanup, stdio stdout hygiene, dHash ROI slicing, and Mineflayer NDJSON framing).
  - Authored `RESUME.md`: Instant cold-start pointer allowing incoming agents or resumed sessions to orient in seconds without parsing conversation transcripts.
  - Initialized `LOOP_STATE.json`: Machine-readable task DAG tracking all Phase 1-6 milestones and blockers.
* **Evidence:** Preflight Unicode scan verified 0 emoji infractions across all repository files.
* **Surprises & Lessons:** Gemini 3.8 Flash requires explicit thinking configuration (`low`, `medium`, `high`) and will throw an API error if `minimal` is requested. Prompt harness configuration explicitly locks thinking to `high` for orchestrator sessions.
* **Next Target:** Milestone 1.1a -- Author `pyproject.toml`, establish package scaffolding under `src/gaming_mcp/`, and initialize `server.py` entrypoint.

---

## Iteration 1 -- 2026-09-24: Subtask 1.1a -- Project Scaffolding, Core Exceptions, Configuration, and Test Suite

* **Milestone / Focus:** Milestone 1.1: MCP Protocol Engine (Subtask 1.1a: Scaffolding).
* **Deliverables Completed:**
  - `pyproject.toml`: Complete PEP 621 build configuration with Hatchling backend, dependency groups (gamepad, audio, ocr, minecraft, retro, turbo, dev), and strict Ruff/Mypy/Pytest configurations.
  - Package structure: `src/gaming_mcp/` with `core/`, `adapters/`, `io/`, `skills/`, and `utils/`.
  - `src/gaming_mcp/config.py`: Pydantic v2 schemas for `GamingMCPConfig`, `ScreenCaptureConfig`, `InputConfig`, `AudioConfig`, `SecurityConfig`, and `AdapterConfig` with layered loading (defaults, config.json, environment variables).
  - `src/gaming_mcp/core/exceptions.py`: Typed exception hierarchy (`GamingMCPError`, `AdapterError`, `AdapterNotFoundError`, `AdapterInitializationError`, `CaptureError`, `DXGICaptureError`, `InputInjectionError`, `SecurityViolationError`, `SafetyKillSwitchError`, `SkillExecutionError`, `ElicitationDeniedError`) with JSON-RPC error mapping.
  - `src/gaming_mcp/utils/logging.py`: Structured JSON logger writing strictly to `sys.stderr` to prevent stdio transport corruption.
  - `src/gaming_mcp/__main__.py`: CLI argument parser and execution harness.
  - `tests/test_scaffolding.py`: 10 automated unit tests verifying versions, configuration schemas, env overrides, CLI parsing, exception error codes, structured logging, and async entrypoint.
* **Evidence:**
  - `EVIDENCE/1.1a-scaffolding/pytest_coverage.txt`: 10/10 tests passing with 90% overall coverage and 100% coverage on `core/exceptions.py`.
  - Ruff check: 0 warnings, all formatting clean.
  - Mypy: 0 errors across 13 source files with strict type checking.
  - Unicode zero-emoji audit: 0 infractions across repository.
* **Surprises & Lessons:**
  - In Python 3.12 with modern numpy stubs, Mypy requires `python_version = "3.12"` in `pyproject.toml` to parse PEP 695 type aliases.
  - `TransportType` derives from `StrEnum` rather than `(str, Enum)` per modern Python 3.11+ conventions (UP042).
* **Next Target:** Milestone 1.1b -- Implement `src/gaming_mcp/server.py` with standard JSON-RPC 2.0 lifecycle handlers and transports (stdio, SSE).

---

## Iteration 2 -- 2026-09-24: Milestone 1.1 Completion and Milestone 1.2 Adapter SPI & Router Architecture

* **Milestone / Focus:** Milestone 1.1 (MCP Protocol Engine) and Milestone 1.2 (Adapter SPI & Router Architecture). Phase 1 Exit Gate achieved.
* **Deliverables Completed:**
  - `src/gaming_mcp/core/cancellation.py`: `CancellationManager` with active task registration, `notifications/cancelled` listening, and immediate motor safety release callbacks.
  - `src/gaming_mcp/core/registries.py`: `ToolRegistry`, `ResourceRegistry`, and `PromptRegistry` with strict Pydantic v2 argument validation, error envelopes, and subscription tracking.
  - `src/gaming_mcp/server.py`: `GamingMCPServer` wrapping official MCP SDK 2.x `MCPServer`, built-in `server_health`, `ping`, `switch_adapter` tools, `system://server/health` resource, and stdio/SSE/streamable-HTTP transport dispatch.
  - `src/gaming_mcp/adapters/base.py`: `GameAdapter` abstract SPI and `AdapterMetadata` Pydantic model with asynchronous lifecycle (`initialize`, `shutdown`, `register_tools`, `register_resources`, `register_prompts`, `health_check`).
  - `src/gaming_mcp/adapters/router.py`: `AdapterRouter` for dynamic adapter hot-swapping at runtime without dropping client connection, tracking bound tools/resources/prompts.
  - `tests/test_cancellation.py`: 3 unit tests verifying task tracking, cancellation propagation, and emergency motor reset.
  - `tests/test_registries.py`: 5 unit tests verifying tool schemas, validation errors, resource reads (JSON, bytes/blob), subscriptions, and prompt rendering.
  - `tests/test_server.py`: 6 unit tests verifying server lifecycle, health metrics, process RSS memory, shutdown motor reset, and transport runners.
  - `tests/test_adapters/test_router.py`: 6 unit tests verifying adapter registration, listing, hot-swap tool rebinding, missing adapter error handling, and aggregated health checks.
* **Evidence:**
  - `EVIDENCE/1.1-mcp-engine/pytest_coverage.txt` and `EVIDENCE/1.2-adapter-spi/pytest_coverage.txt`: 30/30 unit tests passing cleanly with 93% total coverage.
  - Core coverage: 97.6% (100% on `core/exceptions.py`, 98% on `core/cancellation.py`, 95% on `core/registries.py`).
  - Adapters coverage: 97.3% (100% on `adapters/base.py`, 92% on `adapters/router.py`).
  - Ruff check: 0 errors/warnings across 23 source files.
  - Mypy: 0 errors under `--strict`.
  - Zero-emoji audit: 0 infractions across repository.
* **Surprises & Lessons:**
  - In `mcp` 2.x, `MCPServer.remove_prompt` throws `ValueError` if the prompt was not registered in its internal manager; adapter unbinding must suppress non-critical cleanup errors.
  - Tool execution results must explicitly include `"isError": False` for successful custom dictionary payloads to ensure MCP schema consistency.
* **Next Target:** Milestone 2.1 -- Universal VLA Computer Use Engine: DXGI Desktop Duplication ctypes wrapper and MSS fallback capturer under `src/gaming_mcp/io/screen.py`.

---

## Iteration 3 -- 2026-09-25: Milestone 2.1 Hardware-Accelerated Display and Audio Capture

* **Milestone / Focus:** Phase 2 Milestone 2.1: Hardware-Accelerated Display and Audio Capture.
* **Deliverables Completed:**
  - `src/gaming_mcp/io/screen.py`: `DXGIScreenCapturer` utilizing Direct3D 11 and DXGI 1.2 Desktop Duplication via ctypes with staging texture caching, `MSSScreenCapturer` cross-platform fallback, and `CompositeScreenCapturer` with access-loss recovery.
  - Dedicated worker thread pool (`get_screen_executor`) in `screen.py`: Isolates desktop capture operations from main thread COM apartments, preventing Win32 `ERROR_BUSY` (170) on `SetThreadDesktop`.
  - `src/gaming_mcp/io/audio.py`: `WASAPIAudioCapturer` with non-blocking PCM ring buffering, RMS energy calculation, peak decibels relative to full scale (dBFS), tactical sound cue detection, and STFT magnitude spectrograms.
  - `src/gaming_mcp/io/vision.py`: `PerceptualGater` with 64-bit dHash perceptual gating, Hamming distance thresholding (<3 suppressing redundant frames), and HUD exclusion zone masking.
  - `src/gaming_mcp/utils/image.py`: ACES filmic HDR-to-SDR tone-mapping, Set-of-Marks alphanumeric coordinate grid overlay, and high-performance JPEG/PNG base64 serialization.
  - `tests/test_io/`: 17 new automated tests across `test_screen.py`, `test_audio.py`, `test_image.py`, and `test_vision.py`.
* **Evidence:**
  - `EVIDENCE/2.1-display-audio/pytest_coverage.txt`: 47/47 unit tests passing cleanly with 89% total coverage across 1221 statements.
  - `screen.py` coverage: 86%, `audio.py` coverage: 81%, `vision.py` coverage: 89%, `image.py` coverage: 88%.
  - `EVIDENCE/2.1-display-audio/ruff_check.txt`: 0 lint errors across all source files.
  - `EVIDENCE/2.1-display-audio/mypy_check.txt`: 0 type errors under `--strict`.
  - `EVIDENCE/2.1-display-audio/emoji_audit.txt`: 0 emoji code points verified across entire repository.
* **Surprises & Lessons:**
  - `sounddevice` / PortAudio DLL initializes hidden window/COM message hooks on the importing thread, which causes subsequent `SetThreadDesktop` calls on that thread to fail with Win32 error 170 (`ERROR_BUSY`). Running screen capture in a dedicated single-threaded worker executor (`get_screen_executor()`) completely isolates the capture pipeline and guarantees 100% reliable desktop attachment.
  - Verified `IDXGIOutput1::DuplicateOutput` at vtable index 22, acquiring full 2880x1800 retina frames in ~15ms on CPU staging buffers.
* **Next Target:** Milestone 2.2 -- Dual-Layer Actuation and Action Chunking (Subtask 2.2a: Win32 SendInput PS/2 hardware scan codes and trajectory splining).

---

## Iteration 4 -- 2026-09-25: Milestone 2.2 Dual-Layer Actuation and Action Chunking

* **Milestone / Focus:** Phase 2 Milestone 2.2: Dual-Layer Actuation and Action Chunking.
* **Deliverables Completed:**
  - `src/gaming_mcp/io/input.py`: `Win32InputInjector` implementing native Win32 `SendInput` with PS/2 Set 1 hardware scan codes (`KEYEVENTF_SCANCODE`, `KEYEVENTF_EXTENDEDKEY`), Gaussian keypress hold duration jitter (mean = 55ms, std = 6ms), relative mouse motions for 3D camera controls (`MOUSEEVENTF_MOVE`), absolute and smooth cursor navigation, and motor safety reset (`release_all()`).
  - Dedicated input worker executor (`get_input_executor`) in `input.py`: Isolates SendInput and SetThreadDesktop calls from audio/multimedia libraries (such as sounddevice/PortAudio) that initialize hidden COM message hooks, ensuring 0 errors on desktop attachment.
  - `src/gaming_mcp/io/gamepad.py`: `BaseGamepadController` abstract SPI and `ViGEmGamepadController` with guarded capability probe per MEMORY.md Case 2. If ViGEmBus kernel driver or vgamepad module is absent, gracefully raises typed `AdapterError` (-32002) with advisory setup instructions without crashing server startup. Included `MockGamepadController` for deterministic simulation.
  - `src/gaming_mcp/utils/curves.py`: Flash & Hogan (1985) minimum-jerk trajectory polynomials ($s(u) = 10u^3 - 15u^4 + 6u^5$), Fitts' Law duration estimation ($T = a + b \log_2(1 + D/W)$), cubic Bezier trajectory splining with perpendicular control point arcs, and smooth relative 3D camera turn delta generators.
  - `src/gaming_mcp/io/timing.py`: `ActionChunkScheduler` executing compound microsecond action chunks (`ActionChunk`, `ActionChunkItem`) locally to overcome cloud inference latency, with fine-grained spin wait and sub-10ms motor safety release on MCP cancellation tokens.
  - Test suites: 22 new unit and integration tests across `test_curves.py`, `test_input.py`, `test_gamepad.py`, and `test_timing.py`.
* **Evidence:**
  - `EVIDENCE/2.2-actuation-chunks/pytest_coverage.txt`: 69/69 tests passing cleanly with 89% total coverage across 1890 statements.
  - `curves.py` coverage: 98%, `gamepad.py` coverage: 92%, `input.py` coverage: 84%, `timing.py` coverage: 81%.
  - `EVIDENCE/2.2-actuation-chunks/ruff_check.txt`: 0 errors/warnings across 40 source files.
  - `EVIDENCE/2.2-actuation-chunks/mypy_check.txt`: 0 type errors under `--strict`.
  - `EVIDENCE/2.2-actuation-chunks/emoji_audit.txt`: 0 emoji code points verified across entire repository.
* **Surprises & Lessons:**
  - `SendInput` returned Win32 error 5 (`ERROR_ACCESS_DENIED`) when run in the test suite after `test_audio.py` because `sounddevice` initialized hidden COM windows on the main thread, blocking subsequent `SetThreadDesktop` with Win32 error 170 (`ERROR_BUSY`). By routing `SendInput` through a dedicated worker thread (`get_input_executor()`), input operations are completely isolated and succeed 100% reliably.
* **Next Target:** Milestone 2.3 -- Visual Grounding, Safety and Privacy (Subtask 2.3a: Set-of-Marks coordinate grid overlay, Subtask 2.3b: Window rect clipping and process blacklist, Subtask 2.3c: Emergency hardware kill-switch).



