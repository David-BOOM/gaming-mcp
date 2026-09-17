# Gaming MCP Server

An extensible, enterprise-grade Model Context Protocol (MCP) server project designed to enable frontier Large Language Models (LLMs) and Vision-Language-Action (VLA) agents to autonomously observe, reason about, and control video games across diverse paradigms.

---

## Project Status: Planning and Architectural Design Phase

This repository is currently in the formal architectural design, research synthesis, and planning phase. Detailed engineering specifications, theoretical formulations, multi-perspective audits, and benchmark criteria have been established.

* Master Implementation Plan: See [implementation_plan.md](implementation_plan.md) or [docs/implementation_plan.md](docs/implementation_plan.md)
* Multi-Perspective Quality Audit: See [docs/audit_report.md](docs/audit_report.md)
* Research Summaries: See [research/arxiv/arxiv_game_agents_summary.md](research/arxiv/arxiv_game_agents_summary.md)

---

## Overview & Core Concepts

Gaming MCP bridges the gap between frontier AI agents (such as Claude Desktop, Cursor, and custom autonomous agent runtimes) and video game environments. It standardizes game interactions through the official Model Context Protocol (MCP) using a dual-paradigm architecture:

### 1. Universal Vision-Language-Action (Computer Use Mode)
* Agnostic to game engine, platform, or source code availability.
* Directly operates any commercial title via hardware-accelerated screen capture and driver-level input emulation.
* Functions across full-screen 3D DirectX/Vulkan games, retro emulators, and desktop windowed applications.

### 2. Deterministic High-Fidelity API Mode
* Programmatic integration for titles with modding APIs, headless interfaces, or emulator bindings.
* Eliminates perceptual visual hallucination by exposing structured JSON game state (e.g., player inventory, 3D voxel coordinates, entity lists, RAM variables).
* Initial adapters planned for Minecraft (via Node.js Mineflayer IPC), Libretro/RetroArch (console emulation), and OpenAI Gymnasium (reinforcement learning environments).

---

## Research Foundations & Theoretical Basis

The system architecture synthesizes breakthroughs from frontier AI laboratories and peer-reviewed academic literature:

* Google DeepMind:
  * SIMA (Scalable Instructable Multiworld Agent, 2024): Non-privileged RGB pixel input and HID keyboard/mouse actuation across diverse 3D commercial games.
  * Genie (Generative Interactive Environments, 2024): Foundation world models learning latent action spaces from video.
* Anthropic:
  * Claude Computer Use API: Native protocol standard for GUI coordinate spaces, mouse clicks, drags, and discrete keyboard scan codes.
* OpenAI:
  * Voyager (2023): Embodied lifelong learning in Minecraft featuring iterative prompting, self-verification, and a vector-indexed composite skill library.
  * Computer-Using Agent (CUA, 2025): Hybrid visual grounding combining screenshots with window metadata to minimize spatial misclicks.
* Meta:
  * Project CICERO (2022): Strategic reasoning and natural language negotiation in Diplomacy.
* Academic Consortia:
  * BAAI Cradle (2024): General computer control framework successfully playing complex 3D titles (Red Dead Redemption 2) without internal memory access.
  * Ghost in the Minecraft (GITM, 2023): Mapping text goals to low-level motor primitives.
  * Microsoft SmartPlay (2024): Standardized benchmark evaluating spatial reasoning, math, and planning in game environments.

---

## Key Architectural Highlights

### 1. Latency-Lagged POMDP & Action Chunking
To bridge the temporal disparity between 60 Hz game loops (16.6ms physics ticks) and cloud LLM inference delays (500ms to 2,500ms), the server implements:
* Hierarchical Action Chunking: The LLM issues parameterized temporal action trajectories rather than single atomic taps.
* Minimum-Jerk Trajectory Splining: Continuous mouse interpolation satisfying Fitts' Law to produce natural, human-like motion.
* Programmable Reflex Tripwires: Client-side conditional triggers that execute emergency responses locally without waiting for cloud round-trips.

