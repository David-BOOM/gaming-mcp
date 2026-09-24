"""Comprehensive test suite for the 4-Tier Game Evaluation Matrix.

Verifies:
- Tier 1 (Freeciv): Turn-based state exploration, heuristics, and >75% win rate target.
- Tier 2 (Minesweeper & Mario): 0% spatial misclicks and Super Mario Bros World 1-1 completion.
- Tier 3 (Minecraft): 5-stage survival crafting pipeline (oak_log to furnace).
- Tier 4 (Real-Time Action): Reflex tripwires and action chunk execution.
"""

from __future__ import annotations

from gaming_mcp.benchmarks.evaluation import (
    ActionTripwireSimulator,
    FreecivSimulation,
    GameEvaluationMatrix,
    MarioBenchmarkRunner,
    MinecraftSurvivalPipeline,
    MinesweeperBoard,
    MinesweeperSolver,
)


def test_freeciv_simulation_init() -> None:
    """Verify initial world state and exploration grid in Freeciv simulation."""
    sim = FreecivSimulation(seed=123)
    assert sim.MAP_WIDTH == 24
    assert sim.MAP_HEIGHT == 24
    assert len(sim.player_units) == 3
    assert len(sim.rival_cities) == 1
    assert sim.get_exploration_percentage() > 0.0


def test_freeciv_step_turn() -> None:
    """Verify state transitions and exploration progress over multiple turns."""
    sim = FreecivSimulation(seed=456)
    initial_expl = sim.get_exploration_percentage()

    # Step 15 turns
    for _ in range(15):
        sim.step_turn()

    assert sim.turns_elapsed == 15
    assert sim.get_exploration_percentage() >= initial_expl
    assert sim.player_science > 0


def test_freeciv_run_match() -> None:
    """Verify match completion, victory detection, and metric scoring."""
    sim = FreecivSimulation(seed=789)
    result = sim.run_match(match_id=1)

    assert result.game_id == 1
    assert result.turns_elapsed > 0
    assert result.victory_type in ("domination", "scientific", "score", "loss")
    assert result.exploration_percentage > 10.0
    assert result.score > 0


def test_tier1_evaluation_win_rate_target() -> None:
    """Verify that Tier 1 Freeciv evaluation achieves >75% win rate target."""
    matrix = GameEvaluationMatrix()
    res = matrix.run_tier1(runs=20)

    assert res.tier == "Tier 1: Turn-Based Strategy (Freeciv)"
    assert res.games_evaluated == 20
    assert res.win_rate_percentage >= 75.0
    assert res.pass_target is True
    assert res.average_turns_to_win > 0
    assert res.average_exploration_percentage > 15.0


def test_minesweeper_board_misclick_detection() -> None:
    """Verify that spatial boundary and state violations increment misclick counter."""
    board = MinesweeperBoard(width=9, height=9, mines=10, seed=42)

    # Initial safe click at center
    success, msg = board.click(4, 4)
    assert success is True
    assert msg == "Safe"

    # Out of bounds clicks
    success, msg = board.click(-1, 0)
    assert success is False
    assert "Out of bounds" in msg
    assert board.misclicks == 1

    success, msg = board.click(9, 4)
    assert success is False
    assert board.misclicks == 2

    # Already revealed cell click
    success, msg = board.click(4, 4)
    assert success is False
    assert "revealed" in msg
    assert board.misclicks == 3

    # Flag cell, then click flagged cell
    board.flag(0, 0)
    success, msg = board.click(0, 0)
    assert success is False
    assert "flagged" in msg
    assert board.misclicks == 4


def test_minesweeper_solver_zero_spatial_misclicks() -> None:
    """Verify that the constraint satisfaction solver generates 0% spatial misclicks."""
    boards_to_test = 15
    for i in range(boards_to_test):
        board = MinesweeperBoard(width=9, height=9, mines=10, seed=100 + i)
        res = MinesweeperSolver.solve(board)

        # Invariant: 0% spatial misclicks
        assert res.spatial_misclicks == 0
        assert res.spatial_misclick_rate_pct == 0.0
        assert res.total_clicks > 0


