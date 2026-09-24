"""Virtual gamepad abstraction supporting ViGEmBus Xbox 360 controller emulation.

Enables analog stick precision and pressure-sensitive triggers for 3D games.
Includes guarded capability detection per MEMORY.md Case 2: if the ViGEmBus
driver or vgamepad binary wheel is absent, operations gracefully raise typed
AdapterError (-32002) with advisory instructions without failing server startup.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from gaming_mcp.core.exceptions import AdapterError

logger = logging.getLogger("gaming_mcp.io.gamepad")

# XUSB button name mappings to standardized string identifiers
STANDARD_GAMEPAD_BUTTONS: set[str] = {
    "A",
    "B",
    "X",
    "Y",
    "DPAD_UP",
    "DPAD_DOWN",
    "DPAD_LEFT",
    "DPAD_RIGHT",
    "START",
    "BACK",
    "GUIDE",
    "LEFT_THUMB",
    "RIGHT_THUMB",
    "LEFT_SHOULDER",
    "RIGHT_SHOULDER",
}


class BaseGamepadController(ABC):
    """Abstract interface for virtual gamepad controllers."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the underlying gamepad driver and device are operational."""
        ...

    @property
    @abstractmethod
    def status_message(self) -> str:
        """Advisory description of driver or device status."""
        ...

    @abstractmethod
    def set_left_stick(self, x: float, y: float) -> None:
        """Set left analog stick axes in range [-1.0, 1.0]."""
        ...

    @abstractmethod
    def set_right_stick(self, x: float, y: float) -> None:
        """Set right analog stick axes in range [-1.0, 1.0]."""
        ...

    @abstractmethod
    def set_left_trigger(self, value: float) -> None:
        """Set left analog trigger in range [0.0, 1.0]."""
        ...

    @abstractmethod
    def set_right_trigger(self, value: float) -> None:
        """Set right analog trigger in range [0.0, 1.0]."""
        ...

    def set_triggers(self, left: float, right: float) -> None:
        """Set both left and right analog triggers."""
        self.set_left_trigger(left)
        self.set_right_trigger(right)

    @abstractmethod
    def press_button(self, button: str) -> None:
        """Press a controller button."""
        ...

    @abstractmethod
    def release_button(self, button: str) -> None:
        """Release a controller button."""
        ...

    @abstractmethod
    def update(self) -> None:
        """Transmit pending axis and button states to the virtual bus."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Release all buttons and center all analog sticks to neutral."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release gamepad resources and detach virtual device."""
        ...


