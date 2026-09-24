"""Low-level I/O, device drivers, screen capture, and actuation subsystems."""

from gaming_mcp.io.audio import WASAPIAudioCapturer
from gaming_mcp.io.screen import (
    CompositeScreenCapturer,
    DXGIScreenCapturer,
    MSSScreenCapturer,
    attach_thread_to_input_desktop,
)
from gaming_mcp.io.vision import (
    PerceptualGater,
    compute_dhash,
    compute_hamming_distance,
)

__all__ = [
    "CompositeScreenCapturer",
    "DXGIScreenCapturer",
    "MSSScreenCapturer",
    "PerceptualGater",
    "WASAPIAudioCapturer",
    "attach_thread_to_input_desktop",
    "compute_dhash",
    "compute_hamming_distance",
]
