"""Security guardrails: window boundary clipping, process blacklist, and kill-switch.

Autonomous agents operating with operating-system-level input injection pose
security risks to the host environment. This module enforces three safety envelopes:
1. Window Boundary Isolation: Clamps or rejects mouse coordinates falling outside
   the target game window rect, preventing unintentional taskbar clicks or OS interactions.
2. Protected Process Blacklisting: Refuses interaction or focus locking on sensitive
   system utilities (e.g. cmd.exe, powershell.exe, Taskmgr.exe, credential managers).
3. Emergency Hardware Kill-Switch: A background daemon monitoring a physical key combination
   (Ctrl + Alt + Shift + Pause/Break) that instantaneously severs input injection,
   releases all held physical/virtual keys, and aborts running action chunks.
"""

import ctypes
import logging
import platform
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.exceptions import SafetyKillSwitchTriggered, SecurityViolationError
from gaming_mcp.io.gamepad import BaseGamepadController, get_gamepad_controller
from gaming_mcp.io.input import Win32InputInjector

logger = logging.getLogger("gaming_mcp.io.security")

IS_WINDOWS = sys.platform == "win32" or platform.system() == "Windows"

# Default Blacklisted System Processes
DEFAULT_BLACKLIST: set[str] = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "taskmgr.exe",
    "credentialuibroker.exe",
    "regedit.exe",
    "mmc.exe",
    "explorer.exe",
    "conhost.exe",
}

# Win32 Virtual Key Codes for Kill-Switch
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_PAUSE = 0x13  # Pause/Break


class WindowBoundaryGuard:
    """Clamps or rejects mouse cursor coordinates outside the target game window."""

    def __init__(self, rect: tuple[int, int, int, int] | None = None) -> None:
        self.rect: tuple[int, int, int, int] = rect or (0, 0, 0, 0)

    def set_rect(self, rect: tuple[int, int, int, int]) -> None:
        """Update active window bounding rectangle (left, top, right, bottom)."""
        self.rect = rect

    @property
    def has_bounds(self) -> bool:
        """Return True if a non-zero bounding rectangle is configured."""
        return self.rect != (0, 0, 0, 0) and (self.rect[2] > self.rect[0])

    def is_within_bounds(self, x: int, y: int) -> bool:
        """Check if (x, y) coordinates fall inside the active window rectangle."""
        if not self.has_bounds:
            return True

        left, top, right, bottom = self.rect
        return bool(left <= x < right and top <= y < bottom)

    def clamp_coordinates(self, x: int, y: int) -> tuple[int, int]:
        """Clamp (x, y) coordinates to remain inside the active window rectangle."""
        if not self.has_bounds:
            return x, y

        left, top, right, bottom = self.rect
        clamped_x = max(left, min(right - 1, x))
        clamped_y = max(top, min(bottom - 1, y))
        return clamped_x, clamped_y

    def validate_coordinates(
        self,
        x: int,
        y: int,
        strict: bool = False,
    ) -> tuple[int, int]:
        """Validate coordinates, raising SecurityViolationError if strict or clamping."""
        if not self.has_bounds:
            return x, y

        if not self.is_within_bounds(x, y):
            if strict:
                raise SecurityViolationError(
                    "window_boundary",
                    f"Coordinates ({x}, {y}) fall outside window bounds {self.rect}",
                )
            clamped = self.clamp_coordinates(x, y)
            logger.warning(
                "Window boundary clipping applied: (%d, %d) clamped to (%d, %d)",
                x,
                y,
                clamped[0],
                clamped[1],
            )
            return clamped

        return x, y


class ProcessBlacklistGuard:
    """Blocks interaction with sensitive operating system processes."""

    def __init__(self, additional_blacklist: set[str] | None = None) -> None:
        self._blacklist: set[str] = {p.lower() for p in DEFAULT_BLACKLIST}
        if additional_blacklist:
            self._blacklist.update(p.lower() for p in additional_blacklist)

    def is_blacklisted(self, process_name: str) -> bool:
        """Return True if process_name matches any blacklisted executable."""
        if not process_name:
            return False
        return process_name.strip().lower() in self._blacklist

    def assert_not_blacklisted(self, process_name: str, hwnd: int | None = None) -> None:
        """Raise SecurityViolationError if process is blacklisted."""
        if self.is_blacklisted(process_name):
            hwnd_info = f" (hwnd={hwnd})" if hwnd is not None else ""
            raise SecurityViolationError(
                "process_blacklist",
                f"Access to protected system process '{process_name}'{hwnd_info} "
                "is denied by security policy.",
            )


