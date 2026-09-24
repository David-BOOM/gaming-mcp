"""Low-level I/O, device drivers, screen capture, and actuation subsystems."""

from gaming_mcp.io.audio import WASAPIAudioCapturer
from gaming_mcp.io.gamepad import (
    BaseGamepadController,
    MockGamepadController,
    ViGEmGamepadController,
    get_gamepad_controller,
)
from gaming_mcp.io.input import Win32InputInjector
from gaming_mcp.io.screen import (
    CompositeScreenCapturer,
    DXGIScreenCapturer,
    MSSScreenCapturer,
    attach_thread_to_input_desktop,
)
from gaming_mcp.io.timing import (
    ActionChunk,
    ActionChunkItem,
    ActionChunkScheduler,
)
from gaming_mcp.io.vision import (
    PerceptualGater,
    compute_dhash,
    compute_hamming_distance,
)

__all__ = [
    "ActionChunk",
    "ActionChunkItem",
    "ActionChunkScheduler",
    "BaseGamepadController",
    "CompositeScreenCapturer",
    "DXGIScreenCapturer",
    "MSSScreenCapturer",
    "MockGamepadController",
    "PerceptualGater",
    "ViGEmGamepadController",
    "WASAPIAudioCapturer",
    "Win32InputInjector",
    "attach_thread_to_input_desktop",
    "compute_dhash",
    "compute_hamming_distance",
    "get_gamepad_controller",
]
