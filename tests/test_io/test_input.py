"""Unit and integration tests for Win32 SendInput hardware scan-code injector."""

import pytest

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.io.input import PS2_SCAN_CODES, Win32InputInjector


def test_ps2_scan_code_table_resolution() -> None:
    """Verify hardware scan codes for standard and extended keyboard keys."""
    injector = Win32InputInjector()

    # Standard 1-byte keys
    sc_w, ext_w = injector.resolve_scan_code("w")
    assert sc_w == 0x11
    assert not ext_w

    sc_space, ext_space = injector.resolve_scan_code("space")
    assert sc_space == 0x39
    assert not ext_space

    sc_esc, ext_esc = injector.resolve_scan_code("escape")
    assert sc_esc == 0x01
    assert not ext_esc

    # Extended 2-byte keys (e.g. arrow keys, right ctrl, windows key)
    sc_up, ext_up = injector.resolve_scan_code("up")
    assert sc_up == 0x48
    assert ext_up

    sc_rctrl, ext_rctrl = injector.resolve_scan_code("rctrl")
    assert sc_rctrl == 0x1D
    assert ext_rctrl

    sc_win, ext_win = injector.resolve_scan_code("win")
    assert sc_win == 0x5B
    assert ext_win

    # Verify all predefined entries in PS2_SCAN_CODES have valid non-zero codes
    for name, (code, _) in PS2_SCAN_CODES.items():
        assert code > 0, f"Scan code for {name} must be positive"


def test_input_injector_key_tracking_and_release() -> None:
    """Held keys must be accurately tracked in held_keys set and cleared on release_all."""
    injector = Win32InputInjector()

    assert len(injector.held_keys) == 0

    injector.key_down("w")
    injector.key_down("shift")
    assert "w" in injector.held_keys
    assert "shift" in injector.held_keys
    assert len(injector.held_keys) == 2

    injector.key_up("w")
    assert "w" not in injector.held_keys
    assert "shift" in injector.held_keys

    # Press key with hold duration
    injector.press_key("a", hold_duration_ms=10.0, jitter_std_ms=1.0)
    # After press_key, key must be released
    assert "a" not in injector.held_keys

    # Release all
    injector.release_all()
    assert len(injector.held_keys) == 0


def test_input_injector_mouse_tracking_and_actions() -> None:
    """Mouse buttons must be tracked in held_mouse_buttons and cleared on release_all."""
    injector = Win32InputInjector()

    assert len(injector.held_mouse_buttons) == 0

    injector.mouse_down("left")
    assert "left" in injector.held_mouse_buttons

    injector.mouse_down("right")
    assert "right" in injector.held_mouse_buttons
    assert len(injector.held_mouse_buttons) == 2

    injector.mouse_up("left")
    assert "left" not in injector.held_mouse_buttons
    assert "right" in injector.held_mouse_buttons

    injector.release_all()
    assert len(injector.held_mouse_buttons) == 0


def test_mouse_motion_and_drag() -> None:
    """Mouse relative and absolute motion and drag commands must execute without error."""
    injector = Win32InputInjector()

    # Relative movement
    assert injector.mouse_move_relative(0, 0) is True

    # Absolute movement
    pos = injector.get_cursor_position()
    assert isinstance(pos, tuple)
    assert len(pos) == 2

    # Smooth movement
    assert (
        injector.mouse_move_smooth(pos[0], pos[1], duration_ms=20.0, steps=3, use_bezier=False)
        is True
    )

    # Click with modifier
    assert injector.mouse_click(button="left", modifiers=["shift"]) is True

    # Drag
    assert (
        injector.mouse_drag(
            pos[0], pos[1], pos[0], pos[1], button="left", duration_ms=20.0, steps=3
        )
        is True
    )

    # Emergency release
    injector.release_all()
    assert len(injector.held_keys) == 0
    assert len(injector.held_mouse_buttons) == 0


@pytest.mark.asyncio
async def test_input_injector_cancellation_manager_integration() -> None:
    """CancellationManager emergency reset must invoke injector.release_all."""
    injector = Win32InputInjector()
    manager = CancellationManager()

    injector.attach_to_cancellation_manager(manager)

    injector.key_down("w")
    injector.key_down("d")
    injector.mouse_down("left")

    assert len(injector.held_keys) == 2
    assert len(injector.held_mouse_buttons) == 1

    # Trigger emergency reset on cancellation manager
    await manager.emergency_reset()

    assert len(injector.held_keys) == 0
    assert len(injector.held_mouse_buttons) == 0
