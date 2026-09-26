"""Unit tests for smooth 3D camera look actuation and gamepad fallback behavior."""

from unittest.mock import MagicMock, patch

import pytest

from gaming_mcp.io.gamepad import (
    MockGamepadController,
    get_gamepad_controller,
)
from gaming_mcp.io.input import Win32InputInjector


def test_mouse_look_smooth_zero_deltas() -> None:
    """When both total_dx and total_dy are zero, return True immediately without dispatch."""
    injector = Win32InputInjector()
    with (
        patch.object(injector, "mouse_move_relative") as mock_rel,
        patch("time.sleep") as mock_sleep,
    ):
        res = injector.mouse_look_smooth(0, 0, duration_ms=100, samples=15)
        assert res is True
        mock_rel.assert_not_called()
        mock_sleep.assert_not_called()


@pytest.mark.parametrize(
    ("total_dx", "total_dy", "samples"),
    [
        (300, 150, 15),
        (-250, 400, 20),
        (-180, -90, 10),
        (5, -7, 12),
        (1000, 0, 30),
        (0, -500, 25),
    ],
)
def test_mouse_look_smooth_cumulative_sum_exactness(
    total_dx: int,
    total_dy: int,
    samples: int,
) -> None:
    """Cumulative sum of dispatched deltas must exactly match total_dx and total_dy."""
    injector = Win32InputInjector()
    with (
        patch.object(injector, "mouse_move_relative", return_value=True) as mock_rel,
        patch("time.sleep"),
    ):
        res = injector.mouse_look_smooth(total_dx, total_dy, duration_ms=0, samples=samples)
        assert res is True
        assert mock_rel.call_count == samples

        captured_dx = [call_args.args[0] for call_args in mock_rel.call_args_list]
        captured_dy = [call_args.args[1] for call_args in mock_rel.call_args_list]

        assert sum(captured_dx) == total_dx
        assert sum(captured_dy) == total_dy


def test_mouse_look_smooth_minimum_jerk_distribution() -> None:
    """Relative deltas must follow a bell-shaped minimum-jerk velocity curve."""
    injector = Win32InputInjector()
    total_dx = 500
    samples = 15

    with (
        patch.object(injector, "mouse_move_relative", return_value=True) as mock_rel,
        patch("time.sleep"),
    ):
        res = injector.mouse_look_smooth(total_dx, 0, duration_ms=0, samples=samples)
        assert res is True

        captured_dx = [call_args.args[0] for call_args in mock_rel.call_args_list]
        assert len(captured_dx) == samples

        mid_idx = samples // 2
        peak_delta = captured_dx[mid_idx]
        initial_delta = captured_dx[0]
        final_delta = captured_dx[-1]

        # Center delta must be greater than boundary deltas
        assert peak_delta > initial_delta
        assert peak_delta > final_delta

        # Velocity must accelerate in first half and decelerate in second half
        for i in range(mid_idx - 1):
            assert captured_dx[i] <= captured_dx[i + 1]
        for i in range(mid_idx, samples - 1):
            assert captured_dx[i] >= captured_dx[i + 1]


def test_mouse_look_smooth_timing_and_sleep() -> None:
    """Each sample must be followed by time.sleep with duration_ms / samples."""
    injector = Win32InputInjector()
    duration_ms = 150
    samples = 15

    with (
        patch.object(injector, "mouse_move_relative", return_value=True) as mock_rel,
        patch("time.sleep") as mock_sleep,
    ):
        res = injector.mouse_look_smooth(150, 75, duration_ms=duration_ms, samples=samples)
        assert res is True
        assert mock_rel.call_count == samples
        assert mock_sleep.call_count == samples

        expected_delay = (duration_ms / 1000.0) / samples
        for call_args in mock_sleep.call_args_list:
            actual_delay = call_args.args[0]
            assert actual_delay == pytest.approx(expected_delay, abs=1e-5)


def test_mouse_look_smooth_zero_duration() -> None:
    """When duration_ms is zero, time.sleep must not be called."""
    injector = Win32InputInjector()
    with (
        patch.object(injector, "mouse_move_relative", return_value=True),
        patch("time.sleep") as mock_sleep,
    ):
        res = injector.mouse_look_smooth(100, 50, duration_ms=0, samples=10)
        assert res is True
        mock_sleep.assert_not_called()


def test_mouse_look_smooth_single_sample() -> None:
    """When samples is 1, a single relative delta matching the total displacement is emitted."""
    injector = Win32InputInjector()
    with (
        patch.object(injector, "mouse_move_relative", return_value=True) as mock_rel,
        patch("time.sleep"),
    ):
        res = injector.mouse_look_smooth(80, -40, duration_ms=0, samples=1)
        assert res is True
        mock_rel.assert_called_once_with(80, -40)


def test_mouse_look_smooth_failure_propagation() -> None:
    """If an underlying mouse_move_relative call fails, return False while finishing execution."""
    injector = Win32InputInjector()
    side_effects = [True, True, False, True, True]

    with (
        patch.object(injector, "mouse_move_relative", side_effect=side_effects) as mock_rel,
        patch("time.sleep"),
    ):
        res = injector.mouse_look_smooth(50, 50, duration_ms=0, samples=5)
        assert res is False
        assert mock_rel.call_count == 5


def test_mouse_look_smooth_unmocked_live() -> None:
    """Live instantiation and invocation must execute cleanly on the host environment."""
    injector = Win32InputInjector()
    res = injector.mouse_look_smooth(10, -10, duration_ms=0, samples=5)
    assert res is True


def test_get_gamepad_controller_prefer_mock() -> None:
    """When prefer_mock is True, MockGamepadController is returned immediately."""
    ctrl = get_gamepad_controller(prefer_mock=True)
    assert isinstance(ctrl, MockGamepadController)
    assert ctrl.is_available is True


def test_get_gamepad_controller_fallback_when_unavailable() -> None:
    """When driver is unavailable and fallback_to_mock is True, return MockGamepadController."""
    with patch("gaming_mcp.io.gamepad.ViGEmGamepadController") as mock_cls:
        instance = MagicMock()
        instance.is_available = False
        instance.status_message = "ViGEmBus driver not installed"
        mock_cls.return_value = instance

        ctrl = get_gamepad_controller(prefer_mock=False, fallback_to_mock=True)
        assert isinstance(ctrl, MockGamepadController)
        assert ctrl.is_available is True


def test_get_gamepad_controller_no_fallback_when_unavailable() -> None:
    """When driver is unavailable and fallback_to_mock is False, return degraded real controller."""
    with patch("gaming_mcp.io.gamepad.ViGEmGamepadController") as mock_cls:
        instance = MagicMock()
        instance.is_available = False
        instance.status_message = "ViGEmBus driver not installed"
        mock_cls.return_value = instance

        ctrl = get_gamepad_controller(prefer_mock=False, fallback_to_mock=False)
        assert ctrl is instance
        assert ctrl.is_available is False


def test_get_gamepad_controller_returns_real_when_available() -> None:
    """When ViGEmBus driver is available, return the operational ViGEmGamepadController instance."""
    with patch("gaming_mcp.io.gamepad.ViGEmGamepadController") as mock_cls:
        instance = MagicMock()
        instance.is_available = True
        mock_cls.return_value = instance

        ctrl = get_gamepad_controller(prefer_mock=False, fallback_to_mock=True)
        assert ctrl is instance
        assert ctrl.is_available is True
