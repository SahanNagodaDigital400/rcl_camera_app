"""The shared vision module — preprocessing and embedding for BOTH pipelines.

AD-1 — the single most important invariant in this codebase
-----------------------------------------------------------
Index-time and query-time preprocessing and embedding must be byte-for-byte
identical. They live here, in one module, and both callers use it unwrapped::

    Index time:  ReferenceImage -> preprocess -> embed -> pgvector
    Scan time:   phone photo    -> preprocess -> embed -> search -> top 3

`apps/api` (catalogue write and scan) and `scripts/ingest` (index) call the
*same* functions with no wrapping, forking or reimplementation on either side.
Any asymmetry silently destroys match accuracy: it raises no error, fails no
test that does not look for it, and shows up only as a quietly worse top-3
number. `tests/test_pipeline.py` holds that as an executable assertion.

Layering, which resolves a tension the planning docs leave open::

    view selection / augmentation      (index-time only, ABOVE the boundary)
    ---------------------------- PIL.Image boundary -----------------------
    load_image -> preprocess -> embed  (symmetric, `pipeline.py`)

Augmentation is index-only by definition, so it lives above the boundary
(`views.py`) and hands a plain image down. Everything below the boundary is
identical on both sides.

Colour management (AD-15) is part of loading and belongs below the boundary
too: roughly 60% of the reference catalogue is CMYK press files, and a naive
RGB conversion discards the embedded ICC profile and corrupts the embedding.
`tests/test_colour_management.py` guards hue *and* brightness, because the
green cast and the tonal crush were two separate bugs and the first fix did not
catch the second.

The surfaces
------------
* `pipeline` — `load_image`, `preprocess`, `embed`, `embed_images`,
  `config_hash`, `PIPELINE_VERSION`. The symmetric half.
* `views` — `generate_views`, AD-13's 4 clean rotations plus 12 randomized
  augmented crops. Index-time only.
* `intake` — AD-7's single upload path (`intake_image`) and AD-17's capped
  display derivative (`display_derivative`). Every writer calls this and
  nothing else.

Porting rule
------------
`poc/tilematch/vision.py` was written to be lifted into this module
*unchanged*, not read as a reference and reimplemented. `pipeline.py` is that
copy. Its preprocessing constants come verbatim from the model's own
`preprocessor_config.json` (`Xenova/dinov2-base`) and changing any of them
invalidates every stored vector.

Re-index rule (AD-14)
---------------------
`PIPELINE_VERSION` and `config_hash()` stamp the active `embedding_generation`
row, not each embedding — the check is global. Any change to this module's
pixel path changes the stamp, requires a complete new generation cut over by
the single active pointer, and the PR must say so.
"""

from __future__ import annotations

from shared_vision.intake import (
    DERIVATIVE_MAX_BYTES,
    DERIVATIVE_MAX_EDGE,
    FEATURELESS_STD,
    ImageTooLarge,
    IntakeRefused,
    IntakeResult,
    InvalidCropRect,
    UnreadableImage,
    crop_to_rect,
    display_derivative,
    intake_image,
)
from shared_vision.pipeline import (
    CROP_SIZE,
    DECODE_MAX_EDGE,
    EMBED_DIM,
    MODEL_MISSING,
    MODEL_PATH,
    PIPELINE_VERSION,
    REFERENCE_MAX_PIXELS,
    RESIZE_SHORTEST_EDGE,
    UPLOAD_MAX_PIXELS,
    config_hash,
    embed,
    embed_images,
    load_image,
    preprocess,
)
from shared_vision.views import (
    CANONICAL_VIEWS,
    VIEW_CROP,
    VIEW_ROTATION,
    VIEWS_PER_IMAGE,
    generate_views,
    view_kind,
)

#: The file `pipeline.py` is a copy of, unchanged (AD-1). Read by this
#: package's own tests, which assert the docstring above still names it.
PORT_SOURCE = "poc/tilematch/vision.py"

__all__ = [
    "CANONICAL_VIEWS",
    "CROP_SIZE",
    "DECODE_MAX_EDGE",
    "DERIVATIVE_MAX_BYTES",
    "DERIVATIVE_MAX_EDGE",
    "EMBED_DIM",
    "FEATURELESS_STD",
    "MODEL_MISSING",
    "MODEL_PATH",
    "PIPELINE_VERSION",
    "PORT_SOURCE",
    "REFERENCE_MAX_PIXELS",
    "RESIZE_SHORTEST_EDGE",
    "UPLOAD_MAX_PIXELS",
    "VIEWS_PER_IMAGE",
    "VIEW_CROP",
    "VIEW_ROTATION",
    "ImageTooLarge",
    "IntakeRefused",
    "IntakeResult",
    "InvalidCropRect",
    "UnreadableImage",
    "config_hash",
    "crop_to_rect",
    "display_derivative",
    "embed",
    "embed_images",
    "generate_views",
    "intake_image",
    "load_image",
    "preprocess",
    "view_kind",
]
