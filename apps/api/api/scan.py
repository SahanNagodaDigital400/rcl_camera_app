"""`POST /scans` — capture through match: crop, quality gate, and the ranked
Candidates Epic 2's vector search already knew how to find (Stories 3.2-3.4).

Story 3.1 gave Scan a capture/upload path with nowhere to send the result.
This route is that destination: it crops the submitted image server-side, in
`shared_vision`, checks the cropped region's quality, matches the surviving
crop against the catalogue through `api.catalogue.find_candidates` — the same
function Epic 2 built and tested, wrapped here rather than reimplemented
(AD-1) — and answers `200` with up to three ranked Candidates. A persisted
`Scan` row (Story 3.5 — no such table exists yet) is a later story's extension
of *this same handler*, not a second endpoint.

**`require_claimed_user`, never `require_administrator`.** Scan is reachable
by every authenticated role — Story 3.1's own home-panel door carries no role
guard — so this route does not sit under `/admin/` and must not declare the
Administrator check: `tests/test_admin_authorization.py`'s route-table guard
fails the build if a route outside that prefix declares it.

**The uploaded image is untrusted content from a phone camera, not an
Administrator's studio asset**, so intake runs at `UPLOAD_MAX_PIXELS` —
AD-7's tighter of the two ceilings — rather than `REFERENCE_MAX_PIXELS`. The
read-then-intake sequence and the exception mapping are `catalogue._accept_bytes`'s
own shape, reused rather than reimplemented: `_read_upload` is imported
directly from `api.catalogue`, and so are the four envelope codes and
sentences intake can produce, so this module never redefines what "too
large" or "not a readable image" means.

**The crop rectangle is validated by executing it.** `shared_vision.crop_to_rect`
is the one place a crop rectangle is checked and applied — see its own
docstring — and this handler's job is only to translate the `InvalidCropRect`
it can raise into this route's own `422` envelope, exactly as it already
translates `ImageTooLarge` and `UnreadableImage`. The bounds arithmetic is
not written a second time here.

Sync, not `async def`, for `add_tile`'s reason: intake is CPU-bound (colour
management, an EXIF transpose, a re-encode) and FastAPI runs a sync handler
in its threadpool, where that cost cannot block the event loop.
"""

from __future__ import annotations

from typing import Annotated

import psycopg
import shared_vision
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from shared_schema.errors import ApiError
from shared_schema.scan import ScanCandidate
from shared_schema.user import User

from api.catalogue import (
    IMAGE_TOO_LARGE,
    NOT_AN_IMAGE,
    TOO_LARGE,
    UNREADABLE_IMAGE,
    _read_upload,
    find_candidates,
    primary_reference_image_ids,
)
from api.db import get_connection
from api.dependencies import NO_STORE, require_claimed_user

router = APIRouter(tags=["scan"])

# --- Envelope codes ------------------------------------------------------------
# `apps/web`'s `error-code-parity.test.ts` pins this spelling against the
# client's own copy, the same way it pins every code `api.catalogue` declares.

#: The crop rectangle `shared_vision.crop_to_rect` refused to apply — zero or
#: negative area, an origin outside the image, or an extent past its far edge.
INVALID_CROP_RECT = "invalid_crop_rect"

#: Worded about the selection rather than about coordinates: the caller here is
#: `CropScreen`, translating its own drag state back into this rectangle before
#: it is ever sent, so a caller who sees this sentence has a bug in that
#: translation rather than a selection to fix by hand.
INVALID_RECT_MESSAGE = "That crop selection is not valid. Adjust it and try again."

#: The cropped region scored below `shared_vision.SCAN_QUALITY_THRESHOLD`
#: (FR-9, AD-12). `CropScreen` recognises this code and swaps its actions for
#: a single "Retake" — see its own module comment — rather than leaving a
#: resubmission of the same photo live, which would only fail again.
SCAN_QUALITY_TOO_LOW = "scan_quality_too_low"

#: Verbatim, EXPERIENCE.md's own microcopy for this refusal. `CropScreen`
#: renders `failure.message` straight from the server rather than holding a
#: second copy of this sentence, so there is no TypeScript twin for
#: `error-code-parity.test.ts` to pin it against — only the *code* above has
#: one. This exact wording is pinned by nothing but
#: `test_scan_submission.py`'s own direct assertion against it.
SCAN_QUALITY_MESSAGE = "This photo's a little blurry — try again."


def _refusal(code: str, message: str, status_code: int) -> ApiError:
    """One constructor for every refusal here. `api.catalogue`'s own idiom."""
    return ApiError(code, message, status_code=status_code, headers=NO_STORE)


