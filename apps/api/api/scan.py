"""`POST /scans` — the crop-only submission path AD-11 requires (Story 3.2).

Story 3.1 gave Scan a capture/upload path with nowhere to send the result.
This route is that destination, and today it does exactly one thing: it
crops the submitted image, server-side, in `shared_vision`, and answers.
Everything past that — a blur/framing check (3.3), matching against the
catalogue (3.4), a persisted `Scan` row (3.5 — no such table exists yet) — is
a later story's extension of *this same handler*, not a second endpoint.
Inventing a response shape now that those stories would only replace is
exactly the fantasized scope CLAUDE.md and AGENTS.md both ask this workflow
to avoid, so this responds `202` with no body: there is nothing yet to hand
back.

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

import shared_vision
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from shared_schema.errors import ApiError
from shared_schema.user import User

from api.catalogue import IMAGE_TOO_LARGE, NOT_AN_IMAGE, TOO_LARGE, UNREADABLE_IMAGE, _read_upload
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


def _refusal(code: str, message: str, status_code: int) -> ApiError:
    """One constructor for every refusal here. `api.catalogue`'s own idiom."""
    return ApiError(code, message, status_code=status_code, headers=NO_STORE)


@router.post("/scans", status_code=status.HTTP_202_ACCEPTED)
def submit_scan(
    user: Annotated[User, Depends(require_claimed_user)],
    crop_x: Annotated[float, Form()],
    crop_y: Annotated[float, Form()],
    crop_width: Annotated[float, Form()],
    crop_height: Annotated[float, Form()],
    image: Annotated[UploadFile, File()],
) -> Response:
    """Story 3.2 — crop the submitted scan, server-side, exactly once.

    `crop_x`/`crop_y`/`crop_width`/`crop_height` are the normalized 0-1
    rectangle `CropScreen` computed from its own on-screen selection against
    the uploaded image's actual pixel dimensions (AD-11) — never absolute
    pixels, and never a rectangle already applied to the bytes that arrive
    here.

    **`202`, with a genuinely empty body — not `None`.** Nothing is persisted
    yet (no `Scan` table exists — Story 3.5), nothing is matched yet (3.4),
    and there is no quality verdict yet (3.3): those stories extend this same
    handler with the thing they add, rather than this one inventing a
    response shape today that tomorrow would only replace. Unlike a `204`,
    FastAPI does not suppress a `202`'s body on its own — returning `None`
    with no declared `response_model` would still serialize to the four bytes
    `null` — so this builds and returns its own empty `Response`, `auth.logout`'s
    own pattern for the same reason.
    """
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
        shared_vision.crop_to_rect(accepted.image, crop_x, crop_y, crop_width, crop_height)
    except shared_vision.InvalidCropRect as invalid:
        raise _refusal(
            INVALID_CROP_RECT, INVALID_RECT_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    return Response(status_code=status.HTTP_202_ACCEPTED, headers=dict(NO_STORE))
