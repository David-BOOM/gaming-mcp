"""Security guardrails, Win32 64-bit safety, and kill-switch latching tests."""

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Any
from unittest.mock import patch

import pytest

from gaming_mcp.core.exceptions import SafetyKillSwitchTriggered, SecurityViolationError
from gaming_mcp.io.input import (
    INPUT,
    KEYBDINPUT,
    MOUSEINPUT,
    InputUnion,
    Win32InputInjector,
)
from gaming_mcp.io.process import Win32WindowManager
from gaming_mcp.io.security import (
    EmergencyKillSwitch,
    ProcessBlacklistGuard,
)
from gaming_mcp.io.timing import ActionChunk, ActionChunkItem, ActionChunkScheduler


def test_default_blacklist_includes_modern_shells() -> None:
    """Verify modern terminals, WSL, and system utilities are blacklisted."""
    guard = ProcessBlacklistGuard()
    must_block = [
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "taskmgr.exe",
        "credentialuibroker.exe",
        "regedit.exe",
        "mmc.exe",
        "explorer.exe",
        "conhost.exe",
        "wt.exe",
        "openconsole.exe",
        "wsl.exe",
        "bash.exe",
        "consent.exe",
        "rundll32.exe",
    ]
    for proc in must_block:
        assert guard.is_blacklisted(proc) is True
        assert guard.is_blacklisted(proc.replace(".exe", "")) is True
        assert guard.is_blacklisted(f"C:\\Windows\\System32\\{proc}") is True

    # Safe processes
    assert guard.is_blacklisted("game.exe") is False
    assert guard.is_blacklisted("retroarch.exe") is False
    assert guard.is_blacklisted("javaw.exe") is False


def test_win32_input_injector_locking() -> None:
    """Input injector must lock and reject actuation calls when locked."""
    injector = Win32InputInjector()
    assert injector.is_locked is False

    injector.lock()
    assert injector.is_locked is True

    # Key down when locked must raise SafetyKillSwitchTriggered
    with pytest.raises(SafetyKillSwitchTriggered):
        injector.key_down("w")

    # Absolute mouse movement when locked must raise SafetyKillSwitchTriggered
    with pytest.raises(SafetyKillSwitchTriggered):
        injector.mouse_move_absolute(100, 100)

    # Relative mouse move when locked must raise SafetyKillSwitchTriggered
    with pytest.raises(SafetyKillSwitchTriggered):
        injector.mouse_move_relative(10, 10)

    # Unlock restores normal functionality
    injector.unlock()
    assert injector.is_locked is False


def test_win32_input_injector_release_allowed_when_locked() -> None:
    """Key and mouse button release operations must succeed even when locked."""
    injector = Win32InputInjector()
    injector.lock()
    assert injector.is_locked is True

    # Key up and mouse up must not raise SafetyKillSwitchTriggered
    assert injector.key_up("w") is True
    assert injector.mouse_up("left") is True

    # Emergency release_all must execute cleanly while locked
    injector.release_all()
    assert len(injector.held_keys) == 0
    assert len(injector.held_mouse_buttons) == 0

    injector.unlock()


def test_win32_input_injector_all_actuation_blocked_when_locked() -> None:
    """All high-level and low-level input actuation methods must be blocked when locked."""
    injector = Win32InputInjector()
    injector.lock()

    actuation_calls = [
        lambda: injector.key_down("a"),
        lambda: injector.mouse_down("left"),
        lambda: injector.mouse_move_absolute(50, 50),
        lambda: injector.mouse_move_relative(10, -10),
        lambda: injector.press_key("space", hold_duration_ms=10),
        lambda: injector.send_keys(["x"]),
        lambda: injector.mouse_click(100, 100),
        lambda: injector.mouse_drag(10, 10, 50, 50, duration_ms=20, steps=2),
    ]

    for call in actuation_calls:
        with pytest.raises(SafetyKillSwitchTriggered):
            call()

    injector.unlock()


def test_emergency_kill_switch_locks_injector() -> None:
    """EmergencyKillSwitch.trigger() must lock the injector, and reset() must unlock it."""
    injector = Win32InputInjector()
    kill_switch = EmergencyKillSwitch(input_injector=injector)

    assert kill_switch.is_triggered is False
    assert injector.is_locked is False

    kill_switch.trigger()
    assert kill_switch.is_triggered is True
    assert injector.is_locked is True

    with pytest.raises(SafetyKillSwitchTriggered):
        kill_switch.assert_not_triggered()

    kill_switch.reset()
    assert kill_switch.is_triggered is False
    assert injector.is_locked is False
    kill_switch.assert_not_triggered()


@pytest.mark.asyncio
async def test_action_chunk_scheduler_halts_on_kill_switch() -> None:
    """ActionChunkScheduler must halt execution if kill-switch is triggered."""
    injector = Win32InputInjector()
    kill_switch = EmergencyKillSwitch(input_injector=injector)
    scheduler = ActionChunkScheduler(
        input_injector=injector,
        kill_switch=kill_switch,
    )

    # Trigger kill switch prior to chunk execution
    kill_switch.trigger()

    chunk = ActionChunk(
        actions=[
            ActionChunkItem(offset_ms=0, type="key_down", params={"key": "w"}),
            ActionChunkItem(offset_ms=50, type="key_up", params={"key": "w"}),
        ],
        total_duration_ms=60,
    )

    res = await scheduler.execute_chunk(chunk)
    assert res["status"] == "cancelled"
    assert "kill-switch" in res["reason"].lower() or "locked" in res["reason"].lower()