@router.post("/scans", response_model=list[ScanCandidate])
def submit_scan(
    response: Response,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    crop_x: Annotated[float, Form()],
    crop_y: Annotated[float, Form()],
    crop_width: Annotated[float, Form()],
    crop_height: Annotated[float, Form()],
    image: Annotated[UploadFile, File()],
) -> list[ScanCandidate]:
    """Crop, gate on quality, match, and answer up to three ranked Candidates.

    Story 3.2 crops the submitted scan, server-side, exactly once. Story 3.3
    gates what survives that crop on FR-9's quality check. Story 3.4 sends the
    surviving crop — never the pre-crop frame — through
    `api.catalogue.find_candidates`, the same tested search Epic 2 built, and
    maps each returned Candidate to the closed `ScanCandidate` contract:
    `tile_id`, `code`, `size`, `category`, `image_id` — never `score`, `rank`
    or any derived confidence wording (AD-20). Order in the array *is* the
    rank; the client paints the first as "Best match" and never re-derives the
    ordinal.

    `crop_x`/`crop_y`/`crop_width`/`crop_height` are the normalized 0-1
    rectangle `CropScreen` computed from its own on-screen selection against
    the uploaded image's actual pixel dimensions (AD-11) — never absolute
    pixels, and never a rectangle already applied to the bytes that arrive
    here.

    **`200`, with a bare JSON array — up to three Candidates, or none.** The
    request is no longer "accepted for later": by the time this returns, the
    match has fully resolved, which is what `200` means and what every other
    synchronous route in this product already uses. An empty catalogue (no
    tile ever indexed) is not an error — `find_candidates` answers `[]`, and
    this route answers the same empty array, which `apps/web`'s Results screen
    reads as "no confident match" rather than a failure. Nothing is persisted
    yet (no `Scan` table exists — Story 3.5): that story extends this same
    handler with the thing it adds, rather than this one inventing a response
    shape today that tomorrow would only replace. A quality failure (3.3,
    below) never reaches the match at all.

    **The embedding forward pass is serialized service-wide** (AD-16):
    `find_candidates` holds a module-level lock around the one call that
    touches the model, acquired only after `require_claimed_user` has already
    resolved — so a refused caller never queues for it, and two accepted scans
    that reach the model together wait for each other's forward pass rather
    than contending with it.
    """
    response.headers.update(NO_STORE)

    data = _read_upload(image)
    try:
        accepted = shared_vision.intake_image(data, max_pixels=shared_vision.UPLOAD_MAX_PIXELS)
    except shared_vision.ImageTooLarge as oversized:
        raise _refusal(IMAGE_TOO_LARGE, TOO_LARGE, status.HTTP_413_CONTENT_TOO_LARGE) from oversized
    except shared_vision.UnreadableImage as unreadable:
        raise _refusal(
            UNREADABLE_IMAGE, NOT_AN_IMAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from unreadable

    try:
        cropped = shared_vision.crop_to_rect(
            accepted.image, crop_x, crop_y, crop_width, crop_height
        )
    except shared_vision.InvalidCropRect as invalid:
        raise _refusal(
            INVALID_CROP_RECT, INVALID_RECT_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    # FR-9 / AD-12: the quality gate runs on the cropped region `cropped` is —
    # never on `accepted.image`, the pre-crop upload. A failing score stops
    # the request here; matching never sees a blurry or poorly-framed scan.
    if not shared_vision.passes_quality(cropped):
        raise _refusal(
            SCAN_QUALITY_TOO_LOW, SCAN_QUALITY_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        )

    # Matching runs on `cropped`, never on the pre-crop frame (AD-1). One call,
    # through the function Epic 2 already tested — no second search here.
    candidates = find_candidates(conn, cropped)
    image_ids = primary_reference_image_ids(conn, [candidate.tile_id for candidate in candidates])

    # FR-7's floor ("every Tile keeps at least one Reference Image") holds for
    # a Tile that still exists — it says nothing about one that stops
    # existing between the two calls above. That gap is real, if narrow: an
    # Administrator's `DELETE /admin/tiles/{tile_id}` can land in between
    # them, and a candidate `find_candidates` returned a moment earlier then
    # has no row for `primary_reference_image_ids` to find. `.get()` rather
    # than `[...]`, so that rare overlap drops the one affected candidate —
    # one fewer entry in the returned array — instead of raising a `KeyError`
    # that would surface as a raw, un-enveloped `500`.
    return [
        ScanCandidate(
            tile_id=candidate.tile_id,
            code=candidate.code,
            size=candidate.size,
            category=candidate.category,
            image_id=image_id,
        )
        for candidate in candidates
        if (image_id := image_ids.get(candidate.tile_id)) is not None
    ]
