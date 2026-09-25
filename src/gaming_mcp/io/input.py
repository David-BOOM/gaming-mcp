"""Win32 SendInput PS/2 hardware scan-code injector and mouse controller.

DirectX and Vulkan games frequently read raw input from DirectInput or
Raw Input APIs, ignoring synthetic user-space GDI messages (e.g. WM_KEYDOWN).
This module uses Win32 SendInput with KEYEVENTF_SCANCODE to dispatch
hardware scan codes directly into the Windows input subsystem.

Includes Gaussian keypress duration jitter, minimum-jerk cursor splining,
and atomic motor safety reset for MCP cancellation tokens.
"""

import concurrent.futures
import ctypes
import logging
import platform
import random
import sys
import threading
import time
from collections.abc import Sequence
from ctypes import wintypes
from typing import Any

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.utils.curves import (
    estimate_fitts_duration,
    generate_cubic_bezier_path,
    generate_minimum_jerk_path,
    generate_relative_camera_deltas,
)

logger = logging.getLogger("gaming_mcp.io.input")

IS_WINDOWS = sys.platform == "win32" or platform.system() == "Windows"

# Win32 SendInput Constants
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

MAPVK_VK_TO_VSC = 0
MAPVK_VSC_TO_VK = 1
MAPVK_VK_TO_CHAR = 2
MAPVK_VK_TO_VSC_EX = 4


# Win32 Ctypes Structures
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", InputUnion),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


# PS/2 Set 1 Hardware Scan Code Table
# Maps lowercase key name -> (scan_code: int, is_extended: bool)
PS2_SCAN_CODES: dict[str, tuple[int, bool]] = {
    # Alphanumeric
    "escape": (0x01, False),
    "esc": (0x01, False),
    "1": (0x02, False),
    "2": (0x03, False),
    "3": (0x04, False),
    "4": (0x05, False),
    "5": (0x06, False),
    "6": (0x07, False),
    "7": (0x08, False),
    "8": (0x09, False),
    "9": (0x0A, False),
    "0": (0x0B, False),
    "-": (0x0C, False),
    "=": (0x0D, False),
    "backspace": (0x0E, False),
    "tab": (0x0F, False),
    "q": (0x10, False),
    "w": (0x11, False),
    "e": (0x12, False),
    "r": (0x13, False),
    "t": (0x14, False),
    "y": (0x15, False),
    "u": (0x16, False),
    "i": (0x17, False),
    "o": (0x18, False),
    "p": (0x19, False),
    "[": (0x1A, False),
    "]": (0x1B, False),
    "enter": (0x1C, False),
    "return": (0x1C, False),
    "ctrl": (0x1D, False),
    "control": (0x1D, False),
    "lctrl": (0x1D, False),
    "rctrl": (0x1D, True),
    "a": (0x1E, False),
    "s": (0x1F, False),
    "d": (0x20, False),
    "f": (0x21, False),
    "g": (0x22, False),
    "h": (0x23, False),
    "j": (0x24, False),
    "k": (0x25, False),
    "l": (0x26, False),
    ";": (0x27, False),
    "'": (0x28, False),
    "`": (0x29, False),
    "shift": (0x2A, False),
    "lshift": (0x2A, False),
    "rshift": (0x36, False),
    "\\": (0x2B, False),
    "z": (0x2C, False),
    "x": (0x2D, False),
    "c": (0x2E, False),
    "v": (0x2F, False),
    "b": (0x30, False),
    "n": (0x31, False),
    "m": (0x32, False),
    ",": (0x33, False),
    ".": (0x34, False),
    "/": (0x35, False),
    "alt": (0x38, False),
    "lalt": (0x38, False),
    "ralt": (0x38, True),
    "space": (0x39, False),
    "capslock": (0x3A, False),
    # Function keys
    "f1": (0x3B, False),
    "f2": (0x3C, False),
    "f3": (0x3D, False),
    "f4": (0x3E, False),
    "f5": (0x3F, False),
    "f6": (0x40, False),
    "f7": (0x41, False),
    "f8": (0x42, False),
    "f9": (0x43, False),
    "f10": (0x44, False),
    "f11": (0x57, False),
    "f12": (0x58, False),
    # Navigation / Cursor (Extended)
    "home": (0x47, True),
    "up": (0x48, True),
    "pageup": (0x49, True),
    "pgup": (0x49, True),
    "left": (0x4B, True),
    "right": (0x4D, True),
    "end": (0x4F, True),
    "down": (0x50, True),
    "pagedown": (0x51, True),
    "pgdn": (0x51, True),
    "insert": (0x52, True),
    "delete": (0x53, True),
    # Windows / Meta
    "win": (0x5B, True),
    "windows": (0x5B, True),
    "super": (0x5B, True),
}


