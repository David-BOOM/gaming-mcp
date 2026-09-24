"""Unit tests for trajectory splining, minimum-jerk curves, and Fitts' Law."""

import math
import random

from gaming_mcp.utils.curves import (
    estimate_fitts_duration,
    generate_cubic_bezier_path,
    generate_minimum_jerk_path,
    generate_relative_camera_deltas,
    minimum_jerk_factor,
    minimum_jerk_step,
    minimum_jerk_velocity_factor,
)


def test_minimum_jerk_factor_boundaries() -> None:
    """Verify polynomial evaluations at boundary conditions."""
    assert minimum_jerk_factor(0.0) == 0.0
    assert minimum_jerk_factor(-0.5) == 0.0
    assert minimum_jerk_factor(1.0) == 1.0
    assert minimum_jerk_factor(1.5) == 1.0
    # At u = 0.5: 10(0.125) - 15(0.0625) + 6(0.03125) = 1.25 - 0.9375 + 0.1875 = 0.5
    assert math.isclose(minimum_jerk_factor(0.5), 0.5, abs_tol=1e-6)


def test_minimum_jerk_velocity_profile() -> None:
    """Velocity profile must be bell-shaped: zero at endpoints, positive in the interior."""
    assert minimum_jerk_velocity_factor(0.0) == 0.0
    assert minimum_jerk_velocity_factor(1.0) == 0.0
    # Peak velocity is at u = 0.5
    peak = minimum_jerk_velocity_factor(0.5)
    assert peak > 1.5
    assert minimum_jerk_velocity_factor(0.2) > 0.0
    assert minimum_jerk_velocity_factor(0.8) > 0.0


def test_minimum_jerk_step() -> None:
    """Step interpolation must scale linearly with the polynomial factor."""
    start = (100.0, 200.0)
    end = (300.0, 400.0)

    p0 = minimum_jerk_step(start, end, 0.0)
    assert p0 == start

    p1 = minimum_jerk_step(start, end, 1.0)
    assert p1 == end

    p_mid = minimum_jerk_step(start, end, 0.5)
    assert math.isclose(p_mid[0], 200.0, abs_tol=1e-5)
    assert math.isclose(p_mid[1], 300.0, abs_tol=1e-5)


def test_estimate_fitts_duration() -> None:
    """Fitts' Law durations must scale monotonically with distance and clamp within bounds."""
    min_d = estimate_fitts_duration(0.0, min_ms=50.0, max_ms=1000.0)
    assert min_d == 50.0

    d_short = estimate_fitts_duration(100.0, target_width=50.0)
    d_long = estimate_fitts_duration(1000.0, target_width=50.0)
    assert d_long > d_short

    # Test clamping
    d_extreme = estimate_fitts_duration(100000.0, max_ms=500.0)
    assert d_extreme == 500.0


def test_generate_minimum_jerk_path() -> None:
    """Path generation must preserve endpoints and respect step counts."""
    start = (50, 100)
    end = (500, 800)
    rng = random.Random(42)

    # 1. Deterministic path without jitter
    path = generate_minimum_jerk_path(start, end, steps=10, jitter_std=0.0, rng=rng)
    assert len(path) == 10
    assert path[0] == start
    assert path[-1] == end

    # 2. Path with Gaussian micro-jitter
    path_jitter = generate_minimum_jerk_path(start, end, steps=15, jitter_std=1.5, rng=rng)
    assert len(path_jitter) == 15
    assert path_jitter[0] == start
    assert path_jitter[-1] == end

    # 3. Degenerate cases
    assert generate_minimum_jerk_path(start, start, steps=5) == [start, start]
    assert generate_minimum_jerk_path(start, end, steps=1) == [start, end]


def test_generate_cubic_bezier_path() -> None:
    """Cubic Bezier path must start and end at exact coordinates and produce smooth arcs."""
    start = (100, 100)
    end = (400, 400)
    rng = random.Random(1234)

    path = generate_cubic_bezier_path(start, end, steps=20, curvature=0.3, rng=rng)
    assert len(path) == 20
    assert path[0] == start
    assert path[-1] == end

    # Curvature should cause midpoint to deviate from the straight chord
    mid_idx = len(path) // 2
    chord_mid_x = (start[0] + end[0]) // 2
    chord_mid_y = (start[1] + end[1]) // 2
    # At least one coordinate should diverge from chord midpoint
    dx = abs(path[mid_idx][0] - chord_mid_x)
    dy = abs(path[mid_idx][1] - chord_mid_y)
    assert (dx + dy) > 5

    # Degenerate cases
    assert generate_cubic_bezier_path(start, start, steps=10) == [start, start]


def test_generate_relative_camera_deltas() -> None:
    """Relative camera delta generator must sum exactly to the target total rotation."""
    total_dx = 345
    total_dy = -178
    samples = 20

    deltas = generate_relative_camera_deltas(total_dx, total_dy, samples=samples)
    assert len(deltas) == samples

    sum_x = sum(d[0] for d in deltas)
    sum_y = sum(d[1] for d in deltas)

    assert sum_x == total_dx
    assert sum_y == total_dy

    # Middle delta should be larger than initial or final delta due to bell-curve acceleration
    first_magnitude = abs(deltas[0][0]) + abs(deltas[0][1])
    mid_magnitude = abs(deltas[samples // 2][0]) + abs(deltas[samples // 2][1])
    assert mid_magnitude >= first_magnitude

    # Zero delta case
    assert generate_relative_camera_deltas(0, 0, samples=5) == [(0, 0)]
