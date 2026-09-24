"""Unit and integration tests for security guardrails and emergency kill-switch."""

from unittest.mock import MagicMock

import pytest

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.exceptions import SafetyKillSwitchTriggered, SecurityViolationError
from gaming_mcp.io.gamepad import MockGamepadController
from gaming_mcp.io.input import Win32InputInjector
from gaming_mcp.io.security import (
    EmergencyKillSwitch,
    ProcessBlacklistGuard,
    WindowBoundaryGuard,
)


def test_window_boundary_guard_clamping_and_validation() -> None:
    """WindowBoundaryGuard must clamp coordinates and enforce boundary checks."""
    guard = WindowBoundaryGuard(rect=(100, 100, 500, 400))
    assert guard.has_bounds is True

    # Inside bounds
    assert guard.is_within_bounds(200, 200) is True
    assert guard.clamp_coordinates(200, 200) == (200, 200)
    assert guard.validate_coordinates(200, 200, strict=True) == (200, 200)

    # Outside bounds - Clamping
    assert guard.is_within_bounds(50, 50) is False
    assert guard.clamp_coordinates(50, 50) == (100, 100)
    assert guard.clamp_coordinates(600, 500) == (499, 399)

    # Outside bounds - Non-strict clamps with log warning
    clamped = guard.validate_coordinates(50, 50, strict=False)
    assert clamped == (100, 100)

    # Outside bounds - Strict raises SecurityViolationError
    with pytest.raises(SecurityViolationError) as exc_info:
        guard.validate_coordinates(50, 50, strict=True)
    assert "window_boundary" in exc_info.value.message
    assert exc_info.value.error_code == -32004

    # Empty bounds passes through
    empty_guard = WindowBoundaryGuard()
    assert empty_guard.has_bounds is False
    assert empty_guard.validate_coordinates(999, 999, strict=True) == (999, 999)


def test_process_blacklist_guard() -> None:
    """ProcessBlacklistGuard must reject sensitive OS utilities and permit games."""
    guard = ProcessBlacklistGuard()

    # Blacklisted utilities
    assert guard.is_blacklisted("cmd.exe") is True
    assert guard.is_blacklisted("POWERSHELL.EXE") is True
    assert guard.is_blacklisted("taskmgr.exe") is True
    assert guard.is_blacklisted("credentialuibroker.exe") is True

    # Allowed game processes
    assert guard.is_blacklisted("minecraft.exe") is False
    assert guard.is_blacklisted("javaw.exe") is False
    assert guard.is_blacklisted("retroarch.exe") is False
    assert guard.is_blacklisted("portal2.exe") is False

    # Enforcement check
    with pytest.raises(SecurityViolationError) as exc_info:
        guard.assert_not_blacklisted("powershell.exe", hwnd=42)
    assert "process_blacklist" in exc_info.value.message
    assert exc_info.value.error_code == -32004

    # Allowed does not raise
    guard.assert_not_blacklisted("game.exe", hwnd=100)

    # Custom additions
    custom_guard = ProcessBlacklistGuard(additional_blacklist={"cheatengine.exe"})
    assert custom_guard.is_blacklisted("cheatengine.exe") is True


def test_emergency_kill_switch_lifecycle() -> None:
    """EmergencyKillSwitch must halt input, release motor states, and raise when active."""
    mock_injector = MagicMock(spec=Win32InputInjector)
    mock_gamepad = MockGamepadController()
    manager = CancellationManager()

    callback_called = False

    def _on_kill() -> None:
        nonlocal callback_called
        callback_called = True

    switch = EmergencyKillSwitch(
        input_injector=mock_injector,
        gamepad=mock_gamepad,
        cancellation_manager=manager,
    )
    switch.add_callback(_on_kill)

    assert switch.is_triggered is False
    switch.assert_not_triggered()

    # Trigger emergency kill-switch
    switch.trigger()

    assert switch.is_triggered is True
    assert callback_called is True
    mock_injector.release_all.assert_called_once()
    assert mock_gamepad.left_stick == (0.0, 0.0)

    # assert_not_triggered must raise SafetyKillSwitchTriggered
    with pytest.raises(SafetyKillSwitchTriggered) as exc_info:
        switch.assert_not_triggered()
    assert exc_info.value.error_code == -32005

    # Reset
    switch.reset()
    assert switch.is_triggered is False
    switch.assert_not_triggered()


def test_emergency_kill_switch_daemon_start_stop() -> None:
    """Emergency kill-switch background thread must start and stop gracefully."""
    switch = EmergencyKillSwitch(poll_interval_sec=0.01)
    started = switch.start()

    # If started on Windows, ensure it halts cleanly
    if started:
        assert switch._is_running is True
        switch.stop()
        assert switch._is_running is False
