"""Comprehensive test suite for LatencyProfiler and TokenEconomicsProfiler.

Verifies:
- Frame grab latency (<15ms DXGI, <35ms MSS).
- Win32 hardware scan-code injection latency (<2ms).
- Virtual gamepad state dispatch latency (<1ms).
- 64-bit dHash perceptual gating token savings (>75% target).
- Exporting artifacts to EVIDENCE/benchmark/ with ZERO EMOJIS.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from gaming_mcp.benchmarks.evaluation import GameEvaluationMatrix
from gaming_mcp.benchmarks.profiler import (
    LatencyProfiler,
    TokenEconomicsProfiler,
    export_benchmark_artifacts,
)


def test_latency_summary_computation() -> None:
    """Verify percentile and statistical summary calculations in LatencyProfiler."""
    samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    summary = LatencyProfiler._compute_summary(samples, target_ms=10.0)

    assert summary.sample_count == 10
    assert summary.min_ms == 1.0
    assert summary.max_ms == 10.0
    assert summary.mean_ms == 5.5
    assert summary.median_ms == 6.0
    assert summary.p95_ms == 10.0
    assert summary.passed is True


def test_latency_summary_empty() -> None:
    """Verify graceful handling of empty sample sequences."""
    summary = LatencyProfiler._compute_summary([], target_ms=5.0)
    assert summary.sample_count == 0
    assert summary.passed is False


def test_profile_screen_capture() -> None:
    """Verify screen capture latency benchmarking for DXGI and MSS."""
    profiler = LatencyProfiler()
    res = profiler.profile_screen_capture(iterations=10)

    assert res.dxgi_available is True
    assert res.dxgi_metrics.p95_ms <= 15.0
    assert res.dxgi_metrics.passed is True

    assert res.mss_available is True
    assert res.mss_metrics.p95_ms <= 35.0
    assert res.mss_metrics.passed is True
    assert res.passed is True


def test_profile_scancode_injection() -> None:
    """Verify hardware scan-code injection latency benchmarking (<2ms)."""
    profiler = LatencyProfiler()
    res = profiler.profile_scancode_injection(iterations=25)

    assert res.input_available is True
    assert res.metrics.sample_count == 25
    assert res.metrics.p95_ms <= 2.0
    assert res.passed is True


def test_profile_gamepad_latency() -> None:
    """Verify virtual gamepad state update dispatch latency benchmarking (<1ms)."""
    profiler = LatencyProfiler()
    res = profiler.profile_gamepad_latency(iterations=25)

    assert res.gamepad_available is True
    assert res.metrics.sample_count == 25
    assert res.metrics.p95_ms <= 1.0
    assert res.passed is True


def test_run_full_latency_profile() -> None:
    """Verify aggregated latency profile across all subsystems."""
    profiler = LatencyProfiler()
    res = profiler.run_full_profile(iterations=15)

    assert res.all_passed is True
    assert res.capture.passed is True
    assert res.injection.passed is True
    assert res.gamepad.passed is True


def test_token_economics_identical_frames() -> None:
    """Verify that identical static frames achieve high suppression rate."""
    profiler = TokenEconomicsProfiler()
    res = profiler.evaluate_identical_frames(count=20)

    assert res.total_frames == 20
    assert res.transmitted_frames == 1  # Only initial frame transmitted
    assert res.suppressed_frames == 19
    assert res.suppression_rate_pct == 95.0
    assert res.mean_hamming_distance < 3.0


def test_token_economics_hud_animations() -> None:
    """Verify that HUD masking successfully suppresses frame transmission."""
    profiler = TokenEconomicsProfiler()
    res = profiler.evaluate_hud_animations(count=20)

    assert res.total_frames == 20
    assert res.transmitted_frames == 1
    assert res.suppressed_frames == 19
    assert res.suppression_rate_pct == 95.0


def test_token_economics_dynamic_scenes() -> None:
    """Verify that active gameplay scenes are detected as mutations and transmitted."""
    profiler = TokenEconomicsProfiler()
    res = profiler.evaluate_dynamic_scenes(count=20)

    assert res.total_frames == 20
    assert res.transmitted_frames > 15  # Genuine motion detected
    assert res.mean_hamming_distance > 5.0


def test_token_economics_session_workload() -> None:
    """Verify mixed gameplay session achieves >75% token reduction target."""
    profiler = TokenEconomicsProfiler()
    res = profiler.run_full_profile(total_session_frames=100)

    assert res.target_reduction_percentage == 75.0
    assert res.token_reduction_percentage >= 75.0
    assert res.passed is True
    assert res.tokens_saved > 0
    assert len(res.scenarios) == 3


def test_export_benchmark_artifacts_and_zero_emoji(tmp_path: Path) -> None:
    """Verify artifact generation and ironclad ZERO EMOJIS adherence."""
    matrix = GameEvaluationMatrix()
    matrix_res = matrix.run_all(tier1_runs=5, tier2_runs=5)

    lat_prof = LatencyProfiler()
    lat_res = lat_prof.run_full_profile(iterations=10)

    tok_prof = TokenEconomicsProfiler()
    tok_res = tok_prof.run_full_profile(total_session_frames=50)

    json_path, md_path = export_benchmark_artifacts(
        matrix_result=matrix_res,
        latency_result=lat_res,
        token_result=tok_res,
        output_dir=tmp_path,
    )

    assert json_path.exists()
    assert md_path.exists()

    # Validate JSON parsing
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
        assert data["all_benchmarks_passed"] is True

    # Validate Markdown content
    with open(md_path, encoding="utf-8") as f:
        md_text = f.read()
        assert "Benchmark Evaluation and Profiling Report" in md_text
        assert "Tier 1: Turn-Based Strategy" in md_text
        assert "Tier 2: 2D Grid & Platformer" in md_text
        assert "Tier 3: 3D Open World" in md_text
        assert "Tier 4: Real-Time Action" in md_text

    # Strict Zero Emoji Verification across generated artifacts
    for p in (json_path, md_path):
        with open(p, encoding="utf-8") as f:
            content = f.read()
            for idx, ch in enumerate(content):
                cp = ord(ch)
                if (
                    0x1F600 <= cp <= 0x1F64F
                    or 0x1F300 <= cp <= 0x1F5FF
                    or 0x1F680 <= cp <= 0x1F6FF
                    or 0x2600 <= cp <= 0x26FF
                    or 0x2700 <= cp <= 0x27BF
                    or 0x2B50 <= cp <= 0x2B55
                ):
                    msg = f"Emoji violation found in {p.name} at char {idx}: U+{cp:04X}"
                    raise AssertionError(msg)
