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

* **Current Phase:** Phase 1: Core Foundation & Protocol Dispatcher (Weeks 1-2)
* **Active Milestone:** Milestone 1.1: MCP Protocol Engine
* **Active Subtask:** Subtask 1.1a -- Project Scaffolding and Foundation Core (`pyproject.toml`, directory tree, `src/gaming_mcp/server.py`)
* **Immediate Next Action:**
  1. Author `pyproject.toml` per Part IX of `implementation_plan.md`.
  2. Create source tree: `src/gaming_mcp/` (`core/`, `io/`, `adapters/`, `skills/`).
  3. Implement `src/gaming_mcp/server.py` with standard JSON-RPC 2.0 lifecycle handlers.
  4. Write initial tests in `tests/test_server.py`.
  5. Run `pytest` to establish baseline test green.
  6. Run pre-commit Unicode check to verify 0 emojis.
  7. Commit as `feat(core): scaffold project structure and mcp protocol engine`.

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
| Phase 1 | Core Foundation & Protocol Dispatcher | IN_PROGRESS | `EVIDENCE/phase1/` |
| Phase 2 | Universal VLA Computer Use Engine | PENDING | `EVIDENCE/phase2/` |
| Phase 3 | Minecraft High-Fidelity Bridge | PENDING | `EVIDENCE/phase3/` |
| Phase 4 | Retro & Gymnasium Adapters | PENDING | `EVIDENCE/phase4/` |
| Phase 5 | Voyager-Inspired Skill Library | PENDING | `EVIDENCE/phase5/` |
| Phase 6 | Hardening, Benchmarking & Distribution | PENDING | `EVIDENCE/phase6/` |

---

## 5. Active Blockers and Dependencies

| Blocker ID | Affected Task | Summary | Unblock Plan | Human Required |
|------------|---------------|---------|--------------|----------------|
| None | None | No active blockers. Phase 1 is fully unblocked. | N/A | No |

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
