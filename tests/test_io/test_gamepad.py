"""Unit and mock tests for virtual gamepad controllers and ViGEmBus wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from gaming_mcp.core.exceptions import AdapterError
from gaming_mcp.io.gamepad import (
    MockGamepadController,
    ViGEmGamepadController,
    get_gamepad_controller,
)


def test_mock_gamepad_controller_axes_and_triggers() -> None:
    """MockGamepadController must record and clamp stick axes and trigger inputs."""
    pad = MockGamepadController()
    assert pad.is_available
    assert "Mock virtual gamepad operational" in pad.status_message

    # Sticks
    pad.set_left_stick(0.75, -0.5)
    assert pad.left_stick == (0.75, -0.5)

    # Clamping test
    pad.set_left_stick(2.0, -3.0)
    assert pad.left_stick == (1.0, -1.0)

    # Triggers
    pad.set_left_trigger(0.8)
    pad.set_right_trigger(1.5)
    assert pad.left_trigger == 0.8
    assert pad.right_trigger == 1.0  # Clamped

    # Reset
    pad.reset()
    assert pad.left_stick == (0.0, 0.0)
    assert pad.right_stick == (0.0, 0.0)
    assert pad.left_trigger == 0.0
    assert pad.right_trigger == 0.0

    # Close
    pad.close()
    assert not pad.is_available


def test_mock_gamepad_controller_buttons() -> None:
    """MockGamepadController must track button states and reject invalid buttons."""
    pad = MockGamepadController()

    pad.press_button("A")
    pad.press_button("DPAD_UP")
    assert "A" in pad.held_buttons
    assert "DPAD_UP" in pad.held_buttons

    pad.release_button("A")
    assert "A" not in pad.held_buttons
    assert "DPAD_UP" in pad.held_buttons

    # Invalid button must raise AdapterError
    with pytest.raises(AdapterError) as exc_info:
        pad.press_button("INVALID_BUTTON_NAME")
    assert "Unrecognized gamepad button" in str(exc_info.value)

    pad.reset()
    assert len(pad.held_buttons) == 0


def test_vigem_gamepad_controller_unavailable_degradation() -> None:
    """When vgamepad or ViGEmBus is missing, operations raise typed AdapterError."""
    # Instantiating directly when vgamepad is uninstalled in the host venv
    controller = ViGEmGamepadController()
    if not controller.is_available:
        assert "vgamepad" in controller.status_message or "ViGEmBus" in controller.status_message

        with pytest.raises(AdapterError) as exc_info:
            controller.set_left_stick(0.5, 0.5)
        assert exc_info.value.error_code == -32002
        assert "Virtual gamepad unavailable" in str(exc_info.value)

        with pytest.raises(AdapterError):
            controller.press_button("A")

        # Reset and close must be safe no-ops
        controller.reset()
        controller.close()


def test_vigem_gamepad_controller_mocked_driver() -> None:
    """When vgamepad module and driver are active, controller correctly dispatches inputs."""
    mock_vx360 = MagicMock()
    mock_vgamepad = MagicMock()
    mock_vgamepad.VX360Gamepad.return_value = mock_vx360
    mock_vgamepad.XUSB_BUTTON.XUSB_GAMEPAD_A = 0x1000
    mock_vgamepad.XUSB_BUTTON.XUSB_GAMEPAD_B = 0x2000

    with patch.dict("sys.modules", {"vgamepad": mock_vgamepad}):
        pad = ViGEmGamepadController()
        assert pad.is_available
        assert "operational" in pad.status_message

        # Analog sticks
        pad.set_left_stick(0.5, -0.5)
        mock_vx360.left_joystick_float.assert_called_with(x_value_float=0.5, y_value_float=-0.5)

        pad.set_right_stick(0.2, 0.8)
        mock_vx360.right_joystick_float.assert_called_with(x_value_float=0.2, y_value_float=0.8)

        # Triggers
        pad.set_left_trigger(0.9)
        mock_vx360.left_trigger_float.assert_called_with(value_float=0.9)

        pad.set_right_trigger(0.4)
        mock_vx360.right_trigger_float.assert_called_with(value_float=0.4)

        # Buttons
        pad.press_button("A")
        mock_vx360.press_button.assert_called_with(button=0x1000)

        pad.release_button("A")
        mock_vx360.release_button.assert_called_with(button=0x1000)

        # Update
        pad.update()
        mock_vx360.update.assert_called_once()

        # Unrecognized button
        with pytest.raises(AdapterError):
            pad.press_button("NONEXISTENT_BUTTON")

        # Reset and close
        pad.reset()
        mock_vx360.reset.assert_called_once()

        pad.close()
        assert not pad.is_available


def test_get_gamepad_controller_factory() -> None:
    """Factory helper must honor prefer_mock flag."""
    mock_pad = get_gamepad_controller(prefer_mock=True)
    assert isinstance(mock_pad, MockGamepadController)
    assert mock_pad.is_available
