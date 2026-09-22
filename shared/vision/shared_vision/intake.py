"""AD-7's one upload-intake path, and AD-17's display derivative.

Every image byte that reaches object storage passes through `intake_image`
first — the catalogue add (`apps/api/api/catalogue.py`), the edit and bulk paths
that follow it, `scripts/ingest`, and Epic 3's scan submission. There is no
second copy of "sniff, gate, orient, strip, re-encode" anywhere, which is the
whole of AD-7: the alternative is three call sites that each remember two of
the four steps.

What it does, in order, and why the order is not negotiable:

1. **Sniff the content.** Pillow decides what the bytes are. The file name and
   the client's `content-type` are never consulted — AGENTS.md Policy forbids
   validating an upload by extension, and this dataset genuinely holds `.tif`
   files behind `.jpg` names.
2. **Gate on header dimensions, before any decode.** A 400 Mpixel refusal must
   cost a header read, not an allocation.
3. **Colour-manage, orient, strip, cap** — `pipeline.load_image`, which is the
   function the query path calls too (AD-1). ICC -> sRGB at relative
   colorimetric intent runs *first* inside it (AD-15), before the EXIF
   transpose and before the 2048px cap.
4. **Re-encode.** What is stored is bytes this process produced from raw
   pixels, never the bytes that arrived: that is what guarantees no EXIF, no
   ICC payload, no trailing archive and no polyglot survives into storage.

The stored "source" is therefore the colour-managed, 2048px-capped image rather
than the literal upload. AD-1 caps both pipelines at 2048px before anything
else, so nothing a re-index (AD-14) could use has been discarded — and keeping
the raw upload would mean keeping the unvalidated bytes AD-7 exists to refuse.
"""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFile, UnidentifiedImageError
from PIL.Image import DecompressionBombError

from shared_vision import pipeline

#: Pillow buffers an `optimize`d or `progressive` JPEG whole before writing it,
#: and raises "broken data stream when writing image file" — an `OSError`, from
#: a save, on a valid image — when the encoded scan does not fit. Its own
#: estimate is one byte per pixel at these qualities, which is fine for a
#: photograph and not for a full-bleed speckled stone: those are exactly the
#: textures that encode largest, and they are most of this catalogue.
#:
#: This raises the floor to cover any derivative the encode below can produce
#: (1280px long edge, so at most ~1.6 Mpixel). The buffer is transient, so it
#: costs nothing at rest.
#:
#: Module-level because Pillow reads it as a global at encode time. It is a
#: property of the encoder, not of the pixels: the bytes that come back are
#: identical either way — the alternative is not different output, it is a
#: raise — so this cannot introduce an index/query asymmetry and does not
#: belong in `config_hash`.
ImageFile.MAXBLOCK = 16 * 1024 * 1024

#: The re-encode quality for the retained source. High and 4:4:4, because this
#: is the asset a future re-index reads: it is not served to anybody, so bytes
#: are cheaper here than detail lost from the only copy that remains.
#:
#: **Encoded without `optimize`**, unlike the derivative, and that is a
#: robustness decision rather than a performance one. `optimize` makes Pillow
#: buffer the whole scan, and at q95 4:4:4 a 2048x2048 frame of genuinely
#: incompressible texture exceeds any fixed buffer worth allocating — a
#: measured `OSError` on a perfectly valid image, on the write of the **only
#: copy this product retains**. Without it libjpeg streams, no buffer bounds
#: the encode, and the cost is a few percent of bytes on an asset nobody
#: downloads.
SOURCE_QUALITY = 95

#: AD-17's derivative, POC-validated: 1280px long edge, a 300 KB budget, and
#: quality stepped down only for the highly-detailed textures that miss it.
#: Generated once at write time — building one on demand measured 1-3.5 s
#: against an original of up to 96 MB.
DERIVATIVE_MAX_EDGE = 1280
DERIVATIVE_QUALITY = 82
DERIVATIVE_QUALITY_STEP = 6
DERIVATIVE_MIN_QUALITY = 68
DERIVATIVE_MAX_BYTES = 300 * 1024

#: Pixel standard deviation below which a reference carries no retrievable
#: texture. Such an image matches any washed-out photo and can never be
#: reliably retrieved itself — a real property of plain tiles, not a bug, but
#: the Administrator has to know which ones are affected (FR-19).
FEATURELESS_STD = 3.0


class IntakeRefused(ValueError):
    """Base class for the two ways intake refuses bytes. Callers map it to a 4xx."""


class UnreadableImage(IntakeRefused):
    """Zero bytes, a truncated file, or something that is not an image at all."""


