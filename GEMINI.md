# Workspace Rules — Gaming MCP Server

These rules are active across the entire `gaming-mcp` project and apply to all agents and automated workflows:

1. Zero Emojis Policy (Absolute): Never use any emojis or pictogram symbols in any file, commit message, plan, test, or response. All Unicode must pass automated verification with 0 infractions.
2. Planning-First Discipline: The project is currently in the Planning/Research stage. Do not generate source code, dummy implementations, or test suites unless explicitly instructed by the user. Follow the formal planning lifecycle.
3. Theoretical & Research Rigor: System architecture must be grounded in peer-reviewed academic literature (Voyager, Cradle, GITM, SmartPlay) and frontier AI company technical reports (DeepMind SIMA/Genie, Anthropic Computer Use, OpenAI Operator/CUA, Meta CICERO, xAI Grok).
4. MCP Specification Conformance: Adhere strictly to the official Model Context Protocol (v2025-06-18 / v2026-07-28), including cancellation hooks, progress tokens, resource subscriptions, human elicitation gates, and typed Pydantic schemas.
5. Low-Level I/O & Hardware Safety: Use ViGEmBus virtual gamepad emulation and Win32 hardware scan codes for full DirectX/Vulkan game compatibility. Enforce window boundary clipping, process blacklists, and emergency hardware kill-switches (`Ctrl+Alt+Shift+Pause/Break`).
6. Latency Mitigation & Token Economics: Mitigate cloud inference latency via Action Chunking, minimum-jerk trajectory smoothing, and local reflex tripwires. Mitigate token costs via 64-bit dHash perceptual delta gating and WASAPI loopback audio event telemetry.
7. Clean Repository Hygiene: Never commit API credentials, `.env` files, virtual environments, or copyrighted game ROMs/media. Conventional Commits with zero emojis.
