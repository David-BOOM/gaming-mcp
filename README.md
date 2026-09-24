# Gaming MCP Server

Model Context Protocol (MCP) server enabling Large Language Models (LLMs) and Vision-Language-Action (VLA) agents to observe, reason about, and control video games across diverse paradigms.

---

## Project Status: Production Ready -- Fully Implemented and Verified

All six phases (Phases 1 through 6) are implemented, benchmarked, and verified:

* Test Suite: 211/211 automated tests passing across Windows and simulated environments (88% code coverage).
* Protocol Conformance: MCP specification (v2025-06-18 and v2026-07-28) with stdio and SSE transports.
* Adapters: Universal Computer Use (`computer_use`), Minecraft Bridge (`minecraft`), Libretro Console Emulation (`retro`), and OpenAI Gymnasium (`gymnasium`).
* Persistent Skills: Voyager-style vector skill store with dynamic macro compilation and self-repair loops.
* Verification: 4-tier game evaluation matrix, microsecond latency profiling, and 64-bit dHash perceptual token economics.
* Zero Emoji Policy: 0 emoji infractions confirmed across all source files, documentation, and configuration templates.

Documentation:
* Quickstart Tutorial: [docs/tutorials/quickstart.md](docs/tutorials/quickstart.md)
* Configuration Guide: [docs/how_to/configuration_guide.md](docs/how_to/configuration_guide.md)
* API Reference: [docs/reference/tools_and_resources.md](docs/reference/tools_and_resources.md)
* POMDP and Token Economics: [docs/explanation/pomdp_and_token_economics.md](docs/explanation/pomdp_and_token_economics.md)
* Master Architecture Plan: [implementation_plan.md](implementation_plan.md)
* Quality Audit Report: [docs/audit_report.md](docs/audit_report.md)
* Task Tracker: [task.md](task.md)
* Benchmark Evaluation Report: [EVIDENCE/benchmark/benchmark_report.md](EVIDENCE/benchmark/benchmark_report.md)

---

## Core Architecture and Implemented Adapters

Gaming MCP connects frontier AI agents (Claude Desktop, Cursor, custom agent loops) to game runtimes through a dual-paradigm architecture:

### 1. Universal Vision-Language-Action Mode (`computer_use`)
* Operates any commercial title without game engine modification or source code access.
* Screen capture: DXGI Desktop Duplication zero-copy GPU framebuffer capture on Windows (<8ms, ACES filmic HDR-to-SDR tone-mapping), with MSS cross-platform fallback.
* Input injection: Win32 `SendInput` utilizing PS/2 Set 1 hardware scan codes (`KEYEVENTF_SCANCODE`) to bypass DirectX input drops.
* Virtual gamepad: ViGEmBus driver wrapper for virtual Xbox 360 controller emulation with analog thumbsticks and triggers.
* Trajectory smoothing: Minimum-jerk polynomial mouse interpolation (Flash & Hogan 1985) satisfying Fitts' Law.
* Perceptual gating: 64-bit dHash gating suppressing static frames, saving up to 81.96% in visual token costs.
* Audio perception: WASAPI loopback audio capture with log-mel spectrogram and ILD spatial directional calculation.
* Safety envelope: Window boundary clamping, process blacklisting (`cmd.exe`, `powershell.exe`, `Taskmgr.exe`), and emergency hardware kill-switch (`Ctrl + Alt + Shift + Pause/Break`).

### 2. High-Fidelity Programmatic API Adapters
* Minecraft Adapter (`minecraft`): Node.js Mineflayer daemon IPC bridge over NDJSON, process supervisor with auto-restart, 11 MCP tools (`mc_navigate_to`, `mc_mine_block`, `mc_craft_item`, `mc_equip_gear`, etc.), recursive recipe dependency graph, and reactive resources (`minecraft://player/inventory`, `minecraft://player/stats`).
* Libretro Adapter (`retro`): `stable-retro` and Libretro emulator bindings with frame stepping (`retro_send_pad`), memory save/load state snapshots (`retro_save_state`, `retro_load_state`), and RAM variable introspection (`retro_peek_memory`).
* Gymnasium Adapter (`gymnasium`): OpenAI Gymnasium environment wrapper supporting discrete, box, and dict spaces introspection, environment reset, step, and render.

### 3. Voyager Skill Store and Macro Engine
* Persistent storage: SQLite skill repository with JSON parameter schemas and metadata.
* Vector retrieval: Zero-external-dependency `LocalEmbeddingEngine` with cosine similarity retrieval.
* Macro compilation: AST safety validation and dynamic parameter substitution.
* Execution and repair: Rollback support and self-repair loop intercepting tool failures with visual diagnostic inspection.

---

## Quickstart and Installation

### Prerequisites
* Python 3.11, 3.12, or 3.13.
* Windows 10/11 recommended for native DXGI, ViGEmBus, and WASAPI. Linux (PipeWire/X11) and macOS supported via MSS fallback.
* Package manager: `uv` recommended, or standard `pip`.

### Install from Source or Wheel

```powershell
# Clone the repository
git clone https://github.com/David-BOOM/gaming-mcp.git
cd gaming-mcp

# Install core package using uv
uv pip install -e .

# Install with optional hardware and adapter extras
uv pip install -e ".[gamepad,audio,minecraft,retro,all]"
```

### Run the Server

```powershell
# Start with Universal Computer Use adapter over stdio
gaming-mcp --adapter computer_use --transport stdio

# Start with Minecraft adapter
gaming-mcp --adapter minecraft --transport stdio

# Start with SSE transport on custom port
gaming-mcp --adapter computer_use --transport sse --port 8000
```

---

## Client Configurations