class ImageTooLarge(IntakeRefused):
    """Above the caller's pixel ceiling. Raised from the header, before a decode."""


class InvalidCropRect(IntakeRefused):
    """A crop rectangle with no area, or one that falls outside the image."""


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """One accepted image: the pixels, the bytes to store, and what is known of it.

    `image` is what gets embedded and what the derivative is built from —
    already colour-managed, already oriented, already stripped. `data` is what
    gets stored. They are two representations of the same accepted image and a
    caller must never mix one request's pixels with another's bytes.
    """

    image: Image.Image
    data: bytes
    #: The digest of the bytes **as uploaded**, not of `data`. It answers "is
    #: this the same file the operator sent", which is the question a duplicate
    #: check or a provenance audit asks; the re-encoded bytes are ours and
    #: their digest would only ever match our own output.
    sha256: str
    width: int
    height: int
    pixel_std: float
    featureless: bool


def intake_image(data: bytes, *, max_pixels: int = pipeline.REFERENCE_MAX_PIXELS) -> IntakeResult:
    """Validate, colour-manage, strip and re-encode one upload. AD-7's whole surface.

    `max_pixels` is the caller's trust level, not a tuning knob: a reference
    file arriving from an Administrator gets `REFERENCE_MAX_PIXELS` because the
    catalogue really does hold 185 Mpixel scans, and an untrusted scan upload
    gets the far tighter `UPLOAD_MAX_PIXELS`.

    Raises `UnreadableImage` or `ImageTooLarge`; both are `ValueError`, so a
    caller that forgets the distinction still fails closed.
    """
    if not data:
        raise UnreadableImage("the uploaded file is empty")

    # The header-only gate. `Image.open` parses the header and nothing else, so
    # this rejects a decompression bomb for the cost of a few hundred bytes.
    # Kept here rather than relying on `load_image`'s identical check because
    # the two failures need different status codes and `load_image` raises the
    # same `ValueError` the colour transform can.
    try:
        with Image.open(io.BytesIO(data)) as probe:
            pixels = probe.width * probe.height
    except DecompressionBombError as bomb:
        # Pillow's own ceiling, which sits at twice `Image.MAX_IMAGE_PIXELS`
        # and therefore above ours. Reported as "too large" rather than
        # "unreadable" because that is what it is: the header is well formed
        # and the claim it makes is the problem. It inherits from `Exception`
        # rather than `OSError`, so it has to be named — omitting it is how it
        # slips past a "corrupt file" handler and aborts a whole build.
        raise ImageTooLarge(str(bomb)) from bomb
    except (UnidentifiedImageError, OSError) as unreadable:
        raise UnreadableImage("the uploaded file is not a readable image") from unreadable

    if pixels > max_pixels:
        raise ImageTooLarge(
            f"image is {pixels / 1e6:.0f} Mpixels, above the {max_pixels / 1e6:.0f} Mpixel limit"
        )

    try:
        image = pipeline.load_image(io.BytesIO(data), max_pixels=max_pixels)
    except (UnidentifiedImageError, OSError, ValueError, DecompressionBombError) as unreadable:
        # Everything that survived the header and then failed to decode: a
        # truncated stream, a corrupt scan line, a CMYK transform that could
        # not be completed. None of it is actionable beyond "send a real file".
        raise UnreadableImage("the uploaded file could not be decoded") from unreadable

    std = float(np.asarray(image, dtype=np.float32).std())

    return IntakeResult(
        image=image,
        data=_reencode(image),
        sha256=hashlib.sha256(data).hexdigest(),
        width=image.width,
        height=image.height,
        pixel_std=round(std, 2),
        featureless=std < FEATURELESS_STD,
    )


def _reencode(image: Image.Image) -> bytes:
    """The accepted pixels, written back out as bytes this process produced."""
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=SOURCE_QUALITY, subsampling=0)
    return buf.getvalue()