def test_win32_64bit_ctypes_structure_sizes_and_alignment() -> None:
    """Verify Win32 ctypes structures adhere to x64 alignment and byte-size standards."""
    is_64bit = sys.maxsize > 2**32
    if is_64bit:
        # Win32 INPUT union on 64-bit: 8-byte aligned, 40 bytes total
        assert ctypes.sizeof(INPUT) == 40
        assert ctypes.sizeof(MOUSEINPUT) == 32
        assert ctypes.sizeof(KEYBDINPUT) == 24
        assert ctypes.sizeof(InputUnion) == 32

        # PROCESSENTRY32W on 64-bit with 8-byte th32DefaultHeapID pointer: 568 bytes
        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        assert ctypes.sizeof(PROCESSENTRY32W) == 568


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
def test_win32_window_manager_ctypes_signatures_and_snapshot() -> None:
    """Verify Win32 ctypes signatures and Toolhelp32 process snapshot fallback."""
    wm = Win32WindowManager()
    assert wm.is_windows is True
    assert wm._user32 is not None
    assert wm._kernel32 is not None

    # Verify ClientToScreen and MapWindowPoints prototypes
    assert hasattr(wm._user32, "ClientToScreen")
    assert hasattr(wm._user32, "MapWindowPoints")

    # Verify process resolution for current process
    pid = os.getpid()
    proc_name = wm.get_process_name(pid)
    assert len(proc_name) > 0
    assert "python" in proc_name.lower() or proc_name.endswith(".exe")

    # Verify snapshot fallback method directly
    snap_name = wm._get_process_name_via_snapshot(pid)
    assert len(snap_name) > 0
    assert "python" in snap_name.lower() or snap_name.endswith(".exe")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
def test_elevated_process_openprocess_failure_fallback_to_snapshot() -> None:
    """When OpenProcess returns NULL due to elevated privileges, fallback to snapshot succeeds."""
    wm = Win32WindowManager()
    assert wm._kernel32 is not None
    pid = os.getpid()

    # Simulate OpenProcess failing with NULL/0 (e.g. ERROR_ACCESS_DENIED)
    with patch.object(wm._kernel32, "OpenProcess", return_value=0):
        resolved_name = wm.get_process_name(pid)
        assert len(resolved_name) > 0
        assert "python" in resolved_name.lower() or resolved_name.endswith(".exe")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
def test_elevated_process_blacklist_enforcement() -> None:
    """ProcessBlacklistGuard correctly blocks elevated processes resolved via snapshot fallback."""
    wm = Win32WindowManager()
    guard = ProcessBlacklistGuard()

    # Mock get_process_name returning an elevated system process
    with patch.object(wm, "get_process_name", return_value="taskmgr.exe"):
        name = wm.get_process_name(99999)
        assert guard.is_blacklisted(name) is True

        with pytest.raises(SecurityViolationError):
            guard.assert_not_blacklisted(name, hwnd=123)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
def test_client_rect_screen_coordinate_mapping_real_window() -> None:
    """WindowManager maps client rect to desktop screen coordinates using ClientToScreen."""
    wm = Win32WindowManager()
    windows = wm.list_windows(visible_only=True)

    tested = False
    for w in windows:
        if w.width > 200 and w.height > 200 and not w.is_minimized:
            # Client rect in screen coordinates must lie within the outer window bounding rect
            assert w.client_rect[0] >= w.rect[0]
            assert w.client_rect[1] >= w.rect[1]
            assert w.client_rect[2] <= w.rect[2]
            assert w.client_rect[3] <= w.rect[3]
            tested = True
            break

    assert tested, "At least one non-minimized desktop window must be available for testing"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
def test_client_rect_screen_coordinate_mapping_mock() -> None:
    """Verify ClientToScreen translates client (0, 0, width, height) to absolute screen coords."""
    wm = Win32WindowManager()
    assert wm._user32 is not None

    def fake_get_window_rect(h: int, ref: Any) -> bool:
        r = ctypes.cast(ref, ctypes.POINTER(wintypes.RECT)).contents
        r.left = 100
        r.top = 200
        r.right = 900
        r.bottom = 800
        return True

    def fake_get_client_rect(h: int, ref: Any) -> bool:
        r = ctypes.cast(ref, ctypes.POINTER(wintypes.RECT)).contents
        r.left = 0
        r.top = 0
        r.right = 784
        r.bottom = 561
        return True

    def fake_client_to_screen(h: int, ref: Any) -> bool:
        pt = ctypes.cast(ref, ctypes.POINTER(wintypes.POINT)).contents
        pt.x += 108
        pt.y += 231
        return True

    with (
        patch.object(wm._user32, "GetWindowRect", side_effect=fake_get_window_rect),
        patch.object(wm._user32, "GetClientRect", side_effect=fake_get_client_rect),
        patch.object(wm._user32, "ClientToScreen", side_effect=fake_client_to_screen),
    ):
        info = wm.get_window_info(54321)
        assert info is not None
        assert info.rect == (100, 200, 900, 800)
        # Client rect must be offset to absolute screen coordinates: (108, 231, 892, 792)
        assert info.client_rect == (108, 231, 892, 792)
