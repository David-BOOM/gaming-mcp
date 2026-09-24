"""Image processing, encoding, and computer vision utilities.

Provides high-performance image encoding (JPEG/PNG), base64 serialization,
ACES filmic HDR-to-SDR tone mapping, Set-of-Marks (SoM) coordinate grid
overlays, and geometric region cropping.
"""

from __future__ import annotations

import base64
import io
from typing import TYPE_CHECKING, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    import numpy.typing as npt


def aces_filmic_tonemap(hdr_array: npt.NDArray[np.float32]) -> npt.NDArray[np.uint8]:
    """Apply ACES filmic tone mapping curve to HDR float RGB/RGBA buffers.

    Transforms high dynamic range linear radiance values into standard
    dynamic range (SDR) 8-bit sRGB representations.

    Parameters:
        hdr_array: Float32 array of shape (H, W, 3) or (H, W, 4) with values >= 0.0.

    Returns:
        Uint8 array of shape (H, W, 3) or (H, W, 4) in range [0, 255].
    """
    has_alpha = hdr_array.shape[2] == 4 if hdr_array.ndim == 3 else False
    if has_alpha:
        rgb = hdr_array[:, :, :3]
        alpha = hdr_array[:, :, 3:]
    else:
        rgb = hdr_array

    # ACES filmic approximation curve (Krzysztof Narkowicz, 2015)
    a = 2.51
    b = 0.03
    c = 2.43
    d = 0.59
    e = 0.14
    numerator = rgb * (a * rgb + b)
    denominator = rgb * (c * rgb + d) + e
    mapped_rgb = np.clip(numerator / np.maximum(denominator, 1e-6), 0.0, 1.0)

    # Convert linear to sRGB (gamma ~2.2 approximation)
    srgb = np.where(
        mapped_rgb <= 0.0031308,
        mapped_rgb * 12.92,
        1.055 * np.power(np.maximum(mapped_rgb, 1e-6), 1.0 / 2.4) - 0.055,
    )
    srgb_uint8 = np.clip(srgb * 255.0, 0, 255).astype(np.uint8)

    if has_alpha:
        alpha_uint8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
        return np.concatenate([srgb_uint8, alpha_uint8], axis=2)

    return srgb_uint8


def encode_image(
    image: Image.Image | npt.NDArray[np.uint8],
    image_format: Literal["jpeg", "png"] = "jpeg",
    quality: int = 85,
) -> bytes:
    """Encode an image or numpy array to JPEG or PNG bytes.

    Parameters:
        image: PIL Image or numpy array (uint8 RGBA or RGB).
        image_format: Target format ('jpeg' or 'png').
        quality: JPEG compression quality (1-100).

    Returns:
        Raw encoded image bytes.
    """
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            pil_img = Image.fromarray(image, mode="L")
        elif image.shape[2] == 4:
            pil_img = Image.fromarray(image, mode="RGBA")
        else:
            pil_img = Image.fromarray(image, mode="RGB")
    else:
        pil_img = image

    output_buffer = io.BytesIO()

    if image_format.lower() == "jpeg":
        # Convert RGBA or L to RGB for standard JPEG compliance
        if pil_img.mode != "RGB":
            rgb_img = Image.new("RGB", pil_img.size, (0, 0, 0))
            if pil_img.mode == "RGBA":
                rgb_img.paste(pil_img, mask=pil_img.split()[3])
            else:
                rgb_img.paste(pil_img)
            pil_img = rgb_img

        pil_img.save(output_buffer, format="JPEG", quality=quality, optimize=True)
    else:
        pil_img.save(output_buffer, format="PNG", optimize=False)

    return output_buffer.getvalue()


def image_to_base64(image_bytes: bytes) -> str:
    """Convert raw image bytes to an ASCII base64 encoded string."""
    return base64.b64encode(image_bytes).decode("ascii")


def base64_to_image(b64_string: str) -> Image.Image:
    """Decode a base64 string to a PIL Image instance."""
    image_bytes = base64.b64decode(b64_string)
    return Image.open(io.BytesIO(image_bytes))


def crop_region(
    image: Image.Image,
    region: tuple[int, int, int, int],
) -> Image.Image:
    """Crop an image to the specified bounding box (x, y, width, height).

    Coordinates outside the image boundaries are safely clamped.
    """
    img_width, img_height = image.size
    x, y, width, height = region

    x1 = max(0, min(x, img_width - 1))
    y1 = max(0, min(y, img_height - 1))
    x2 = max(x1 + 1, min(x + width, img_width))
    y2 = max(y1 + 1, min(y + height, img_height))

    return image.crop((x1, y1, x2, y2))


def draw_set_of_marks_grid(
    image: Image.Image,
    spacing: int = 100,
    line_color: tuple[int, int, int, int] = (255, 255, 0, 160),
    label_color: tuple[int, int, int, int] = (255, 255, 255, 240),
    label_bg_color: tuple[int, int, int, int] = (0, 0, 0, 180),
) -> Image.Image:
    """Overlay a Set-of-Marks (SoM) alphanumeric coordinate grid onto an image.

    Enhances spatial visual grounding for multimodal language models by
    superimposing coordinate lines and cell identifiers (e.g., A1, B2).

    Parameters:
        image: Base PIL image.
        spacing: Grid cell size in pixels.
        line_color: RGBA color for grid lines.
        label_color: RGBA color for marker text.
        label_bg_color: RGBA color for marker text background box.

    Returns:
        A new PIL Image with the SoM grid superimposed.
    """
    img = image.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    width, height = img.size
    font = ImageFont.load_default()

    # Draw vertical lines
    for x in range(0, width, spacing):
        draw.line([(x, 0), (x, height)], fill=line_color, width=1)

    # Draw horizontal lines
    for y in range(0, height, spacing):
        draw.line([(0, y), (width, y)], fill=line_color, width=1)

    # Draw cell tags at grid intersections
    for r, y in enumerate(range(0, height, spacing)):
        row_letter = chr(ord("A") + (r % 26))
        for c, x in enumerate(range(0, width, spacing)):
            col_number = c + 1
            label = f"{row_letter}{col_number}"

            # Calculate text bounding box
            bbox = draw.textbbox((x + 2, y + 2), label, font=font)
            bg_rect = (bbox[0] - 1, bbox[1] - 1, bbox[2] + 1, bbox[3] + 1)
            draw.rectangle(bg_rect, fill=label_bg_color)
            draw.text((x + 2, y + 2), label, fill=label_color, font=font)

    result = Image.alpha_composite(img, overlay)
    if image.mode != "RGBA":
        return result.convert(image.mode)
    return result
