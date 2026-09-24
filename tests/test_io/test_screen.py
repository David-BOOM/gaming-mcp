"""Integration and unit tests for DXGI and MSS screen capturers."""

import platform
import sys

from PIL import Image

from gaming_mcp.io.screen import (
    CompositeScreenCapturer,
    DXGIScreenCapturer,
    MSSScreenCapturer,
    attach_thread_to_input_desktop,
)

IS_WINDOWS = sys.platform == "win32" or platform.system() == "Windows"


def test_attach_thread_to_input_desktop() -> None:
    """Thread desktop attachment helper must succeed or return boolean status."""
    res = attach_thread_to_input_desktop()
    assert isinstance(res, bool)


def test_mss_screen_capturer_runtime() -> None:
    """MSS capturer must acquire screen frames and support region cropping."""
    capturer = MSSScreenCapturer()
    try:
        frame = capturer.capture()
        assert isinstance(frame, Image.Image)
        assert frame.size[0] > 0
        assert frame.size[1] > 0

        # Test region crop
        cropped = capturer.capture(region=(10, 10, 100, 80))
        assert isinstance(cropped, Image.Image)
        assert cropped.size == (100, 80)
    finally:
        capturer.close()


def test_composite_screen_capturer_lifecycle_and_gating() -> None:
    """Composite capturer must prioritize DXGI/MSS, support SoM, and perform dHash delta gating."""
    capturer = CompositeScreenCapturer(prefer_dxgi=True)
    try:
        # 1. Base capture
        img = capturer.capture()
        assert isinstance(img, Image.Image)
        assert img.size[0] > 0

        # 2. Capture with Set-of-Marks grid
        som_img = capturer.capture(apply_som=True, som_spacing=100)
        assert som_img.size == img.size

        # 3. Gated capture: First frame is non-static
        raw1, b64_1, is_static1, _h1, _dist1 = capturer.capture_with_gating(
            region=(100, 100, 200, 200)
        )
        assert not is_static1
        assert raw1 is not None
        assert b64_1 is not None

        # 4. Gated capture: Successive identical frame is static
        raw2, b64_2, is_static2, _h2, dist2 = capturer.capture_with_gating(
            region=(100, 100, 200, 200)
        )
        assert is_static2
        assert raw2 is None
        assert b64_2 is None
        assert dist2 <= 3
    finally:
        capturer.close()


def test_dxgi_capturer_on_windows() -> None:
    """On Windows hosts with D3D11, DXGIScreenCapturer must be available or degrade safely."""
    capturer = DXGIScreenCapturer()
    try:
        if IS_WINDOWS and capturer.is_available:
            frame = capturer.capture()
            assert isinstance(frame, Image.Image)
            assert frame.size[0] > 0
    finally:
        capturer.close()