_input_executor: concurrent.futures.ThreadPoolExecutor | None = None
_input_executor_lock = threading.Lock()


def get_input_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Retrieve or initialize the dedicated single-threaded input worker executor.

    Isolates SendInput and SetThreadDesktop from audio/multimedia libraries (sounddevice)
    which initialize hidden COM window hooks that lock the calling thread with ERROR_BUSY (170).
    """
    global _input_executor
    with _input_executor_lock:
        if _input_executor is None:
            _input_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="gaming_mcp_input",
            )
            if IS_WINDOWS:
                from gaming_mcp.io.screen import attach_thread_to_input_desktop

                _input_executor.submit(attach_thread_to_input_desktop).result()
        return _input_executor


def shutdown_input_executor() -> None:
    """Shutdown dedicated input worker thread executor."""
    global _input_executor
    with _input_executor_lock:
        if _input_executor is not None:
            _input_executor.shutdown(wait=True)
            _input_executor = None


class Win32InputInjector:
    """Dispatches hardware scan codes and mouse movements via Win32 SendInput."""

    def __init__(self) -> None:
        self._held_keys: set[str] = set()
        self._held_mouse_buttons: set[str] = set()
        self._lock = threading.Lock()
        self.is_windows = IS_WINDOWS

        self._user32: Any = None
        if self.is_windows and hasattr(ctypes, "windll"):
            self._user32 = getattr(ctypes.windll, "user32", None)
            if self._user32:
                self._setup_user32_signatures()
                get_input_executor()

    def _send_input(self, inp: INPUT) -> bool:
        """Dispatch SendInput with automatic input-desktop re-attachment on ERROR_ACCESS_DENIED."""
        if not self.is_windows or not self._user32:
            return True

        def _do_send() -> bool:
            res = self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            if res == 0 and ctypes.GetLastError() == 5:
                from gaming_mcp.io.screen import attach_thread_to_input_desktop

                if attach_thread_to_input_desktop():
                    res = self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            return bool(res == 1)

        try:
            return get_input_executor().submit(_do_send).result()
        except Exception as exc:
            logger.error("Error executing SendInput on input worker thread: %s", exc)
            return False

    def _setup_user32_signatures(self) -> None:
        """Configure argtypes and restype for user32 SendInput and helper functions."""
        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT

        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL

        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL

        self._user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        self._user32.MapVirtualKeyW.restype = wintypes.UINT

        self._user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
        self._user32.VkKeyScanW.restype = wintypes.SHORT

    def resolve_scan_code(self, key: str) -> tuple[int, bool]:
        """Resolve a key string to (ps2_scan_code, is_extended)."""
        normalized = key.strip().lower()

        if normalized in PS2_SCAN_CODES:
            return PS2_SCAN_CODES[normalized]

        if self.is_windows and self._user32 and len(normalized) == 1:
            vk = self._user32.VkKeyScanW(normalized) & 0xFF
            if vk != 0xFF:
                sc = self._user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
                if sc != 0:
                    return sc, False

        # Fallback to ASCII ordinal if unmapped
        return ord(normalized[0]) if normalized else 0x00, False

    def key_down(self, key: str) -> bool:
        """Inject a hardware scan-code key down event and track active hold."""
        scan_code, is_extended = self.resolve_scan_code(key)

        with self._lock:
            self._held_keys.add(key.lower())

        if not self.is_windows or not self._user32:
            logger.debug("Non-Windows key_down: %s (scan=0x%02X)", key, scan_code)
            return True

        flags = KEYEVENTF_SCANCODE
        if is_extended:
            flags |= KEYEVENTF_EXTENDEDKEY

        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki.wVk = 0
        inp.u.ki.wScan = scan_code
        inp.u.ki.dwFlags = flags
        inp.u.ki.time = 0
        inp.u.ki.dwExtraInfo = 0

        return self._send_input(inp)

    def key_up(self, key: str) -> bool:
        """Inject a hardware scan-code key up event and clear active hold."""
        scan_code, is_extended = self.resolve_scan_code(key)

        with self._lock:
            self._held_keys.discard(key.lower())

        if not self.is_windows or not self._user32:
            logger.debug("Non-Windows key_up: %s (scan=0x%02X)", key, scan_code)
            return True

        flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
        if is_extended:
            flags |= KEYEVENTF_EXTENDEDKEY

        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki.wVk = 0
        inp.u.ki.wScan = scan_code
        inp.u.ki.dwFlags = flags
        inp.u.ki.time = 0
        inp.u.ki.dwExtraInfo = 0

        return self._send_input(inp)

    def press_key(
        self,
        key: str,
        hold_duration_ms: float | None = None,
        jitter_std_ms: float = 6.0,
    ) -> bool:
        """Inject a key down, wait with Gaussian duration jitter, then inject key up."""
        base_duration = 55.0 if hold_duration_ms is None else float(hold_duration_ms)

        # Apply Gaussian duration jitter (mean = base_duration, std = jitter_std_ms)
        duration_ms = max(10.0, random.gauss(base_duration, jitter_std_ms))

        down_ok = self.key_down(key)
        time.sleep(duration_ms / 1000.0)
        up_ok = self.key_up(key)
        return down_ok and up_ok

    def send_keys(
        self,
        keys: list[str] | Sequence[str] | str,
        hold_duration_ms: float = 100.0,
        repeat_count: int = 1,
    ) -> bool:
        """Inject discrete keystrokes with specified hold duration and repetitions."""
        key_list = [keys] if isinstance(keys, str) else list(keys)

        success = True
        for _ in range(max(1, repeat_count)):
            for k in key_list:
                ok = self.press_key(k, hold_duration_ms=hold_duration_ms)
                if not ok:
                    success = False
        return success

    def mouse_move_relative(self, dx: int, dy: int) -> bool:
        """Inject a relative mouse motion event (MOUSEEVENTF_MOVE). Essential for 3D camera."""
        if not self.is_windows or not self._user32:
            logger.debug("Non-Windows mouse_move_relative: dx=%d, dy=%d", dx, dy)
            return True

        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi.dx = dx
        inp.u.mi.dy = dy
        inp.u.mi.mouseData = 0
        inp.u.mi.dwFlags = MOUSEEVENTF_MOVE
        inp.u.mi.time = 0
        inp.u.mi.dwExtraInfo = 0

        return self._send_input(inp)

    def mouse_move_absolute(self, x: int, y: int) -> bool:
        """Set absolute mouse cursor position."""
        if not self.is_windows or not self._user32:
            logger.debug("Non-Windows mouse_move_absolute: x=%d, y=%d", x, y)
            return True

        try:
            return bool(
                get_input_executor().submit(lambda: self._user32.SetCursorPos(x, y)).result()
            )
        except Exception as exc:
            logger.error("Error setting cursor position: %s", exc)
            return False

    def get_cursor_position(self) -> tuple[int, int]:
        """Retrieve current cursor screen position."""
        if not self.is_windows or not self._user32:
            return 0, 0

        def _get_pos() -> tuple[int, int]:
            pt = POINT()
            if self._user32.GetCursorPos(ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
            return 0, 0

        try:
            return get_input_executor().submit(_get_pos).result()
        except Exception as exc:
            logger.error("Error getting cursor position: %s", exc)
            return 0, 0

    def mouse_move_smooth(
        self,
        target_x: int,
        target_y: int,
        duration_ms: float | None = None,
        steps: int = 20,
        use_bezier: bool = True,
        jitter_std: float = 0.5,
    ) -> bool:
        """Move cursor smoothly to target coordinates using minimum-jerk or Bezier trajectory."""
        start_x, start_y = self.get_cursor_position()
        dist = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5

        if duration_ms is None:
            duration_ms = estimate_fitts_duration(dist)

        if use_bezier:
            path = generate_cubic_bezier_path(
                (start_x, start_y),
                (target_x, target_y),
                steps=steps,
                jitter_std=jitter_std,
            )
        else:
            path = generate_minimum_jerk_path(
                (start_x, start_y),
                (target_x, target_y),
                steps=steps,
                jitter_std=jitter_std,
            )

        step_delay = (duration_ms / 1000.0) / max(1, len(path) - 1)
        for pt in path:
            self.mouse_move_absolute(pt[0], pt[1])
            time.sleep(step_delay)

        return True

    def mouse_look_smooth(
        self,
        total_dx: int,
        total_dy: int,
        duration_ms: int = 100,
        samples: int = 15,
    ) -> bool:
        """Rotate 3D camera smoothly using minimum-jerk relative mouse deltas.

        Slices total_dx and total_dy into discrete relative increments via
        generate_relative_camera_deltas, maintaining human-like motor acceleration
        and deceleration curves across 3D first-person views.

        Args:
            total_dx: Total horizontal relative mouse delta in counts/pixels.
            total_dy: Total vertical relative mouse delta in counts/pixels.
            duration_ms: Total duration of the camera rotation in milliseconds.
            samples: Number of discrete interpolation sample steps.

        Returns:
            True if all relative mouse events were dispatched successfully, False otherwise.
        """
        if total_dx == 0 and total_dy == 0:
            return True

        deltas = generate_relative_camera_deltas(
            total_dx,
            total_dy,
            samples=max(1, samples),
        )

        step_delay = (max(0, duration_ms) / 1000.0) / max(1, len(deltas))
        success = True

        for dx, dy in deltas:
            if not self.mouse_move_relative(dx, dy):
                success = False
            if step_delay > 0:
                time.sleep(step_delay)

        return success

    def mouse_down(self, button: str = "left") -> bool:
        """Inject mouse button down event."""
        btn = button.lower()
        with self._lock:
            self._held_mouse_buttons.add(btn)

        if not self.is_windows or not self._user32:
            logger.debug("Non-Windows mouse_down: %s", btn)
            return True

        flag = {
            "left": MOUSEEVENTF_LEFTDOWN,
            "right": MOUSEEVENTF_RIGHTDOWN,
            "middle": MOUSEEVENTF_MIDDLEDOWN,
        }.get(btn, MOUSEEVENTF_LEFTDOWN)

        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi.dx = 0
        inp.u.mi.dy = 0
        inp.u.mi.mouseData = 0
        inp.u.mi.dwFlags = flag
        inp.u.mi.time = 0
        inp.u.mi.dwExtraInfo = 0

        return self._send_input(inp)

    def mouse_up(self, button: str = "left") -> bool:
        """Inject mouse button up event."""
        btn = button.lower()
        with self._lock:
            self._held_mouse_buttons.discard(btn)

        if not self.is_windows or not self._user32:
            logger.debug("Non-Windows mouse_up: %s", btn)
            return True

        flag = {
            "left": MOUSEEVENTF_LEFTUP,
            "right": MOUSEEVENTF_RIGHTUP,
            "middle": MOUSEEVENTF_MIDDLEUP,
        }.get(btn, MOUSEEVENTF_LEFTUP)

        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi.dx = 0
        inp.u.mi.dy = 0
        inp.u.mi.mouseData = 0
        inp.u.mi.dwFlags = flag
        inp.u.mi.time = 0
        inp.u.mi.dwExtraInfo = 0

        return self._send_input(inp)

    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        modifiers: Sequence[str] | None = None,
    ) -> bool:
        """Execute a mouse click at current or target position, with optional held modifiers."""
        if x is not None and y is not None:
            self.mouse_move_absolute(x, y)

        mods = [m.lower() for m in (modifiers or [])]
        for m in mods:
            self.key_down(m)

        down_ok = self.mouse_down(button)
        # Small click hold delay: 35-50ms
        time.sleep(random.uniform(0.035, 0.050))
        up_ok = self.mouse_up(button)

        for m in reversed(mods):
            self.key_up(m)

        return down_ok and up_ok

    def mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str = "left",
        duration_ms: float = 300.0,
        steps: int = 25,
    ) -> bool:
        """Execute a smooth mouse drag between start and end screen coordinates."""
        self.mouse_move_absolute(start_x, start_y)
        time.sleep(0.02)
        self.mouse_down(button)
        time.sleep(0.02)

        self.mouse_move_smooth(
            end_x,
            end_y,
            duration_ms=duration_ms,
            steps=steps,
            use_bezier=True,
        )

        time.sleep(0.02)
        self.mouse_up(button)
        return True

    def release_all(self) -> None:
        """Emergency motor safety reset: release all tracked keys and mouse buttons."""
        with self._lock:
            keys_to_release = list(self._held_keys)
            buttons_to_release = list(self._held_mouse_buttons)

        for key in keys_to_release:
            try:
                self.key_up(key)
            except Exception as exc:
                logger.error("Error releasing held key %s: %s", key, exc)

        for btn in buttons_to_release:
            try:
                self.mouse_up(btn)
            except Exception as exc:
                logger.error("Error releasing held mouse button %s: %s", btn, exc)

        with self._lock:
            self._held_keys.clear()
            self._held_mouse_buttons.clear()

        logger.info("Motor safety reset complete: all keys and mouse buttons released.")

    def attach_to_cancellation_manager(self, manager: CancellationManager) -> None:
        """Register the release_all callback with an MCP CancellationManager."""
        manager.register_callback(self.release_all)

    @property
    def held_keys(self) -> set[str]:
        """Return a copy of currently depressed keys."""
        with self._lock:
            return set(self._held_keys)

    @property
    def held_mouse_buttons(self) -> set[str]:
        """Return a copy of currently depressed mouse buttons."""
        with self._lock:
            return set(self._held_mouse_buttons)
