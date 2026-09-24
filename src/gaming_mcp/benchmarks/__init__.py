"""Multi-genre game benchmark evaluation and latency/token profiler suite.

Provides empirical evaluation runners across 4 gaming paradigms (Turn-Based Strategy,
2D Grid & Platformer, 3D Open World, and Real-Time Action), alongside microsecond-level
latency profiling and 64-bit dHash perceptual token economics benchmarking.
"""

from __future__ import annotations

from gaming_mcp.benchmarks.evaluation import (
    ActionChunkStep,
    ActionTripwireSimulator,
    FreecivCity,
    FreecivGameResult,
    FreecivSimulation,
    FreecivUnit,
    GameEvaluationMatrix,
    MarioBenchmarkResult,
    MarioBenchmarkRunner,
    MatrixEvaluationResult,
    MinecraftMilestone,
    MinecraftSurvivalPipeline,
    MinesweeperBoard,
    MinesweeperSolver,
    MinesweeperSolverResult,
    ReflexTripwireEvent,
    Tier1Result,
    Tier2Result,
    Tier3Result,
    Tier4Result,
)
from gaming_mcp.benchmarks.profiler import (
    CaptureLatencyResult,
    GamepadLatencyResult,
    InjectionLatencyResult,
    LatencyMetricSummary,
    LatencyProfiler,
    LatencyProfileResult,
    PerceptualScenarioResult,
    TokenEconomicsProfiler,
    TokenEconomicsResult,
    export_benchmark_artifacts,
)

__all__ = [
    "ActionChunkStep",
    "ActionTripwireSimulator",
    "CaptureLatencyResult",
    "FreecivCity",
    "FreecivGameResult",
    "FreecivSimulation",
    "FreecivUnit",
    "GameEvaluationMatrix",
    "GamepadLatencyResult",
    "InjectionLatencyResult",
    "LatencyMetricSummary",
    "LatencyProfileResult",
    "LatencyProfiler",
    "MarioBenchmarkResult",
    "MarioBenchmarkRunner",
    "MatrixEvaluationResult",
    "MinecraftMilestone",
    "MinecraftSurvivalPipeline",
    "MinesweeperBoard",
    "MinesweeperSolver",
    "MinesweeperSolverResult",
    "PerceptualScenarioResult",
    "ReflexTripwireEvent",
    "Tier1Result",
    "Tier2Result",
    "Tier3Result",
    "Tier4Result",
    "TokenEconomicsProfiler",
    "TokenEconomicsResult",
    "export_benchmark_artifacts",
]
