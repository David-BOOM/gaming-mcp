"""Unit tests for image utilities, encoding, tone mapping, and Set-of-Marks grid."""

import numpy as np
from PIL import Image

from gaming_mcp.utils.image import (
    aces_filmic_tonemap,
    base64_to_image,
    crop_region,
    draw_set_of_marks_grid,
    encode_image,
    image_to_base64,
)


def test_aces_filmic_tonemap() -> None:
    """ACES filmic curve must map HDR floats >= 0 to uint8 [0, 255]."""
    hdr_data = np.array([[[0.0, 0.5, 1.0], [2.0, 5.0, 10.0]]], dtype=np.float32)
    sdr = aces_filmic_tonemap(hdr_data)
    assert sdr.dtype == np.uint8
    assert sdr.shape == (1, 2, 3)
    # High HDR radiance should be compressed and clamped near 255
    assert sdr[0, 1, 2] > 200


def test_encode_and_base64_roundtrip() -> None:
    """Images encoded to JPEG/PNG and serialized to base64 must decode cleanly."""
    img = Image.new("RGB", (64, 64), (200, 50, 100))

    jpeg_bytes = encode_image(img, image_format="jpeg", quality=90)
    assert len(jpeg_bytes) > 0
    b64_str = image_to_base64(jpeg_bytes)
    assert isinstance(b64_str, str)

    decoded = base64_to_image(b64_str)
    assert decoded.size == (64, 64)

    png_bytes = encode_image(img, image_format="png")
    assert len(png_bytes) > 0


def test_crop_region_clamping() -> None:
    """Region cropping must safely clamp out-of-bounds bounding boxes."""
    img = Image.new("RGB", (100, 100), (0, 128, 255))
    cropped = crop_region(img, (-50, -50, 100, 100))
    assert cropped.size[0] <= 100
    assert cropped.size[1] <= 100


def test_draw_set_of_marks_grid() -> None:
    """Set-of-Marks overlay must draw alphanumeric grid without resizing the image."""
    img = Image.new("RGB", (400, 400), (40, 40, 40))
    som_img = draw_set_of_marks_grid(img, spacing=100)
    assert som_img.size == (400, 400)
    # The grid lines or text must have mutated some pixels
    assert np.any(np.array(som_img) != np.array(img))
