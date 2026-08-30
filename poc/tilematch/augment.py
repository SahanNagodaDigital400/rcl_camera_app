"""Index-time view sampling and augmentation.

This runs ABOVE the vision.py boundary: it produces plain PIL images that are
then fed through the same `preprocess -> embed` path as any query. Augmentation
is index-only by definition, which is how it coexists with AD-1's requirement
that the shared function be symmetric.

Two problems are being solved here.

Scale. Reference scans are full-bleed textures up to 14457px. A phone photo
captures a fraction of one tile at a completely different scale. Squashing a
whole scan into 224px destroys exactly the fine texture that separates these
products, so each reference contributes several cropped views instead.

Domain gap. References are studio assets; queries are phone photos under shop
lighting. CLAUDE.md names the four families to simulate: lighting, white
balance, blur, perspective. JPEG recompression is added because every phone
photo arrives lossy.
"""

from __future__ import annotations

import hashlib
import io
import random

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

# Crop scale range, as a fraction of the image's short edge. A staff photo of a
# tile face lands roughly in this band relative to the full scan.
CROP_SCALE_MIN = 0.25
CROP_SCALE_MAX = 0.60

VIEWS_PER_IMAGE = 16
CANONICAL_VIEWS = 4  # the 4 rotations of the full frame, unaugmented


def _seed_for(key: str) -> int:
    """Deterministic per-image seed so an index build is reproducible."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def _random_crop(img: Image.Image, rng: random.Random) -> Image.Image:
    short = min(img.size)
    side = int(short * rng.uniform(CROP_SCALE_MIN, CROP_SCALE_MAX))
    side = max(64, min(side, short))
    left = rng.randint(0, max(0, img.width - side))
    top = rng.randint(0, max(0, img.height - side))
    return img.crop((left, top, left + side, top + side))


def _lighting(img: Image.Image, rng: random.Random) -> Image.Image:
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.65, 1.35))
    return ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 1.30))


def _white_balance(img: Image.Image, rng: random.Random) -> Image.Image:
    """Per-channel gain — warm tungsten through cool daylight."""
    r, g, b = img.split()
    gains = (rng.uniform(0.85, 1.18), rng.uniform(0.92, 1.08), rng.uniform(0.85, 1.18))
    r, g, b = (ch.point(lambda v, k=k: min(255, int(v * k))) for ch, k in zip((r, g, b), gains))
    return Image.merge("RGB", (r, g, b))


def _blur(img: Image.Image, rng: random.Random) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 1.8)))


def _perspective(img: Image.Image, rng: random.Random) -> Image.Image:
    """Mild off-axis warp — a staff photo is never perfectly square-on."""
    w, h = img.size
    j = rng.uniform(0.02, 0.09)
    corners = [
        (rng.uniform(0, w * j), rng.uniform(0, h * j)),
        (w - rng.uniform(0, w * j), rng.uniform(0, h * j)),
        (w - rng.uniform(0, w * j), h - rng.uniform(0, h * j)),
        (rng.uniform(0, w * j), h - rng.uniform(0, h * j)),
    ]
    coeffs = _perspective_coeffs(corners, [(0, 0), (w, 0), (w, h), (0, h)])
    return img.transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)


def _perspective_coeffs(src, dst):
    """Solve the 8 coefficients mapping dst -> src for Image.PERSPECTIVE."""
    matrix = []
    for (sx, sy), (dx, dy) in zip(src, dst):
        matrix.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        matrix.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
    a = np.array(matrix, dtype=np.float64)
    b = np.array(src, dtype=np.float64).reshape(8)
    return np.linalg.solve(a, b).tolist()


def _jpeg(img: Image.Image, rng: random.Random) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=rng.randint(40, 78))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


AUGMENTATIONS = (_lighting, _white_balance, _blur, _perspective, _jpeg)


def generate_views(img: Image.Image, key: str, n: int = VIEWS_PER_IMAGE) -> list[Image.Image]:
    """One reference image -> n views covering rotation, scale, position, optics.

    Views are sampled randomly rather than as a full cross-product: a 6-crop x
    4-rotation x 3-augmentation grid is 72 embeddings per image, and at ~490 ms
    each that is hours. Random sampling covers the same space for a fixed
    budget, and the per-image seed keeps it reproducible.

    Rotation is baked into the index rather than applied as query-time TTA. Both
    place the invariance somewhere; putting it here costs offline index time
    once instead of 4x latency on every user-facing scan.
    """
    rng = random.Random(_seed_for(key))
    views: list[Image.Image] = []

    # Baseline coverage: the whole tile at each of the 4 orientations, clean.
    for k in range(CANONICAL_VIEWS):
        views.append(img.rotate(90 * k, expand=True) if k else img)

    while len(views) < n:
        v = _random_crop(img, rng)
        k = rng.randint(0, 3)
        if k:
            v = v.rotate(90 * k, expand=True)
        for aug in rng.sample(AUGMENTATIONS, rng.randint(1, 3)):
            v = aug(v, rng)
        views.append(v)

    return views[:n]


def synthesize_query(img: Image.Image, seed: int) -> Image.Image:
    """Fake a phone photo from a studio scan, for the synthetic eval only.

    Deliberately harsher than `generate_views`: a tighter crop, always warped,
    always blurred, always recompressed, then downscaled to ~1024px the way the
    client does. Still an optimistic stand-in for a real staff photo — the
    lighting, sensor and optics of an actual phone are not modelled here.
    """
    rng = random.Random(seed)
    short = min(img.size)
    side = int(short * rng.uniform(0.30, 0.60))
    left = rng.randint(0, max(0, img.width - side))
    top = rng.randint(0, max(0, img.height - side))
    q = img.crop((left, top, left + side, top + side))

    k = rng.randint(0, 3)
    if k:
        q = q.rotate(90 * k, expand=True)

    q = _perspective(q, rng)
    q = _lighting(q, rng)
    q = _white_balance(q, rng)
    q = _blur(q, rng)

    if max(q.size) > 1024:  # mirrors the client-side canvas downscale (AD-2)
        s = 1024 / max(q.size)
        q = q.resize((max(1, int(q.width * s)), max(1, int(q.height * s))), Image.Resampling.BICUBIC)

    return _jpeg(q, rng)
