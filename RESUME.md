# Gaming MCP Server -- Fast Resumption Pointer (RESUME.md)

**Notice for Resuming Agents and Operators:**
Read this file FIRST upon cold-start, session reboot, rate-limit recovery, or context window compaction. This file provides the exact execution state without requiring you to read past conversation transcripts.

---

## 1. Executive Status Dashboard

* **Project:** Gaming MCP Server (`gaming-mcp`)
* **Last Updated:** 2026-09-24
* **Operating System:** Windows 11 (Host for native DXGI, ViGEmBus, WASAPI, Win32 scan codes)
* **Autonomy Configuration:** Level 3 (Supervised Autonomous Goal Loop), Action Tier T2 (Local modifications, test execution, virtual device emulation, git commits)
* **Active Goal Directive:** `GEMINI38-TEAM-LOOP-PROMPT.md`
* **Ironclad Rule:** Absolute Zero Emojis (0 infractions across all files, code, commits, and logs)

---

## 2. Current Execution Pointer

* **Current Phase:** Phase 4: Retro & Gymnasium Adapters (Weeks 7-8)
* **Active Milestone:** Milestone 4.1: Libretro Core Integration & Milestone 4.2: Gymnasium RL Environment Wrapper
* **Active Subtasks:**
  - Subtask 4.1a -- stable-retro Core Bindings & Emulator Session Manager
  - Subtask 4.1b -- Frame Stepping, RAM Introspection, and Save State Tools (`retro_send_pad`, `retro_save_state`, `retro_load_state`, `retro_read_memory`)
  - Subtask 4.2a -- Gymnasium Environment Adapter (`gym_step`, `gym_reset`, `gym_action_space`, `gym_observation_space`)
* **Immediate Next Action:**
  1. Implement `src/gaming_mcp/adapters/retro.py` for Libretro / stable-retro integration with capability probing and headless mock simulation mode.
  2. Implement `src/gaming_mcp/adapters/gymnasium.py` wrapping standard Gymnasium environments into MCP tools and resources.
  3. Author unit and integration tests under `tests/test_adapters/test_retro.py` and `tests/test_adapters/test_gymnasium.py`.
  4. Run verification ladder (`ruff`, `mypy --strict`, `pytest`, zero-emoji audit).

---

## 3. Core State Pointers

| File | Purpose | Resumption Role |
|------|---------|-----------------|
| [RESUME.md](RESUME.md) | Cold-start state pointer | Read 1st: Instant orientation |
| [MEMORY.md](MEMORY.md) | Knowledge base of traps and fixes | Read 2nd: Avoid repeating known mistakes |
| [LOOP_STATE.json](LOOP_STATE.json) | Machine execution state | Read 3rd: Task status DAG and blockers |
| [PROGRESS.md](PROGRESS.md) | Append-only human-readable ledger | Read 4th: Last iteration report |
| [task.md](task.md) | High-level roadmap tracking | Reference: Project milestone tracking |
| [implementation_plan.md](implementation_plan.md) | Canonical architectural specification | Reference: Authoritative system blueprint |
| `EVIDENCE/` | Verification artifacts directory | Store: Test logs, benchmarks, screenshots |

---

## 4. Phase Execution Matrix

| Phase | Description | Status | Evidence Target |
|-------|-------------|--------|-----------------|
| Phase 1 | Core Foundation & Protocol Dispatcher | VERIFIED | `EVIDENCE/phase1/` |
| Phase 2 | Universal VLA Computer Use Engine | VERIFIED | `EVIDENCE/2.4-computer-use-adapter/` |
| Phase 3 | Minecraft High-Fidelity Bridge | VERIFIED | `EVIDENCE/phase3/` |
| Phase 4 | Retro & Gymnasium Adapters | IN_PROGRESS | `EVIDENCE/phase4/` |
| Phase 5 | Voyager-Inspired Skill Library | PENDING | `EVIDENCE/phase5/` |
| Phase 6 | Hardening, Benchmarking & Distribution | PENDING | `EVIDENCE/phase6/` |

---

## 5. Active Blockers and Dependencies

| Blocker ID | Affected Task | Summary | Unblock Plan | Human Required |
|------------|---------------|---------|--------------|----------------|
| `vigembus-python312-wheel-dependency` | 2.2b | `vgamepad` C-extension has no prebuilt wheel for Python 3.12 and requires ViGEmBus driver. | Implement abstract `GamepadDevice` SPI with capability probe. Fallback to typed `AdapterError` (-32002) advisory per `MEMORY.md` Case 2. | No |

---

## 6. Cold-Start Verification Routine (Execute in Terminal)

Run these commands to verify environment liveness before taking action:

```powershell
# 1. Reconcile git status
git status
git log -3 --oneline

# 2. Check Python toolchain
python --version
uv --version

# 3. Verify zero emojis across repository
python -c "
import os
for root, dirs, files in os.walk('.'):
    if '.git' in root: continue
    for f in files:
        if not f.endswith(('.md', '.py', '.json', '.toml', '.txt')): continue
        p = os.path.join(root, f)
        with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
            for idx, ch in enumerate(fp.read()):
                cp = ord(ch)
                if (0x1F600 <= cp <= 0x1F64F or 0x1F300 <= cp <= 0x1F5FF or 0x1F680 <= cp <= 0x1F6FF or 0x2600 <= cp <= 0x26FF or 0x2700 <= cp <= 0x27BF or 0x2B50 <= cp <= 0x2B55):
                    print(f'Emoji violation in {p}: {hex(cp)}')
print('Preflight zero-emoji check complete.')
"
```
