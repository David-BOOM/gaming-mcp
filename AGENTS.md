# Repository Rules and Guidelines for Developers and Autonomous Agents

This document establishes the mandatory architectural standards, coding practices, and operational boundaries for all human developers, contributors, and autonomous AI coding agents (Antigravity, Claude Code, Cursor, Codex, etc.) working within the `gaming-mcp` repository.

---

## 1. Absolute Prohibition of Emojis (Zero Emojis Policy)

* Strictly Zero Emojis: No emoji or pictogram characters (Unicode ranges 0x1F000-0x1FFFF, 0x2600-0x27BF, 0x2B50-0x2B55, etc.) are permitted anywhere in this repository.
* Universal Scope: This restriction applies to all files without exception:
  * Markdown documentation, plans, and task lists.
  * Source code, comments, docstrings, and variable names.
  * JSON, YAML, and configuration schemas.
  * Git commit messages and pull request descriptions.
  * Automated test output and agent conversational responses.
* Pre-Commit Verification: Every change must pass automated Unicode verification confirming 0 emoji infractions before committing or reporting completion.

---

## 2. Planning-First and Lifecycle Stage Discipline

* Planning Stage Enforcement: When the project is designated in the Planning/Research stage, agents and developers must strictly refrain from generating source code, dummy implementations, or test suites unless explicitly directed by the project owner.
* Structured Workflow: All modifications follow the formal lifecycle:
  1. Deep Research: Synthesizing literature and technical standards.
  2. Architectural Specification: Updating `implementation_plan.md` and `docs/`.
  3. Quality Audit: Peer review and multi-perspective verification.
  4. Human Approval: Explicit confirmation before proceeding to code.
  5. Implementation: Scaffolding and coding once authorized.
  6. Verification: Automated test suites and benchmark execution.
* Synchronized Artifacts: Any architectural deviation must be reflected in `implementation_plan.md`, `docs/audit_report.md`, and `task.md`.

---

## 3. Theoretical Rigor and Academic Grounding

* Grounded in Frontier Research: All system designs must trace their lineage to peer-reviewed academic literature (Voyager, BAAI Cradle, GITM, SmartPlay, ACT) and frontier AI company technical reports (DeepMind SIMA/Genie, Anthropic Computer Use, OpenAI Operator/CUA, Meta CICERO, xAI Grok).
* Explicit Paradigm Classification: Maintain clear boundaries between interaction tiers:
  * Tier 1: Deterministic High-Fidelity APIs (Mineflayer, Libretro cores, OpenAI Gymnasium).
  * Tier 2: Universal OS-Level Computer Use (DXGI zero-copy screen capture, hardware scan codes, ViGEmBus virtual gamepad).
  * Tier 3: Telemetry & Memory Introspection (RCON, UDP packets, shared memory).

---

## 4. Model Context Protocol (MCP) Specification Conformance

* Protocol Version: Strict adherence to the official Model Context Protocol specifications (v2025-06-18 and v2026-07-28).
* Mandatory Protocol Primitives:
  * Cancellation: Implement handlers for `notifications/cancelled` that immediately release physical and virtual keys and halt running routines.
  * Progress Tokens: Report fine-grained progress via `notifications/progress` for multi-second operations (e.g., pathfinding).
  * Subscriptions: Expose reactive resources supporting `resources/subscribe` and dynamic push events (`notifications/resources/updated`).
  * Sampling: Utilize `sampling/createMessage` for server-initiated visual sanity checks before high-stakes actions.
  * Human Elicitation: Enforce `elicitation/createMessage` as a mandatory authorization gate prior to destructive or irreversible actions (save file overwrites, microtransactions).
* Strict Typing: All tool input schemas and resource definitions must be defined using Pydantic models with exhaustive property descriptions and type constraints.

---

## 5. Low-Level I/O, Hardware Drivers, and Safety Guardrails

* Driver-Level Input: Prefer kernel-level virtual devices (ViGEmBus for virtual Xbox 360/DualShock 4 controllers) and Win32 PS/2 Set 1 hardware scan codes (`KEYEVENTF_SCANCODE`) over synthetic user-space hooks (`pyautogui` or GDI `PostMessage`) to guarantee compatibility with DirectX/Vulkan games and resist anti-macro blocks.
* Zero-Copy Capture: Utilize DXGI Desktop Duplication with ACES filmic HDR-to-SDR tone-mapping for low-latency GPU frame acquisition, retaining MSS as a cross-platform fallback.
* Mandatory Safety Envelopes:
  * Window Rect Clipping: Reject or clamp mouse cursor coordinates that fall outside the target game window.
  * Process Blacklisting: Refuse focus locking or input injection into sensitive host OS processes (`cmd.exe`, `powershell.exe`, `Taskmgr.exe`, credential managers, browser password dialogs).
  * Emergency Hardware Kill-Switch: Run a low-level global keyboard hook monitoring `Ctrl + Alt + Shift + Pause/Break` that instantaneously halts all input and terminates active macros.
  * Privacy Redaction Masking: Support zeroing out user-defined screen regions (personal chats, system clock, notification banners) before frame serialization.

---

## 6. Real-Time Latency Mitigation and Token Economics

* POMDP Latency Modeling: Recognize the temporal disparity between 60 Hz physics loops (16.6ms) and remote LLM inference (500ms to 2,500ms).
* Action Chunking & Trajectory Smoothing: Emit parameterized temporal action sequences rather than single atomic taps, interpolated using minimum-jerk polynomials satisfying Fitts' Law.
* Acoustic Perception: Integrate WASAPI loopback audio capture to process off-screen tactical audio cues (footsteps, alarms) exposed via `game://audio/events`.
* Perceptual Token Economics (dHash Gating): Compute 64-bit difference hashes before image encoding. If visual mutation is below 2.5%, suppress image transmission and return a lightweight text confirmation, saving up to 80% in token costs.

---

## 7. Repository Hygiene and Secret Prevention

* Prohibited Assets: Never commit:
  * API keys, tokens, credentials, or `.env` files.
  * Copyrighted game ROMs, BIOS dumps, ISO images, or proprietary game media.
  * Python virtual environments (`.venv`), compiled caches (`__pycache__`, `.pytest_cache`), or build artifacts.
* Commit Standards:
  * Use Conventional Commits (`docs:`, `feat:`, `fix:`, `refactor:`, `test:`, `chore:`).
  * Write clear, imperative, descriptive commit messages.
  * Maintain strictly zero emojis in all commit messages.