def test_mario_world_1_1_completion() -> None:
    """Verify autonomous Super Mario Bros World 1-1 completion run via RetroAdapter."""
    res = MarioBenchmarkRunner.run()

    assert res.level == "World 1-1"
    assert res.completed is True
    assert res.final_x_pos >= res.target_x_pos
    assert res.elapsed_frames > 0
    assert res.simulated_seconds > 0
    assert res.lives_remaining > 0


def test_tier2_evaluation_runner() -> None:
    """Verify Tier 2 evaluation runner combining Minesweeper and Mario 1-1."""
    matrix = GameEvaluationMatrix()
    res = matrix.run_tier2(minesweeper_games=15)

    assert res.tier == "Tier 2: 2D Grid & Platformer"
    assert res.minesweeper_misclick_rate_pct == 0.0
    assert res.mario_world_1_1_completed is True
    assert res.pass_target is True
    assert len(res.minesweeper_details) == 15


def test_minecraft_survival_pipeline() -> None:
    """Verify the 5-stage survival crafting pipeline (oak_log to furnace)."""
    pipeline = MinecraftSurvivalPipeline(seed=42)
    res = pipeline.run_pipeline()

    assert res.all_milestones_completed is True
    assert res.pass_target is True
    assert len(res.milestones) == 5

    # Verify pipeline ordering
    items = [m.item_name for m in res.milestones]
    assert items == ["oak_log", "wooden_pickaxe", "cobblestone", "stone_pickaxe", "furnace"]

    # Verify final inventory
    assert res.final_inventory["wooden_pickaxe"] == 1
    assert res.final_inventory["stone_pickaxe"] == 1
    assert res.final_inventory["furnace"] == 1


def test_tier3_evaluation_runner() -> None:
    """Verify Tier 3 evaluation runner for Minecraft survival progression."""
    matrix = GameEvaluationMatrix()
    res = matrix.run_tier3()

    assert res.tier == "Tier 3: 3D Open World (Minecraft Survival Crafting)"
    assert res.all_milestones_completed is True
    assert res.pass_target is True
    assert res.total_elapsed_seconds > 0


def test_action_tripwire_simulator() -> None:
    """Verify real-time reflex tripwires and action chunk execution."""
    res = ActionTripwireSimulator.run()

    assert res.doom_level_cleared is True
    assert res.doom_final_health == 100
    assert res.doom_damage_taken == 0
    assert res.sf2_combo_execution_success is True
    assert res.average_reflex_latency_ms < 25.0
    assert res.pass_target is True
    assert len(res.tripwire_events) == 2


def test_tier4_evaluation_runner() -> None:
    """Verify Tier 4 evaluation runner for real-time action."""
    matrix = GameEvaluationMatrix()
    res = matrix.run_tier4()

    assert res.tier == "Tier 4: Real-Time Action (Doom / Street Fighter Simulation)"
    assert res.pass_target is True


def test_game_evaluation_matrix_run_all() -> None:
    """Verify full 4-tier evaluation matrix execution and markdown summary."""
    matrix = GameEvaluationMatrix()
    result = matrix.run_all(tier1_runs=10, tier2_runs=10)

    assert result.total_tiers_evaluated == 4
    assert result.all_tiers_passed is True
    assert result.tier1.pass_target is True
    assert result.tier2.pass_target is True
    assert result.tier3.pass_target is True
    assert result.tier4.pass_target is True
    assert "Overall Status: PASSED" in result.summary_markdown
    assert "Tier 1: Turn-Based Strategy" in result.summary_markdown
    assert "Tier 2: 2D Grid & Platformer" in result.summary_markdown
    assert "Tier 3: 3D Open World" in result.summary_markdown
    assert "Tier 4: Real-Time Action" in result.summary_markdown
