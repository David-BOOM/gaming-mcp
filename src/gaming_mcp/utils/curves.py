"""Trajectory splining and human-like motor curves for mouse actuation.

Implements Flash and Hogan (1985) minimum-jerk trajectory polynomials,
Fitts' Law duration modeling, and cubic Bezier curve generation with
Gaussian micro-jitter for natural cursor movement and 3D camera rotation.
"""

import math
import random


def minimum_jerk_factor(u: float) -> float:
    """Compute the Flash & Hogan (1985) minimum-jerk factor for normalized time u in [0, 1].

    s(u) = 10 * u^3 - 15 * u^4 + 6 * u^5
    """
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    return 10.0 * (u**3) - 15.0 * (u**4) + 6.0 * (u**5)


def minimum_jerk_velocity_factor(u: float) -> float:
    """Compute the first derivative of the minimum-jerk polynomial: ds/du.

    ds/du = 30 * u^2 - 60 * u^3 + 30 * u^4
    """
    if u <= 0.0 or u >= 1.0:
        return 0.0
    return 30.0 * (u**2) - 60.0 * (u**3) + 30.0 * (u**4)


def minimum_jerk_step(
    start: tuple[float, float],
    end: tuple[float, float],
    u: float,
) -> tuple[float, float]:
    """Compute the (x, y) coordinates at normalized time u between start and end."""
    factor = minimum_jerk_factor(u)
    x = start[0] + (end[0] - start[0]) * factor
    y = start[1] + (end[1] - start[1]) * factor
    return x, y


def estimate_fitts_duration(
    distance: float,
    target_width: float = 50.0,
    a: float = 100.0,
    b: float = 150.0,
    min_ms: float = 80.0,
    max_ms: float = 1500.0,
) -> float:
    """Estimate movement duration in milliseconds using Fitts' Law.

    T = a + b * log2(1 + D / W)
    Clamped between min_ms and max_ms.
    """
    if distance <= 0.0:
        return min_ms
    w = max(1.0, target_width)
    index_of_difficulty = math.log2(1.0 + (distance / w))
    raw_duration = a + b * index_of_difficulty
    return max(min_ms, min(max_ms, raw_duration))


def generate_minimum_jerk_path(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int = 20,
    jitter_std: float = 0.5,
    rng: random.Random | None = None,
) -> list[tuple[int, int]]:
    """Generate a discrete trajectory using the minimum-jerk profile.

    Start and end points are preserved exactly. Intermediate points may include
    sub-pixel Gaussian motor noise to emulate human physiology.
    """
    if steps <= 1 or start == end:
        return [start, end]

    r = rng if rng is not None else random.Random()
    path: list[tuple[int, int]] = [start]

    for i in range(1, steps - 1):
        u = i / (steps - 1)
        x_float, y_float = minimum_jerk_step(
            (float(start[0]), float(start[1])),
            (float(end[0]), float(end[1])),
            u,
        )
        if jitter_std > 0.0:
            x_float += r.gauss(0.0, jitter_std)
            y_float += r.gauss(0.0, jitter_std)
        path.append((round(x_float), round(y_float)))

    path.append(end)
    return path


def generate_cubic_bezier_path(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int = 25,
    curvature: float = 0.2,
    jitter_std: float = 0.5,
    rng: random.Random | None = None,
) -> list[tuple[int, int]]:
    """Generate a curved mouse trajectory using a cubic Bezier curve.

    Intermediate control points P1 and P2 are offset perpendicularly to the
    line of travel, simulating human hand arc trajectories.
    """
    if steps <= 1 or start == end:
        return [start, end]

    r = rng if rng is not None else random.Random()
    dx = float(end[0] - start[0])
    dy = float(end[1] - start[1])
    dist = math.hypot(dx, dy)

    if dist < 1e-4:
        return [start, end]

    # Normal vector perpendicular to trajectory
    nx = -dy / dist
    ny = dx / dist

    # Determine randomized curve offset
    side = 1.0 if r.random() > 0.5 else -1.0
    offset = dist * curvature * side

    # Control points
    p0 = (float(start[0]), float(start[1]))
    p1 = (
        start[0] + dx * 0.25 + nx * offset * (0.8 + 0.4 * r.random()),
        start[1] + dy * 0.25 + ny * offset * (0.8 + 0.4 * r.random()),
    )
    p2 = (
        start[0] + dx * 0.75 + nx * offset * (0.8 + 0.4 * r.random()),
        start[1] + dy * 0.75 + ny * offset * (0.8 + 0.4 * r.random()),
    )
    p3 = (float(end[0]), float(end[1]))

    path: list[tuple[int, int]] = [start]

    for i in range(1, steps - 1):
        # Apply minimum-jerk timing to the Bezier parameter t
        u = i / (steps - 1)
        t = minimum_jerk_factor(u)
        omt = 1.0 - t

        # Cubic Bezier formula: (1-t)^3*P0 + 3(1-t)^2*t*P1 + 3(1-t)*t^2*P2 + t^3*P3
        bx = (
            (omt**3) * p0[0]
            + 3.0 * (omt**2) * t * p1[0]
            + 3.0 * omt * (t**2) * p2[0]
            + (t**3) * p3[0]
        )
        by = (
            (omt**3) * p0[1]
            + 3.0 * (omt**2) * t * p1[1]
            + 3.0 * omt * (t**2) * p2[1]
            + (t**3) * p3[1]
        )

        if jitter_std > 0.0:
            bx += r.gauss(0.0, jitter_std)
            by += r.gauss(0.0, jitter_std)

        path.append((round(bx), round(by)))

    path.append(end)
    return path


def generate_relative_camera_deltas(
    total_dx: int,
    total_dy: int,
    samples: int = 15,
) -> list[tuple[int, int]]:
    """Slice a total 3D camera pan into discrete relative mouse deltas.

    Uses the minimum-jerk velocity profile so that acceleration and deceleration
    are smooth and physical, preventing choppy camera pans in first-person games.
    The sum of all deltas exactly equals (total_dx, total_dy).
    """
    if samples <= 1 or (total_dx == 0 and total_dy == 0):
        return [(total_dx, total_dy)]

    # Compute velocity factor for each sample interval
    weights: list[float] = []
    for i in range(samples):
        u = (i + 0.5) / samples
        weights.append(minimum_jerk_velocity_factor(u))

    total_weight = sum(weights)
    if total_weight <= 0.0:
        total_weight = 1.0

    deltas: list[tuple[int, int]] = []
    accum_x = 0
    accum_y = 0

    for i in range(samples - 1):
        fraction = weights[i] / total_weight
        dx = round(total_dx * fraction)
        dy = round(total_dy * fraction)
        deltas.append((dx, dy))
        accum_x += dx
        accum_y += dy

    # Final sample absorbs remainder to guarantee exact sum
    deltas.append((total_dx - accum_x, total_dy - accum_y))
    return deltas