class ViGEmGamepadController(BaseGamepadController):
    """ViGEmBus-backed virtual Xbox 360 controller with guarded capability probe."""

    def __init__(self) -> None:
        self._available = False
        self._status = "Unchecked"
        self._gamepad: Any = None
        self._vgamepad_module: Any = None
        self._button_map: dict[str, Any] = {}
        self._held_buttons: set[str] = set()

        self._probe_vigembus()

    def _probe_vigembus(self) -> None:
        """Safely probe for vgamepad module and ViGEmBus kernel driver."""
        try:
            import vgamepad  # type: ignore[import-not-found]

            self._vgamepad_module = vgamepad
            # Instantiate Xbox 360 controller
            self._gamepad = vgamepad.VX360Gamepad()
            self._available = True
            self._status = "ViGEmBus virtual Xbox 360 gamepad operational"

            # Populate button mapping
            btn = vgamepad.XUSB_BUTTON
            self._button_map = {
                "A": btn.XUSB_GAMEPAD_A,
                "B": btn.XUSB_GAMEPAD_B,
                "X": btn.XUSB_GAMEPAD_X,
                "Y": btn.XUSB_GAMEPAD_Y,
                "DPAD_UP": btn.XUSB_GAMEPAD_DPAD_UP,
                "DPAD_DOWN": btn.XUSB_GAMEPAD_DPAD_DOWN,
                "DPAD_LEFT": btn.XUSB_GAMEPAD_DPAD_LEFT,
                "DPAD_RIGHT": btn.XUSB_GAMEPAD_DPAD_RIGHT,
                "START": btn.XUSB_GAMEPAD_START,
                "BACK": btn.XUSB_GAMEPAD_BACK,
                "GUIDE": btn.XUSB_GAMEPAD_GUIDE,
                "LEFT_THUMB": btn.XUSB_GAMEPAD_LEFT_THUMB,
                "RIGHT_THUMB": btn.XUSB_GAMEPAD_RIGHT_THUMB,
                "LEFT_SHOULDER": btn.XUSB_GAMEPAD_LEFT_SHOULDER,
                "RIGHT_SHOULDER": btn.XUSB_GAMEPAD_RIGHT_SHOULDER,
            }
            logger.info("ViGEmBus virtual Xbox 360 controller initialized successfully.")
        except ImportError:
            self._available = False
            self._status = (
                "vgamepad Python package is not installed. "
                "Install via 'uv add vgamepad' or 'pip install vgamepad'."
            )
            logger.warning("ViGEmGamepadController probe: %s", self._status)
        except Exception as exc:
            self._available = False
            self._status = (
                f"ViGEmBus driver connection failed: {exc}. "
                "Please download and install the ViGEmBus driver from "
                "https://github.com/nefarius/ViGEmBus/releases."
            )
            logger.warning("ViGEmGamepadController probe: %s", self._status)

    def _ensure_available(self) -> None:
        """Raise typed AdapterError if driver is unavailable."""
        if not self._available or self._gamepad is None:
            raise AdapterError(
                f"Virtual gamepad unavailable: {self._status}",
                error_code=-32002,
            )

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def status_message(self) -> str:
        return self._status

    def set_left_stick(self, x: float, y: float) -> None:
        self._ensure_available()
        # Clamp to [-1.0, 1.0]
        clamped_x = max(-1.0, min(1.0, float(x)))
        clamped_y = max(-1.0, min(1.0, float(y)))
        self._gamepad.left_joystick_float(x_value_float=clamped_x, y_value_float=clamped_y)

    def set_right_stick(self, x: float, y: float) -> None:
        self._ensure_available()
        clamped_x = max(-1.0, min(1.0, float(x)))
        clamped_y = max(-1.0, min(1.0, float(y)))
        self._gamepad.right_joystick_float(x_value_float=clamped_x, y_value_float=clamped_y)

    def set_left_trigger(self, value: float) -> None:
        self._ensure_available()
        clamped = max(0.0, min(1.0, float(value)))
        self._gamepad.left_trigger_float(value_float=clamped)

    def set_right_trigger(self, value: float) -> None:
        self._ensure_available()
        clamped = max(0.0, min(1.0, float(value)))
        self._gamepad.right_trigger_float(value_float=clamped)

    def press_button(self, button: str) -> None:
        self._ensure_available()
        norm = button.strip().upper()
        btn_const = self._button_map.get(norm)
        if btn_const is None:
            raise AdapterError(f"Unrecognized gamepad button: {button}")

        self._gamepad.press_button(button=btn_const)
        self._held_buttons.add(norm)

    def release_button(self, button: str) -> None:
        self._ensure_available()
        norm = button.strip().upper()
        btn_const = self._button_map.get(norm)
        if btn_const is None:
            raise AdapterError(f"Unrecognized gamepad button: {button}")

        self._gamepad.release_button(button=btn_const)
        self._held_buttons.discard(norm)

    def update(self) -> None:
        self._ensure_available()
        self._gamepad.update()

    def reset(self) -> None:
        """Reset gamepad state to neutral. Safe no-op if driver is unavailable."""
        if not self._available or self._gamepad is None:
            return

        try:
            self._gamepad.reset()
            self._gamepad.update()
            self._held_buttons.clear()
        except Exception as exc:
            logger.error("Error resetting virtual gamepad: %s", exc)

    def close(self) -> None:
        """Release gamepad and detach. Safe no-op if driver is unavailable."""
        if not self._available or self._gamepad is None:
            return

        try:
            self.reset()
        except Exception:
            pass
        finally:
            self._gamepad = None
            self._available = False
            self._status = "Closed"


class MockGamepadController(BaseGamepadController):
    """In-memory mock virtual gamepad controller for testing and dry-runs."""

    def __init__(self) -> None:
        self.left_stick: tuple[float, float] = (0.0, 0.0)
        self.right_stick: tuple[float, float] = (0.0, 0.0)
        self.left_trigger: float = 0.0
        self.right_trigger: float = 0.0
        self.held_buttons: set[str] = set()
        self.update_count: int = 0
        self.is_closed: bool = False

    @property
    def is_available(self) -> bool:
        return not self.is_closed

    @property
    def status_message(self) -> str:
        return "Mock virtual gamepad operational" if not self.is_closed else "Mock closed"

    def set_left_stick(self, x: float, y: float) -> None:
        self.left_stick = (max(-1.0, min(1.0, float(x))), max(-1.0, min(1.0, float(y))))

    def set_right_stick(self, x: float, y: float) -> None:
        self.right_stick = (max(-1.0, min(1.0, float(x))), max(-1.0, min(1.0, float(y))))

    def set_left_trigger(self, value: float) -> None:
        self.left_trigger = max(0.0, min(1.0, float(value)))

    def set_right_trigger(self, value: float) -> None:
        self.right_trigger = max(0.0, min(1.0, float(value)))

    def press_button(self, button: str) -> None:
        norm = button.strip().upper()
        if norm not in STANDARD_GAMEPAD_BUTTONS:
            raise AdapterError(f"Unrecognized gamepad button: {button}")
        self.held_buttons.add(norm)

    def release_button(self, button: str) -> None:
        norm = button.strip().upper()
        self.held_buttons.discard(norm)

    def update(self) -> None:
        self.update_count += 1

    def reset(self) -> None:
        self.left_stick = (0.0, 0.0)
        self.right_stick = (0.0, 0.0)
        self.left_trigger = 0.0
        self.right_trigger = 0.0
        self.held_buttons.clear()
        self.update_count += 1

    def close(self) -> None:
        self.reset()
        self.is_closed = True


def get_gamepad_controller(prefer_mock: bool = False) -> BaseGamepadController:
    """Factory creating an operational gamepad controller or returning a mock/guarded instance."""
    if prefer_mock:
        return MockGamepadController()

    real_controller = ViGEmGamepadController()
    if real_controller.is_available:
        return real_controller

    return real_controller