### 2. Hardware Acceleration & Low-Level Drivers
* DXGI Desktop Duplication: Direct GPU zero-copy framebuffer capture on Windows with sub-8ms latency and ACES filmic HDR-to-SDR tone-mapping.
* ViGEmBus Virtual Gamepad Emulation: Emulates certified Xbox 360 and DualShock 4 controllers at the kernel driver level, providing true 360-degree analog stick control and bypassing anti-macro software blocks.
* Win32 Hardware Scan Codes: PS/2 Set 1 hardware scan code injection via `KEYEVENTF_SCANCODE` for full DirectX compatibility.

### 3. Perceptual Token Economics (dHash Gating)
* Continuous 1080p frame transmission consumes ~2.7M tokens per hour.
* The perception engine computes a 64-bit difference hash (dHash) before image encoding. If scene mutation is below 2.5%, a lightweight text confirmation is returned, saving up to 80% in token costs.

### 4. Acoustic Perception (WASAPI Loopback)
* Captures master audio output directly via the Windows Audio Session API (WASAPI) loopback buffer.
* Computes real-time log-mel spectrograms and Interaural Level Differences (ILD) to detect directional off-screen sound cues (footsteps, alarms, reload clicks) exposed via `game://audio/events`.

### 5. Deep Model Context Protocol Conformance
* Tools: State-mutating actions with execution timeouts, progress tokens (`progressToken`), and cancellation hooks (`notifications/cancelled`).
* Resources: Read-only telemetry streams supporting dynamic subscription notifications (`notifications/resources/updated`).
* Prompts: Reusable interactive strategy playbooks.
* Sampling: Server-initiated LLM vision evaluations and sub-agent planning.
* Elicitation: Human confirmation gates before executing destructive or irreversible in-game actions.

---

## Multi-Genre Benchmark Matrix

The project establishes four standardized benchmark tiers to evaluate autonomous agent capability:

| Tier | Genre | Benchmark Title | Evaluated Capabilities | Target Metric |
|------|-------|-----------------|------------------------|---------------|
| 1 | Turn-Based Strategy | Freeciv / Slay the Spire | Long-horizon planning, text OCR, menu navigation | Win rate > 75% on standard difficulty |
| 2 | 2D Grid & Platformer | Windows Minesweeper / Super Mario Bros | Spatial coordinate grounding, obstacle avoidance | 0% spatial misclicks; Mario 1-1 completion |
| 3 | 3D Open World | Minecraft (Survival Mode) | 3D voxel navigation, crafting trees, resource loops | Crafting diamond pickaxe within 45 minutes |
| 4 | Real-Time Action | Doom / Street Fighter II | High-frequency action chunking, reflex tripwires | First level clearance without health depletion |

---

## Phased Engineering Roadmap

* Phase 1: Core Foundation & Protocol Dispatcher (MCP JSON-RPC 2.0, stdio/HTTP/SSE, typed registries, dynamic router).
* Phase 2: Universal VLA Computer Use Engine (DXGI capture, ViGEm virtual gamepad, dHash gating, WASAPI audio, SoM grid).
* Phase 3: Minecraft High-Fidelity Bridge (Mineflayer NDJSON pipe, 3D voxel pathfinding, crafting matrix).
* Phase 4: Retro & Gymnasium Adapters (Libretro cores, state serialization, RAM variable peeking, Gym RL environments).
* Phase 5: Voyager-Inspired Skill Library (SQLite vector store, semantic skill retrieval, self-repair loops).
* Phase 6: Hardening, Multi-Genre Benchmarking & Distribution (SmartPlay evaluation, CI/CD, PyPI publishing).

---

## Repository Structure

```
gaming-mcp/
├── AGENTS.md                    # Universal repository rules for developers & AI agents
├── GEMINI.md                    # Antigravity agent workspace rules
├── docs/
│   ├── implementation_plan.md   # Complete architectural specification & blueprints
│   └── audit_report.md          # Multi-perspective quality review & council audit
├── research/
│   ├── arxiv/                   # Academic paper summaries and findings
│   └── ...                      # Research tooling and query caches
├── .licenses/                   # Attribution and licensing documentation
├── .gitignore                   # Comprehensive exclusion rules for credentials and ROMs
├── LICENSE                      # Project license (MIT)
└── README.md                    # Project overview and architectural guide
```

---

## License

This project is licensed under the terms of the [MIT License](LICENSE).
