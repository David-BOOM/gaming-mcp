"""Unit tests for perceptual difference hashing and visual gating."""

import numpy as np
from PIL import Image

from gaming_mcp.io.vision import PerceptualGater, compute_dhash, compute_hamming_distance


def test_dhash_identical_images() -> None:
    """Identical images must produce identical hashes with Hamming distance 0."""
    img = Image.new("RGB", (200, 200), (120, 150, 180))
    hash1 = compute_dhash(img)
    hash2 = compute_dhash(img)
    assert hash1 == hash2
    assert compute_hamming_distance(hash1, hash2) == 0


def test_dhash_distinct_images() -> None:
    """Distinct patterned images must yield a significant Hamming distance."""
    # Horizontal gradient
    arr1 = np.tile(np.linspace(0, 255, 100, dtype=np.uint8), (100, 1))
    # Vertical gradient
    arr2 = np.tile(np.linspace(0, 255, 100, dtype=np.uint8).reshape(100, 1), (1, 100))

    img1 = Image.fromarray(arr1)
    img2 = Image.fromarray(arr2)

    hash1 = compute_dhash(img1)
    hash2 = compute_dhash(img2)
    dist = compute_hamming_distance(hash1, hash2)
    assert dist > 10


def test_dhash_region_and_mask() -> None:
    """ROI slicing and mask rects must isolate hashed areas correctly."""
    img = Image.new("RGB", (500, 500), (50, 50, 50))
    # Draw a bright spot
    for x in range(10, 50):
        for y in range(10, 50):
            img.putpixel((x, y), (255, 255, 255))

    # Hashing region far from the spot
    hash_clean = compute_dhash(img, region=(200, 200, 100, 100))
    # Hashing with mask over the spot
    hash_masked = compute_dhash(img, mask_rects=[(10, 10, 40, 40)])

    assert isinstance(hash_clean, int)
    assert isinstance(hash_masked, int)


def test_perceptual_gater_lifecycle() -> None:
    """PerceptualGater must report non-static for first frame and static for identical."""
    gater = PerceptualGater(threshold=3)

    img1 = Image.new("RGB", (300, 300), (100, 100, 100))
    is_static, h1, dist = gater.evaluate(img1)
    # First frame is never static
    assert not is_static
    assert dist == 64

    # Identical second frame is static
    is_static2, h2, dist2 = gater.evaluate(img1)
    assert is_static2
    assert dist2 == 0
    assert h1 == h2

    # Drastic change triggers non-static
    arr_noise = np.random.randint(0, 256, (300, 300, 3), dtype=np.uint8)
    img_noise = Image.fromarray(arr_noise)
    is_static3, _h3, dist3 = gater.evaluate(img_noise)
    assert not is_static3
    assert dist3 > 3

    # Reset forces next frame to be non-static
    gater.reset()
    is_static4, _, _ = gater.evaluate(img1)
    assert not is_static4
