"""Win32 window handles, title regex matching, focus locking, and rect queries.

Provides the spatial grounding and window identification layer for the
Universal Computer Use Adapter. Enables agents to locate game windows by title
pattern, query target viewport rects, bring games to the foreground, and
extract underlying executable process names for security verification.
"""

import ctypes
import logging
import os
import platform
import re
import sys
from ctypes import wintypes
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("gaming_mcp.io.process")

IS_WINDOWS = sys.platform == "win32" or platform.system() == "Windows"

# Win32 Window / Process Constants
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class WindowInfo(BaseModel):
    """Metadata describing an operating system window."""

    hwnd: int = Field(..., description="Win32 Window Handle")
    title: str = Field(default="", description="Window Title Text")
    class_name: str = Field(default="", description="Win32 Window Class Name")
    rect: tuple[int, int, int, int] = Field(
        default=(0, 0, 0, 0),
        description="Screen coordinates: (left, top, right, bottom)",
    )
    client_rect: tuple[int, int, int, int] = Field(
        default=(0, 0, 0, 0),
        description="Client area coordinates: (left, top, right, bottom)",
    )
    process_id: int = Field(default=0, description="Owning Process ID")
    process_name: str = Field(default="", description="Executable Image Name (e.g. game.exe)")
    is_visible: bool = Field(default=True, description="True if window is visible on desktop")

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])


class Win32WindowManager:
    """Manages window discovery, rect introspection, and focus locking on Windows."""

    def __init__(self) -> None:
        self.is_windows = IS_WINDOWS
        self._user32: Any = None
        self._kernel32: Any = None

        if self.is_windows and hasattr(ctypes, "windll"):
            self._user32 = getattr(ctypes.windll, "user32", None)
            self._kernel32 = getattr(ctypes.windll, "kernel32", None)
            if self._user32 and self._kernel32:
                self._setup_win32_signatures()

    def _setup_win32_signatures(self) -> None:
        """Configure ctypes function prototypes for user32 and kernel32."""
        # Window enumeration callback type: BOOL (HWND, LPARAM)
        self._enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        self._user32.EnumWindows.argtypes = [self._enum_proc_type, wintypes.LPARAM]
        self._user32.EnumWindows.restype = wintypes.BOOL

        self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetWindowTextW.restype = ctypes.c_int

        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int

        self._user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetClassNameW.restype = ctypes.c_int

        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL

        self._user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user32.GetWindowRect.restype = wintypes.BOOL

        self._user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user32.GetClientRect.restype = wintypes.BOOL

        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND

        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL

        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL

        self._user32.EnumDesktopWindows.argtypes = [
            wintypes.HANDLE,
            self._enum_proc_type,
            wintypes.LPARAM,
        ]
        self._user32.EnumDesktopWindows.restype = wintypes.BOOL

        self._user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._user32.OpenInputDesktop.restype = wintypes.HANDLE

        self._user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        self._user32.CloseDesktop.restype = wintypes.BOOL

        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE

        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def get_process_name(self, pid: int) -> str:
        """Resolve executable name from process ID."""
        if not self.is_windows or not self._kernel32 or pid <= 0:
            return ""

        h_proc = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            return ""

        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if self._kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                full_path = buf.value
                return os.path.basename(full_path)
            return ""
        finally:
            self._kernel32.CloseHandle(h_proc)

    def get_window_info(self, hwnd: int) -> WindowInfo | None:
        """Build WindowInfo structure for a specific window handle."""
        if not self.is_windows or not self._user32:
            return None

        # Title
        length = self._user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        else:
            title = ""

        # Class name
        class_buf = ctypes.create_unicode_buffer(256)
        self._user32.GetClassNameW(hwnd, class_buf, 256)
        class_name = class_buf.value

        # Visibility
        is_visible = bool(self._user32.IsWindowVisible(hwnd))

        # Window Rect (Left, Top, Right, Bottom)
        w_rect = wintypes.RECT()
        if self._user32.GetWindowRect(hwnd, ctypes.byref(w_rect)):
            rect = (int(w_rect.left), int(w_rect.top), int(w_rect.right), int(w_rect.bottom))
        else:
            rect = (0, 0, 0, 0)

        # Client Rect
        c_rect = wintypes.RECT()
        if self._user32.GetClientRect(hwnd, ctypes.byref(c_rect)):
            client_rect = (
                int(c_rect.left),
                int(c_rect.top),
                int(c_rect.right),
                int(c_rect.bottom),
            )
        else:
            client_rect = (0, 0, 0, 0)

        # Process ID and Name
        pid = wintypes.DWORD(0)
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_id = int(pid.value)
        process_name = self.get_process_name(process_id)

        return WindowInfo(
            hwnd=hwnd,
            title=title,
            class_name=class_name,
            rect=rect,
            client_rect=client_rect,
            process_id=process_id,
            process_name=process_name,
            is_visible=is_visible,
        )

    def list_windows(self, visible_only: bool = True) -> list[WindowInfo]:
        """List all top-level windows on the current desktop."""
        if not self.is_windows or not self._user32:
            return []

        windows: list[WindowInfo] = []

        def _enum_callback(hwnd: int, lparam: int) -> bool:
            if visible_only and not self._user32.IsWindowVisible(hwnd):
                return True

            info = self.get_window_info(hwnd)
            if info:
                windows.append(info)
            return True

        callback = self._enum_proc_type(_enum_callback)
        self._user32.EnumWindows(callback, 0)

        # If running in isolated session/thread where EnumWindows returned empty,
        # fallback to enumerating input desktop explicitly via EnumDesktopWindows
        if not windows and hasattr(self._user32, "OpenInputDesktop"):
            h_desk = self._user32.OpenInputDesktop(0, False, 0x01FF)
            if h_desk:
                try:
                    self._user32.EnumDesktopWindows(h_desk, callback, 0)
                finally:
                    self._user32.CloseDesktop(h_desk)

        return windows

    def find_windows_by_title(
        self,
        pattern: str,
        regex: bool = True,
        visible_only: bool = True,
    ) -> list[WindowInfo]:
        """Search top-level windows matching a substring or regular expression."""
        all_windows = self.list_windows(visible_only=visible_only)
        matched: list[WindowInfo] = []

        if regex:
            compiled = re.compile(pattern, re.IGNORECASE)
            for w in all_windows:
                if compiled.search(w.title):
                    matched.append(w)
        else:
            pat_lower = pattern.lower()
            for w in all_windows:
                if pat_lower in w.title.lower():
                    matched.append(w)

        return matched

    def get_foreground_window(self) -> WindowInfo | None:
        """Retrieve metadata for the currently active foreground window."""
        if not self.is_windows or not self._user32:
            return None

        raw_hwnd = self._user32.GetForegroundWindow()
        if not raw_hwnd:
            return None
        hwnd = int(raw_hwnd)
        if hwnd <= 0:
            return None
        return self.get_window_info(hwnd)

    def focus_window(self, hwnd: int) -> bool:
        """Bring window to foreground and restore if minimized."""
        if not self.is_windows or not self._user32:
            return True

        self._user32.ShowWindow(hwnd, SW_RESTORE)
        res = bool(self._user32.SetForegroundWindow(hwnd))
        return res

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        """Retrieve bounding rectangle (left, top, right, bottom) for a window handle."""
        info = self.get_window_info(hwnd)
        return info.rect if info else None


_window_manager: Win32WindowManager | None = None


def get_window_manager() -> Win32WindowManager:
    """Retrieve the singleton Win32WindowManager instance."""
    global _window_manager
    if _window_manager is None:
        _window_manager = Win32WindowManager()
    return _window_manager
