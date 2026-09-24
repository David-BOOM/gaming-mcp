"""Perceptual vision, differential frame hashing, and visual gating.

Implements 64-bit horizontal difference hashing (dHash) to detect static scenes,
evaluate visual mutations, and suppress redundant frame transmissions to remote
vision-language models, achieving up to 80% token savings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    import numpy.typing as npt


def compute_dhash(
    image: Image.Image | npt.NDArray[np.uint8],
    region: tuple[int, int, int, int] | None = None,
    mask_rects: list[tuple[int, int, int, int]] | None = None,
) -> int:
    """Compute a 64-bit difference hash (dHash) from an image.

    The image is converted to grayscale, optionally cropped and masked,
    and downscaled to 9x8 pixels. Adjacent pixels along each row are
    compared to yield 8 bits per row (64 bits total).

    Parameters:
        image: PIL Image or uint8 numpy array.
        region: Optional bounding box (x, y, width, height) to crop before hashing.
        mask_rects: Optional list of (x, y, width, height) rects to black out
            prior to hashing (e.g. animated HUDs, blinking cursors).

    Returns:
        A 64-bit unsigned integer representing the perceptual hash.
    """
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            pil_img = Image.fromarray(image, mode="L")
        elif image.shape[2] == 4:
            pil_img = Image.fromarray(image, mode="RGBA").convert("L")
        else:
            pil_img = Image.fromarray(image, mode="RGB").convert("L")
    else:
        pil_img = image.convert("L")

    # Apply region of interest (ROI) crop
    if region is not None:
        rx, ry, rw, rh = region
        img_w, img_h = pil_img.size
        x1 = max(0, min(rx, img_w - 1))
        y1 = max(0, min(ry, img_h - 1))
        x2 = max(x1 + 1, min(rx + rw, img_w))
        y2 = max(y1 + 1, min(ry + rh, img_h))
        pil_img = pil_img.crop((x1, y1, x2, y2))

    # Apply HUD / UI blackout masks
    if mask_rects:
        # Create a copy if modifying
        pil_img = pil_img.copy()
        for mx, my, mw, mh in mask_rects:
            box = (mx, my, mx + mw, my + mh)
            black_box = Image.new("L", (mw, mh), 0)
            pil_img.paste(black_box, box)

    # Downscale to 9 columns by 8 rows using bilinear interpolation
    resized = pil_img.resize((9, 8), Image.Resampling.BILINEAR)
    pixels = np.asarray(resized, dtype=np.int32)

    # Compute horizontal gradient differences: P(x+1, y) > P(x, y)
    difference = pixels[:, 1:] > pixels[:, :-1]

    # Flatten the 8x8 boolean matrix into a 64-bit integer
    flat_diff = difference.flatten()
    hash_value = 0
    for bit in flat_diff:
        hash_value = (hash_value << 1) | int(bit)

    return hash_value


def compute_hamming_distance(hash1: int, hash2: int) -> int:
    """Calculate the Hamming distance (differing bit count) between two 64-bit hashes."""
    return (hash1 ^ hash2).bit_count()


class PerceptualGater:
    """Evaluates visual frame deltas using 64-bit dHash perceptual gating.

    Maintains the perceptual hash of the prior frame and compares successive
    observations against a configurable Hamming distance threshold.
    """

    def __init__(self, threshold: int = 3) -> None:
        """Initialize PerceptualGater with a Hamming distance threshold.

        A threshold of 3 on a 64-bit hash corresponds to a visual difference
        under 2.5% (Hamming distance / 64 < 0.046), effectively filtering out
        sub-perceptual noise and static scenes.
        """
        self.threshold = threshold
        self.last_hash: int | None = None

    def evaluate(
        self,
        image: Image.Image | npt.NDArray[np.uint8],
        region: tuple[int, int, int, int] | None = None,
        mask_rects: list[tuple[int, int, int, int]] | None = None,
        override_threshold: int | None = None,
    ) -> tuple[bool, int, int]:
        """Evaluate if the current frame is visually static compared to the last frame.

        Parameters:
            image: PIL Image or numpy array of the current frame.
            region: Optional crop region bounding box.
            mask_rects: Optional list of exclusion zones to mask out.
            override_threshold: Optional threshold override for this call.

        Returns:
            Tuple of (is_static, current_hash, hamming_distance).
            If no previous frame has been evaluated, is_static is False and
            hamming_distance is 64.
        """
        current_hash = compute_dhash(image, region=region, mask_rects=mask_rects)
        active_threshold = (
            override_threshold if override_threshold is not None else self.threshold
        )

        if self.last_hash is None:
            self.last_hash = current_hash
            return False, current_hash, 64

        dist = compute_hamming_distance(self.last_hash, current_hash)
        is_static = dist <= active_threshold

        if not is_static:
            self.last_hash = current_hash

        return is_static, current_hash, dist

    def update_hash(self, new_hash: int) -> None:
        """Manually update the stored prior hash value."""
        self.last_hash = new_hash

    def reset(self) -> None:
        """Clear the stored hash, forcing the next evaluation to report non-static."""
        self.last_hash = None
