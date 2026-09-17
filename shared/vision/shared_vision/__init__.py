"""The shared vision module — preprocessing and embedding for BOTH pipelines.

SKELETON. Nothing here embeds anything yet; the pipeline arrives with Epic 2,
ported from `poc/tilematch/vision.py`. What this module does carry today is the
invariant that every later change to it must respect.

AD-1 — the single most important invariant in this codebase
-----------------------------------------------------------
Index-time and query-time preprocessing and embedding must be byte-for-byte
identical. They live here, in one module, and both callers use it unwrapped::

    Index time:  ReferenceImage -> preprocess -> embed -> pgvector
    Scan time:   phone photo    -> preprocess -> embed -> search -> top 3

`apps/api` (scan) and `scripts/ingest` (index) call the *same* functions with no
wrapping, forking or reimplementation on either side. Any asymmetry silently
destroys match accuracy: it raises no error, fails no test that does not look
for it, and shows up only as a quietly worse top-3 number.

Layering, which resolves a tension the planning docs leave open::

    view selection / augmentation      (index-time only, ABOVE the boundary)
    ---------------------------- PIL.Image boundary -----------------------
    load_image -> preprocess -> embed  (this module, symmetric)

Augmentation is index-only by definition, so it lives above the boundary and
hands a plain image down. Everything below the boundary is identical on both
sides.

Colour management (AD-15) is part of preprocessing and belongs below the
boundary too: roughly 60% of the reference catalogue is CMYK press files, and a
naive RGB conversion discards the embedded ICC profile and corrupts the
embedding.

Planned surfaces, not present yet
---------------------------------
Beyond `preprocess` and `embed`, this module is also the home of the shared
upload-intake path (AD-7): content-sniff, re-encode, EXIF-strip, applied
identically to a staff photo arriving at `apps/api` and to a reference image
arriving through `scripts/ingest`. It is named here so the charter is recorded,
but nothing implements it yet — see the porting rule below. Crop (AD-11) and
view generation (AD-13) arrive the same way.

Porting rule
------------
`poc/tilematch/vision.py` was written to be lifted into this module *unchanged*,
not read as a reference and reimplemented. When Epic 2 ports it, copy it; do not
paraphrase it. Its preprocessing constants come verbatim from the model's own
`preprocessor_config.json` (`Xenova/dinov2-base`) and changing any of them
invalidates every stored vector.

Re-index rule (AD-14)
---------------------
`PIPELINE_VERSION` stamps every stored embedding. Search refuses a mismatch
rather than comparing vectors from two different pipelines. Any change to this
module's pixel path bumps the version and requires a full re-index, and the PR
must say so.
"""

from __future__ import annotations

from typing import Any

#: Stamped onto every stored embedding (AD-14). The skeleton deliberately does
#: not claim the POC's version string ("dinov2b-224-cls+meanpatch-icc-v3") —
#: nothing here produces vectors, so nothing here may look like it does. The
#: port in Epic 2 replaces this with the ported pipeline's own value.
PIPELINE_VERSION = "unimplemented-skeleton-0"

#: The file this module is ported from, unchanged (AD-1).
PORT_SOURCE = "poc/tilematch/vision.py"

_NOT_YET = (
    "shared_vision is a skeleton: the pixel path is not implemented yet. "
    f"It arrives in Epic 2, ported unchanged from {PORT_SOURCE}. "
    "Do not implement it here piecemeal, and never on one side only — AD-1 "
    "requires index-time and query-time preprocessing to be identical."
)

__all__ = ["PIPELINE_VERSION", "PORT_SOURCE", "embed", "preprocess"]


def preprocess(image: Any) -> Any:
    """Normalise an image for embedding. Not implemented yet — see AD-1 above."""
    raise NotImplementedError(_NOT_YET)


def embed(tensor: Any) -> Any:
    """Embed a preprocessed image. Not implemented yet — see AD-1 above."""
    raise NotImplementedError(_NOT_YET)