class EmergencyKillSwitch:
    """Monitors global physical kill-switch shortcut (Ctrl+Alt+Shift+Pause/Break)."""

    def __init__(
        self,
        input_injector: Win32InputInjector | None = None,
        gamepad: BaseGamepadController | None = None,
        cancellation_manager: CancellationManager | None = None,
        poll_interval_sec: float = 0.02,
    ) -> None:
        self.input_injector = input_injector or Win32InputInjector()
        self.gamepad = gamepad or get_gamepad_controller()
        self.cancellation_manager = cancellation_manager
        self.poll_interval_sec = poll_interval_sec

        self._is_triggered = False
        self._is_running = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._callbacks: list[Callable[[], None]] = []
        self._user32: Any = None

        if IS_WINDOWS and hasattr(ctypes, "windll"):
            self._user32 = getattr(ctypes.windll, "user32", None)
            if self._user32:
                self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
                self._user32.GetAsyncKeyState.restype = wintypes.SHORT

    @property
    def is_triggered(self) -> bool:
        """Return True if emergency kill-switch was triggered."""
        with self._lock:
            return self._is_triggered

    def add_callback(self, callback: Callable[[], None]) -> None:
        """Register custom callback to execute upon kill-switch activation."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def trigger(self) -> None:
        """Manually trigger emergency kill-switch."""
        with self._lock:
            if self._is_triggered:
                return
            self._is_triggered = True

        logger.critical(
            "EMERGENCY HARDWARE KILL-SWITCH TRIGGERED: Halting all input actuation immediately."
        )

        # 1. Release all keyboard and mouse keys
        try:
            self.input_injector.release_all()
        except Exception as exc:
            logger.error("Error releasing keys on kill-switch trigger: %s", exc)

        # 2. Reset virtual gamepad
        try:
            self.gamepad.reset()
        except Exception as exc:
            logger.error("Error resetting gamepad on kill-switch trigger: %s", exc)

        # 3. Fire cancellation manager emergency reset if configured
        if self.cancellation_manager is not None:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                _task = loop.create_task(self.cancellation_manager.emergency_reset())
                # Add background task reference to avoid garbage collection
                _ = _task
            except RuntimeError:
                # No running event loop in thread; execute reset directly
                asyncio.run(self.cancellation_manager.emergency_reset())

        # 4. Fire registered callbacks
        for cb in self._callbacks:
            try:
                cb()
            except Exception as exc:
                logger.error("Error running kill-switch callback: %s", exc)

    def reset(self) -> None:
        """Reset triggered state after security remediation."""
        with self._lock:
            self._is_triggered = False

    def assert_not_triggered(self) -> None:
        """Raise SafetyKillSwitchTriggered if kill-switch is active."""
        if self.is_triggered:
            raise SafetyKillSwitchTriggered(
                "Emergency hardware kill-switch is active. Input actuation is locked."
            )

    def start(self) -> bool:
        """Start background daemon monitoring physical key combo."""
        if not IS_WINDOWS or not self._user32:
            logger.debug("Non-Windows or missing user32: kill-switch daemon not started.")
            return False

        with self._lock:
            if self._is_running:
                return True
            self._is_running = True

        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="gaming_mcp_killswitch",
            daemon=True,
        )
        self._thread.start()
        logger.info("Emergency kill-switch daemon started (Ctrl+Alt+Shift+Pause/Break).")
        return True

    def stop(self) -> None:
        """Stop background daemon monitoring thread."""
        with self._lock:
            self._is_running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    def _monitor_loop(self) -> None:
        """Polling loop inspecting physical key states via GetAsyncKeyState."""
        while True:
            with self._lock:
                if not self._is_running:
                    break

            # High bit (0x8000) indicates key is currently depressed
            ctrl_down = bool(self._user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
            alt_down = bool(self._user32.GetAsyncKeyState(VK_MENU) & 0x8000)
            shift_down = bool(self._user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
            pause_down = bool(self._user32.GetAsyncKeyState(VK_PAUSE) & 0x8000)

            if ctrl_down and alt_down and shift_down and pause_down:
                self.trigger()

            time.sleep(self.poll_interval_sec)