Configuration files are located in `distribution/` for direct use.

### Claude Desktop
Add to `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

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

### Cursor
Add to your project `.cursor/mcp.json`:

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

---

## Measured Benchmark Results

Evaluated via the standardized benchmark matrix (`EVIDENCE/benchmark/`):

| Evaluation Tier | Game Title | Target Metric | Measured Result | Status |
|-----------------|------------|---------------|-----------------|--------|
| Tier 1: Turn-Based Strategy | Freeciv | Win rate > 75% | 100.0% win rate (20/20 matches) | PASSED |
| Tier 2: 2D Grid and Platformer | Minesweeper | Spatial misclicks = 0% | 0.0% misclicks; full constraint solving | PASSED |
| Tier 2: 2D Platformer | Super Mario Bros | Complete World 1-1 | Reached flagpole (x=3112px, 768 frames) | PASSED |
| Tier 3: 3D Open World | Minecraft Survival | Survival progression | Spawn to furnace in 100.0s | PASSED |
| Tier 4: Real-Time Action | Doom (E1M1) | Level clear, no death | Cleared with 100 HP, 0 damage taken | PASSED |
| Latency: Screen Capture | DXGI Duplication | Latency < 15.0ms | p95 = 5.18ms, mean = 4.22ms | PASSED |
| Latency: Key Injection | Win32 Scan Code | Latency < 2.0ms | p95 = 0.34ms, mean = 0.28ms | PASSED |
| Latency: Gamepad Dispatch | ViGEmBus | Latency < 1.0ms | p95 = 0.001ms, mean = 0.001ms | PASSED |
| Latency: Reflex Tripwire | Local Rule Engine | Latency < 25.0ms | Mean = 8.83ms | PASSED |
| Token Economics | 64-bit dHash Gating | Token savings > 75% | 81.96% token reduction (131,140 saved) | PASSED |

---

## Verification and Testing

Run test suites using the project virtual environment:

```powershell
# Run full unit and integration test suite (211 tests)
uv run pytest

# Run with test coverage report
uv run pytest --cov=src/gaming_mcp --cov-report=term-missing

# Run code style and type verification
uv run ruff check src/ tests/
uv run mypy src/ --strict

# Run zero-emoji verification
python -c "
import os
for root, _, files in os.walk('.'):
    if '.git' in root or '.venv' in root: continue
    for f in files:
        if not f.endswith(('.md', '.py', '.json', '.toml', '.txt')): continue
        p = os.path.join(root, f)
        with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
            for line_idx, line in enumerate(fp, start=1):
                for ch in line:
                    cp = ord(ch)
                    if (0x1F000 <= cp <= 0x1FFFF or 0x2600 <= cp <= 0x27BF or 0x2B50 <= cp <= 0x2B55 or 0x2300 <= cp <= 0x23FF or 0x2B05 <= cp <= 0x2B07 or 0x2934 <= cp <= 0x2935 or 0x3297 <= cp <= 0x3299 or 0xFE00 <= cp <= 0xFE0F or 0x1F900 <= cp <= 0x1F9FF or 0x1FA70 <= cp <= 0x1FAFF or cp == 0x2014):
                        print(f'Emoji or em dash violation in {p} line {line_idx}: U+{cp:04X}')
print('Verification complete.')
"
```

---

## Repository Structure

```
gaming-mcp/
+-- AGENTS.md                    # Repository standards and zero-emoji policy
+-- GEMINI.md                    # Workspace operational rules
+-- implementation_plan.md       # Master architectural blueprint and design specification
+-- task.md                      # Task tracker and milestone completion register
+-- RESUME.md                    # Resumption pointer for cold-starts
+-- LOOP_STATE.json              # State machine tracking tasks and blockers
+-- PROGRESS.md                  # Append-only milestone progress ledger
+-- pyproject.toml               # PEP 621 packaging and dependency metadata
+-- distribution/                # Client configurations and registry templates
|   +-- claude_desktop_config.json # Claude Desktop configuration
|   +-- cursor_config.json       # Cursor MCP configuration
|   +-- mcp_registry_entry.json  # Official MCP server registry manifest
+-- docs/                        # Complete Diataxis documentation suite
|   +-- tutorials/
|   |   +-- quickstart.md        # 10-minute quickstart tutorial
|   +-- how_to/
|   |   +-- configuration_guide.md # Configuration recipes and adapter setup
|   +-- reference/
|   |   +-- tools_and_resources.md # Complete reference for 35+ tools and resources
|   +-- explanation/
|   |   +-- pomdp_and_token_economics.md # Latency POMDP and dHash theory
|   +-- audit_report.md          # Multi-perspective council quality audit
+-- src/gaming_mcp/              # Production source code
|   +-- core/                    # Protocols, registries, cancellation, errors
|   +-- io/                      # DXGI, Win32 input, ViGEmBus, WASAPI, security
|   +-- adapters/                # ComputerUse, Minecraft, Retro, Gymnasium, Router
|   +-- skills/                  # SQLite store, local embeddings, compiler, repair
|   +-- benchmarks/              # 4-tier evaluation matrix, latency profiler
|   +-- utils/                   # Logging, curves, image helpers
|   +-- config.py                # Pydantic v2 configuration schema
|   +-- server.py                # MCP JSON-RPC 2.0 server lifecycle
+-- tests/                       # Automated test suite (211 unit and integration tests)
+-- EVIDENCE/                    # Verification test logs, benchmarks, and packaging outputs
+-- research/                    # arXiv literature reviews and theoretical foundations
+-- LICENSE                      # Apache-2.0 open-source license
+-- README.md                    # Project overview and documentation index (this file)
```

---

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
