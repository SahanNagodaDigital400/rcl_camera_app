"""Scan quality guidance — FR-9's retake gate, AD-12's enforcement point.

`POST /scans` crops the submitted photo server-side (Story 3.2,
`intake.crop_to_rect`) and, until this module, discarded the result with no
quality signal at all. This is that signal: one score, checked against one
named threshold, on the cropped region and nothing else.

**One metric, not two.** Epics.md's AC names a single "blur/framing bound",
not a blur check and a separate framing check. Variance of the Laplacian is
the standard sharpness heuristic — high-frequency edge content is what a
focused photo has and a blurred one doesn't — and a poorly-framed crop (a
wall, an out-of-focus background, a hand over the lens) shares exactly the
same missing-high-frequency-texture signature. One number against one bound
covers both without inventing an unvalidated second detector.

**Runs on the cropped region only (AD-12).** A blurry background outside the
crop must never block a scan the user has already framed correctly — the
caller (`apps/api/api/scan.py`) calls `blur_score`/`passes_quality` on
`crop_to_rect`'s own return, never on the pre-crop upload.

**The threshold is a documented placeholder, not a measured one.** No POC or
catalogue data calibrates this bound — PRD OQ-13 explicitly defers the real
number to the Foundation build and the Phase 2 pilot. `DEFAULT_SCAN_QUALITY_THRESHOLD`
is a widely-cited variance-of-Laplacian starting point for "clearly blurry",
chosen only so the mechanism ships and is trivially retunable without a code
change — never a claim about this catalogue's real accuracy trade-off.

Read once at import, `pipeline.GREY_WORLD`'s own pattern: a runtime env read
per request would let the bound drift mid-process, which is not what "a
process restart picks up the new value" (the AC's own wording) asks for.
"""

from __future__ import annotations

import logging
import math
import os

import numpy as np
from PIL import Image

#: Named the way `api.throttle`'s and its siblings are — an explicit
#: `rocell.` prefix rather than `__name__` — so a deployment can filter or
#: raise the level of every `rocell.*` logger with one rule.
logger = logging.getLogger("rocell.shared_vision.quality")

#: The environment variable that overrides `DEFAULT_SCAN_QUALITY_THRESHOLD`.
#: Changing it requires a process restart to take effect (read once, below,
#: `pipeline.GREY_WORLD`'s pattern) — never a per-request re-read.
SCAN_QUALITY_THRESHOLD_ENV = "TILEMATCH_SCAN_QUALITY_THRESHOLD"

#: A documented, uncalibrated placeholder — PRD OQ-13 defers the real number
#: to the Foundation build and the Phase 2 pilot. 100.0 is a widely-cited
#: variance-of-Laplacian starting point for "clearly blurry" against an
#: 8-bit grayscale image; it exists so the gate has *some* bound to ship
#: with, not because this catalogue's real accuracy trade-off is known.
DEFAULT_SCAN_QUALITY_THRESHOLD = 100.0


def _read_threshold() -> float:
    """`SCAN_QUALITY_THRESHOLD_ENV`'s value, falling back to the default.

    An operator's typo must not crash every import of `shared_vision` — a
    package half the product depends on — so a value `float()` cannot parse
    is caught rather than left to raise, and the default is used instead.

    `float()` itself is not strict enough to stop there: it happily parses
    `"nan"`, `"inf"` and `"-inf"` with no error at all. A `nan` threshold
    would fail *every* scan (every comparison against `nan` is `False`,
    including `>=`) and an `inf`/`-inf` one would fail or pass *every* scan
    outright — silently, with no warning and no real bound in effect — so
    both are rejected by `math.isfinite` exactly as a parse failure is.

    Either failure is logged rather than swallowed: this is the one bound
    standing between a real refusal and a scan that never should have
    passed, or a stuck gate refusing every legitimate one.
    """
    raw = os.environ.get(SCAN_QUALITY_THRESHOLD_ENV)
    if raw is None:
        return DEFAULT_SCAN_QUALITY_THRESHOLD

    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using the default threshold (%s) instead",
            SCAN_QUALITY_THRESHOLD_ENV,
            raw,
            DEFAULT_SCAN_QUALITY_THRESHOLD,
        )
        return DEFAULT_SCAN_QUALITY_THRESHOLD

    if not math.isfinite(value):
        logger.warning(
            "%s=%r is not a finite number; using the default threshold (%s) instead",
            SCAN_QUALITY_THRESHOLD_ENV,
            raw,
            DEFAULT_SCAN_QUALITY_THRESHOLD,
        )
        return DEFAULT_SCAN_QUALITY_THRESHOLD

    return value


#: The bound `passes_quality` gates against by default. Read once at import —
#: exactly `pipeline.GREY_WORLD`'s own pattern — so the value in effect for
#: the life of a process is fixed at start-up, and the AC's "the process
#: restarts" is what makes a new value take hold, not a later `os.environ`
#: mutation.
SCAN_QUALITY_THRESHOLD = _read_threshold()


def blur_score(image: Image.Image) -> float:
    """Grayscale variance of a 3x3 Laplacian. Higher is sharper/more textured.

    Computed with shifted-array arithmetic against the image's own interior —
    no `scipy.ndimage`, no `cv2` — over the classic edge-detecting kernel::

        0  1  0
        1 -4  1
        0  1  0

    Returns `0.0` for an image under 3px on either edge rather than raising:
    the interior this kernel needs does not exist below that size, and a
    degenerate crop is exactly the kind of input `passes_quality` must fail
    closed on rather than crash on (the I/O matrix's own "degenerate crop
    dimensions" row).
    """
    if image.width < 3 or image.height < 3:
        return 0.0

    gray = np.asarray(image.convert("L"), dtype=np.float64)

    center = gray[1:-1, 1:-1]
    up = gray[:-2, 1:-1]
    down = gray[2:, 1:-1]
    left = gray[1:-1, :-2]
    right = gray[1:-1, 2:]
    laplacian = up + down + left + right - 4.0 * center

    return float(laplacian.var())


def passes_quality(image: Image.Image, *, threshold: float = SCAN_QUALITY_THRESHOLD) -> bool:
    """`True` when `image`'s `blur_score` meets or clears `threshold`.

    `threshold` defaults to the module-level `SCAN_QUALITY_THRESHOLD` bound at
    *definition* time — a test that wants a different bound in the same
    process passes one explicitly rather than mutating the module global,
    which `apps/api` never needs to do since it always calls this with the
    default.
    """
    return blur_score(image) >= threshold