def display_derivative(image: Image.Image) -> bytes:
    """AD-17's capped view: <=1280px long edge, <=300 KB, JPEG. `poc`'s recipe.

    Quality steps down by 6 from 82, clamped at 68, until the budget is met
    or the floor is reached — which bounds the tail (the worst reference
    measured 540 KB, about 1.4 s on 4G) while leaving roughly 90% of the set
    at full quality. The floor is a floor: an image that cannot reach 300 KB
    at q68 is written at q68 rather than degraded further, because a smeared
    reference image is useless for the one thing it exists for, which is a
    member of staff recognising the tile.
    """
    view = image
    if max(view.size) > DERIVATIVE_MAX_EDGE:
        k = DERIVATIVE_MAX_EDGE / max(view.size)
        view = view.resize(
            (max(1, round(view.width * k)), max(1, round(view.height * k))),
            Image.Resampling.LANCZOS,
        )

    quality = DERIVATIVE_QUALITY
    while True:
        buf = io.BytesIO()
        view.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        if buf.tell() <= DERIVATIVE_MAX_BYTES or quality <= DERIVATIVE_MIN_QUALITY:
            return buf.getvalue()
        # Clamped, not just decremented. 82 steps to 76, 70, then 64 — which is
        # *below* the floor this function's docstring and `DERIVATIVE_MIN_QUALITY`
        # both promise, and the loop's exit test would then accept it. The floor
        # is the one thing standing between a detailed texture and a reference
        # image too smeared to recognise the tile by, which is the whole reason
        # it is served.
        quality = max(DERIVATIVE_MIN_QUALITY, quality - DERIVATIVE_QUALITY_STEP)


#: The ceiling a crop rectangle's own origin coordinate may not reach. `x`/`y`
#: are normalized fractions of the image's own width/height, so `1.0` itself
#: is already outside the image no matter how small `width`/`height` are —
#: there is no pixel at fraction 1.0 of an edge.
_CROP_ORIGIN_CEILING = 1.0


def crop_to_rect(
    image: Image.Image, x: float, y: float, width: float, height: float
) -> Image.Image:
    """Story 3.2's one server-side crop execution point (AD-11).

    `x`, `y`, `width` and `height` are normalized 0-1 fractions of `image`'s
    own width/height — never absolute pixels, and never a rectangle already
    applied to the bytes on the way here (AD-11: the client sends the whole
    downscaled image and its selection, and this is the only place a pixel is
    ever cropped from it).

    Raises `InvalidCropRect` for a degenerate or out-of-bounds rectangle
    rather than clamping it: a silently clamped rectangle is a crop the
    caller never asked for and cannot see coming. This is the check
    `POST /scans` relies on — it does not repeat the arithmetic, it catches
    this exception (`apps/api/api/scan.py`).

    **Placed beside `display_derivative` rather than in `pipeline.py`.** This
    is a post-intake `PIL.Image` transform, not a step of the symmetric
    index/query boundary that module's own docstring draws: a query image is
    cropped *before* `preprocess` ever sees it, the same way a reference image
    arrives already framed by whoever photographed it. Neither pipeline crops
    on the other's behalf, so this has no twin to stay symmetric with.

    Written as a standalone, reusable function rather than inlined into the
    route that calls it today, because AD-11 names it as the function a later
    admin-facing crop step would also call — not adopted in this epic, but a
    second implementation would be exactly the asymmetry AD-1 exists to
    prevent if that day comes.
    """
    # `nan`/`inf` fail every ordinary comparison as `False` — `nan <= 0` is
    # `False` exactly as `nan > 0` is — so a bounds check written the obvious
    # way lets either slip straight through and reach `round()` below, which
    # raises an uncaught `ValueError` and turns a malformed request into a
    # `500` instead of this function's own `422`. Checked first and
    # unconditionally, before any arithmetic is done on the four values.
    if not (
        math.isfinite(x) and math.isfinite(y) and math.isfinite(width) and math.isfinite(height)
    ):
        raise InvalidCropRect("the crop rectangle is not a finite number")
    if width <= 0 or height <= 0:
        raise InvalidCropRect("the crop rectangle has zero or negative area")
    if not (0 <= x < _CROP_ORIGIN_CEILING) or not (0 <= y < _CROP_ORIGIN_CEILING):
        raise InvalidCropRect("the crop rectangle's origin is outside the image")
    if x + width > _CROP_ORIGIN_CEILING or y + height > _CROP_ORIGIN_CEILING:
        raise InvalidCropRect("the crop rectangle extends past the image")

    left = round(x * image.width)
    top = round(y * image.height)
    right = min(image.width, round((x + width) * image.width))
    bottom = min(image.height, round((y + height) * image.height))
    # A rectangle that is valid in fractional terms can still round to zero
    # width or height against a small enough image — `x` close enough to 1.0
    # can round `left` up to `image.width` itself, and clamping `right` to
    # that same edge then makes the two equal. Raised rather than repaired:
    # widening the box by a pixel it was never asked for is the same silent
    # clamp this function's own docstring refuses to do at the fractional
    # level, one level down in pixels instead.
    if right <= left or bottom <= top:
        raise InvalidCropRect("the crop rectangle rounds to no pixels")

    return image.crop((left, top, right, bottom))
