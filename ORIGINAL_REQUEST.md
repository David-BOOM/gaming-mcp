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
