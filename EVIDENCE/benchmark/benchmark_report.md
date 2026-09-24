# Gaming MCP Server -- Benchmark Evaluation and Profiling Report

* **Generated:** 2026-09-24T21:49:54Z
* **Operating System:** win32
* **Python Runtime:** 3.12.9
* **Overall Status:** [PASS]

---

## 1. Executive Summary

This report establishes empirical verification for Milestone 6.1 (Multi-Genre Benchmark Evaluation) conforming to implementation_plan.md Part VI and GEMINI38-TEAM-LOOP-PROMPT.md. All evaluations adhere to the strict Zero Emojis policy with 0 infractions.

| Benchmark Suite | Key Evaluated Metric | Measured Value | Target Threshold | Status |

| ----------------- | ---------------------- | ---------------- | ------------------ | -------- |

| Tier 1: Strategy | Freeciv Win Rate | 100.0% | > 75.0% | [PASS] |

| Tier 2: Grid | Minesweeper Misclicks | 0.0% | 0.0% | [PASS] |

| Tier 2: Platformer | Mario World 1-1 | Completed | Completed | [PASS] |

| Tier 3: Open World | Minecraft Pipeline | Completed | All 5 Stages | [PASS] |

| Tier 4: Action | Reflex Tripwire Latency | 8.83 ms | < 25.0 ms | [PASS] |

| Latency: DXGI Capture | p95 Acquisition Time | 5.177 ms | < 15.0 ms | [PASS] |

| Latency: MSS Capture | p95 Acquisition Time | 13.363 ms | < 35.0 ms | [PASS] |

| Latency: Scan-Code | p95 Injection Time | 0.343 ms | < 2.0 ms | [PASS] |

| Latency: Gamepad Update | p95 Dispatch Time | 0.001 ms | < 1.0 ms | [PASS] |

| Token Economics | dHash Token Savings | 81.96% | > 75.0% | [PASS] |


---

## 2. Multi-Genre Evaluation Matrix Details

### Tier 1: Turn-Based Strategy (Freeciv)
* Games Evaluated: 20
* Games Won: 20
* Win Rate: 100.0% (Target: > 75.0%)
* Average Turns to Victory: 14.4
* Average Map Exploration: 34.04%

### Tier 2: 2D Grid & Platformer (Minesweeper & Super Mario Bros)
* Minesweeper Evaluated Games: 20
* Minesweeper Spatial Misclick Count: 0 (0.0% misclick rate)
* Minesweeper Win Rate: 85.0%
* Mario Level: World 1-1
* Mario Completed: Yes
* Final X Position: 3112 / 3100 px
* Elapsed Frames: 768 (12.8s)
* State Recoveries Used: 0

### Tier 3: 3D Open World (Minecraft Survival Crafting)
* Progression Pipeline: oak_log -> wooden_pickaxe -> cobblestone -> stone_pickaxe -> furnace
* Milestones Status:
  - [oak_log]: 4/4 acquired at 27.0s
  - [wooden_pickaxe]: 1/1 acquired at 36.0s
  - [cobblestone]: 11/11 acquired at 91.0s
  - [stone_pickaxe]: 1/1 acquired at 96.0s
  - [furnace]: 1/1 acquired at 100.0s
* Total Elapsed Simulated Time: 100.0s
* Final Inventory Breakdown: {"oak_log": 0, "oak_planks": 7, "crafting_table": 0, "stick": 0, "wooden_pickaxe": 1, "cobblestone": 0, "stone_pickaxe": 1, "furnace": 1}

### Tier 4: Real-Time Action (Action Chunking & Reflex Tripwires)
* Doom Level Clearance: Cleared
* Final Health: 100 HP
* Damage Taken: 0 HP
* Street Fighter II Combo: Success
* Average Reflex Tripwire Latency: 8.83 ms (Target: < 25.0 ms)

---

## 3. Subsystem Latency Benchmarks

| Subsystem | Samples | Min (ms) | Mean (ms) | Median (ms) | p95 (ms) | p99 (ms) | Target | Status |

| ----------- | ------- | -------- | --------- | ----------- | -------- | -------- | ------ | ------ |

| DXGI Capture | 50 | 3.329 | 4.555 | 4.631 | 5.177 | 5.785 | < 15.0 ms | [PASS] |

| MSS Capture | 50 | 9.308 | 11.841 | 11.188 | 13.363 | 48.697 | < 35.0 ms | [PASS] |

| Scan-Code Input | 50 | 0.208 | 0.278 | 0.263 | 0.343 | 0.495 | < 2.0 ms | [PASS] |

| Virtual Gamepad | 50 | 0.001 | 0.001 | 0.001 | 0.001 | 0.012 | < 1.0 ms | [PASS] |


---

## 4. Perceptual Token Economics (64-bit dHash Gating)

* **Baseline Token Consumption (Un-Gated):** 160,000 tokens
* **Gated Token Consumption (With dHash):** 28,860 tokens
* **Total Tokens Saved:** 131,140 tokens
* **Measured Token Reduction:** **81.96%** (Target: > 75.0%)
* **Status:** [PASS]

### Workload Scenario Breakdown

| Scenario | Total Frames | Transmitted | Suppressed | Suppression Rate | Mean Hamming Distance |

| -------- | ------------ | ----------- | ---------- | ---------------- | --------------------- |

| Identical Static Frames (Menu/Paused) | 70 | 1 | 69 | 98.57% | 0.0 bits |
| HUD-Only Animations with Masking | 15 | 1 | 14 | 93.33% | 0.0 bits |
| Dynamic Action Scene (Camera/Movement) | 15 | 15 | 0 | 0.0% | 34.13 bits |

---

*Automated Benchmark Verification Suite -- gaming-mcp v0.1.0*
