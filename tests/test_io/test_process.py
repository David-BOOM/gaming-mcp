"""Unit and integration tests for Win32WindowManager and WindowInfo metadata."""

import os
import sys

from gaming_mcp.io.process import Win32WindowManager, WindowInfo, get_window_manager


def test_window_info_model_and_dimensions() -> None:
    """WindowInfo must compute width and height correctly and serialize fields."""
    info = WindowInfo(
        hwnd=12345,
        title="Super Mario 64",
        class_name="RetroArchWindow",
        rect=(100, 200, 900, 800),
        client_rect=(0, 0, 800, 600),
        process_id=9999,
        process_name="retroarch.exe",
        is_visible=True,
    )
    assert info.hwnd == 12345
    assert info.title == "Super Mario 64"
    assert info.width == 800
    assert info.height == 600
    assert info.is_visible is True


def test_win32_window_manager_current_process_name() -> None:
    """WindowManager must resolve the current Python process name from PID."""
    wm = get_window_manager()
    if sys.platform == "win32":
        pid = os.getpid()
        proc_name = wm.get_process_name(pid)
        assert len(proc_name) > 0
        assert "python" in proc_name.lower() or proc_name.endswith(".exe")


def test_win32_window_manager_window_enumeration() -> None:
    """WindowManager must enumerate desktop windows and locate active foreground window."""
    wm = Win32WindowManager()
    if sys.platform != "win32":
        return

    windows = wm.list_windows(visible_only=True)
    assert isinstance(windows, list)
    assert len(windows) > 0

    # Ensure windows have valid handles and dimensions
    for w in windows[:5]:
        assert isinstance(w.hwnd, int)
        assert w.hwnd > 0
        assert isinstance(w.rect, tuple)
        assert len(w.rect) == 4

    # Foreground window
    fg = wm.get_foreground_window()
    if fg is not None:
        assert isinstance(fg.hwnd, int)
        assert fg.hwnd > 0
        rect = wm.get_window_rect(fg.hwnd)
        assert rect == fg.rect


def test_win32_window_manager_search_by_title() -> None:
    """Search by title must support both regex and substring matching."""
    wm = Win32WindowManager()
    if sys.platform != "win32":
        return

    # Search for common top-level windows
    all_visible = wm.list_windows(visible_only=True)
    if not all_visible:
        return

    sample = all_visible[0]
    if sample.title:
        # Exact substring search
        sub = sample.title[: min(len(sample.title), 5)]
        matches_sub = wm.find_windows_by_title(sub, regex=False)
        assert any(w.hwnd == sample.hwnd for w in matches_sub)

        # Regex search
        import re

        escaped = re.escape(sub)
        matches_regex = wm.find_windows_by_title(f".*{escaped}.*", regex=True)
        assert any(w.hwnd == sample.hwnd for w in matches_regex)
