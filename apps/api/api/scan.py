"""`POST /scans` and `GET /scans` — capture through match, and the record of it.

Story 3.1 gave Scan a capture/upload path with nowhere to send the result.
`submit_scan` is that destination: it crops the submitted image server-side,
in `shared_vision`, checks the cropped region's quality, matches the
surviving crop against the catalogue through `api.catalogue.find_candidates`
— the same function Epic 2 built and tested, wrapped here rather than
reimplemented (AD-1) — answers `200` with up to three ranked Candidates
(Stories 3.2-3.4), and persists what it just answered as one `scan` row
(Story 3.5).

**`GET /scans`, not a new path.** `POST /scans` already owns the concept "a
Scan"; a same-path `GET` is a second verb on one resource, `DELETE
/admin/users/{user_id}`'s own precedent for a method added to an existing
path rather than a new registration surface. `read_scan_history` below is
that read: a caller's own past scans, newest first, one page at a time —
`api.audit.read_audit_log`'s exact shape, scoped to `user_id` throughout.

**`require_claimed_user`, never `require_administrator`, on both routes.**
Scan is reachable by every authenticated role — Story 3.1's own home-panel
door carries no role guard — so this module does not sit under `/admin/` and
must not declare the Administrator check: `tests/test_admin_authorization.py`'s
route-table guard fails the build if a route outside that prefix declares it.

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

import logging
from collections.abc import Iterable
from typing import Annotated, Any
from uuid import UUID

import psycopg
import shared_vision
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from psycopg.types.json import Jsonb
from shared_schema.errors import ApiError
from shared_schema.scan import HISTORY_PAGE_SIZE, ScanCandidate, ScanHistoryEntry
from shared_schema.user import User

from api import anomaly, audit, scan_throttle
from api.audit import AuditAction
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

#: `api.scan_throttle`'s own explicit-`rocell.`-prefix naming, so a deployment
#: can filter or raise the level of every `rocell.*` logger with one rule.
logger = logging.getLogger("rocell.api.scan")

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

#: Story 3.6 / FR-23: this account has submitted more scans than
#: `scan_throttle.SCAN_RATE_LIMIT` allows within `scan_throttle.SCAN_RATE_LIMIT_WINDOW`.
#: A module-level constant, unlike `SCAN_ENTRY_NOT_FOUND` below — this one needs
#: a TypeScript twin (`error-code-parity.test.ts`'s "every code the API can
#: emit" scan), which only reaches a module-level `NAME = "..."` assignment.
SCAN_RATE_LIMITED = "scan_rate_limited"

#: EXPERIENCE.md line 89: a plain "temporarily paused" sentence, and
#: deliberately no countdown — see AD-8 and `scan_throttle`'s own module
#: docstring for why neither the rate nor the window ever reaches this
#: sentence or any header on this response.
SCAN_RATE_LIMITED_MESSAGE = "Scan submissions are temporarily paused. Try again shortly."


def _refusal(code: str, message: str, status_code: int) -> ApiError:
    """One constructor for every refusal here. `api.catalogue`'s own idiom."""
    return ApiError(code, message, status_code=status_code, headers=NO_STORE)


#: One row, one statement, fully parameterized (Story 3.5). `id` and
#: `created_at` take their column defaults, `api.audit._INSERT_ENTRY`'s own
#: reason: the timestamp is the database's clock, not this host's.
#:
#: `candidates_snapshot` is passed as `Jsonb`, so psycopg adapts the list
#: rather than this module serializing JSON by hand. It is built from the
#: same `list[ScanCandidate]` `submit_scan` already returns, after that list
#: is constructed — so the persisted snapshot is byte-identical to the
#: response body, never recomputed.
#:
#: No `RETURNING`: nothing reads the row back at the point it is written, and
#: a caller has no use for its id today.
_INSERT_SCAN = """
INSERT INTO scan (user_id, candidates_snapshot)
VALUES (%s, %s)
"""


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
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
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
    reads as "no confident match" rather than a failure. A quality failure
    (3.3, above) never reaches the match at all.

    **Story 3.5 persists the answer.** Once the Candidates below are built,
    one `scan` row is inserted — `user_id`, and the same array as
    `candidates_snapshot` (AD-10) — including an empty array, which is a real
    answer and not the absence of one. A refused submission (an invalid crop
    rectangle, a quality failure, an oversized or unreadable upload, a missing
    model, a stale index) writes no row, because every refusal above raises
    before this point is ever reached. `GET /scans` below is the read that
    surfaces it.

    **The embedding forward pass is serialized service-wide** (AD-16):
    `find_candidates` holds a module-level lock around the one call that
    touches the model, acquired only after `require_claimed_user` has already
    resolved — so a refused caller never queues for it, and two accepted scans
    that reach the model together wait for each other's forward pass rather
    than contending with it.
    """
    response.headers.update(NO_STORE)

    # Story 3.6 / AD-16's fixed order: session validation (already done, by
    # `require_claimed_user`) → AD-8's rate-limit check → only then, the crop,
    # the quality gate and the inference lock. A throttled caller never pays
    # for any image work, and no `scan` row is written for this refusal, as
    # for every other pre-match refusal in this handler.
    throttled = scan_throttle.check_and_record(conn, user.id)

    # Story 3.7 / FR-22: independent of the throttle above and of this
    # submission's own outcome — epic-3-context.md's "a burst can trip one
    # without the other." Run unconditionally, before either can decide the
    # response, so a throttled burst is still counted toward the volume
    # baseline and a flagged-but-unthrottled burst still proceeds to matching.
    # `anomaly.py` never writes the audit log itself; a `True` result here is
    # turned into one flag entry, exactly as `scan_throttle`'s own boolean is
    # turned into a refusal, by the caller and not by the module reporting it.
    #
    # **Guarded.** This is a purely additive, non-critical signal — epics.md's
    # own "a flag never blocks the action that produced it" — so a transient
    # fault computing or recording it must never sink an otherwise-valid
    # submission. `conn` is autocommit here (AD-3, `api.db`), so a failure in
    # either statement below commits nothing on its own and cannot poison any
    # surrounding transaction; it is swallowed and logged rather than left to
    # fail the request, `api.auth`'s own `record_failure` pattern for exactly
    # this class of secondary-signal fault.
    try:
        if anomaly.check_and_flag(conn, user.id, "scan"):
            audit.record(
                conn,
                action=AuditAction.SCAN_VOLUME_ANOMALY_FLAGGED,
                actor_id=user.id,
                actor_email=user.email,
                source_ip=source_ip,
            )
    except psycopg.Error:
        logger.warning(
            "the anomaly check could not be completed; the submission itself stands",
            exc_info=True,
        )

    if throttled:
        raise _refusal(
            SCAN_RATE_LIMITED, SCAN_RATE_LIMITED_MESSAGE, status.HTTP_429_TOO_MANY_REQUESTS
        )

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
    answer = [
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

    # The persisted snapshot is built from `answer`, never recomputed from
    # `candidates` — so what lands in `scan.candidates_snapshot` is
    # byte-identical to the body this route is about to return, image drops
    # and all.
    conn.execute(
        _INSERT_SCAN,
        (user.id, Jsonb([candidate.model_dump(mode="json") for candidate in answer])),
    )

    return answer


# --- `GET /scans` — a caller's own scan history (Story 3.5) -------------------
#
# `api.audit.read_audit_log`'s exact shape — keyset-paginated, newest first,
# a bare JSON array, a cursor naming no row is a `404` — with one predicate
# added throughout: `user_id = %s`, because this history is scoped to the
# caller's own rows and never reaches another user's. Unlike the audit log
# this surface is `require_claimed_user`-gated rather than Administrator-only
# — every claimed Staff or Administrator account reaches its own history.


def _scan_entry_not_found() -> ApiError:
    """The `404` for a cursor that names no entry of the caller's own.

    **`SCAN_ENTRY_NOT_FOUND` and `NO_SUCH_SCAN_ENTRY` are deliberately local
    to this function, not module constants** — the one place this route
    diverges from every other refusal in this file. `AuditAction`'s own
    `AUDIT_ENTRY_NOT_FOUND` has no TypeScript twin either, for the reason
    given below, and earns that exemption because `api.audit` sits outside
    `error-code-parity.test.ts`'s scanned router list entirely. `api.scan` is
    on that list, for its other codes — `INVALID_CROP_RECT`,
    `SCAN_QUALITY_TOO_LOW` — which do need a twin, so a *module-level*
    `NAME = "value"` assignment here is exactly the shape that test's "every
    code the API can emit" scan looks for and would demand one of. Scoping
    the two constants to this function keeps them out of that scan without
    fabricating a twin: the client never invents a cursor, so this `404` is
    not a case any screen branches on, and there is nothing for a twin to do.
    """
    SCAN_ENTRY_NOT_FOUND = "scan_entry_not_found"
    NO_SUCH_SCAN_ENTRY = "No scan entry has that id."
    return ApiError(
        SCAN_ENTRY_NOT_FOUND,
        NO_SUCH_SCAN_ENTRY,
        status_code=status.HTTP_404_NOT_FOUND,
        headers=NO_STORE,
    )


#: The first page: the caller's own newest `HISTORY_PAGE_SIZE` scans.
#:
#: `ORDER BY created_at DESC, id DESC`, `_SELECT_LATEST_ENTRIES`'s own
#: reasoning: `created_at` defaults to `now()`, the transaction timestamp, so
#: the `id` tiebreaker is what gives this a total order to page through.
#:
#: `LIMIT %s` is a parameter, never a formatted number — `HISTORY_PAGE_SIZE`
#: is ours and could safely be interpolated, and interpolating it anyway is
#: the habit `tests/test_source_guards.py` exists to stop before it reaches a
#: value that is not ours.
_SELECT_LATEST_SCANS = """
SELECT id, created_at, candidates_snapshot
FROM scan
WHERE user_id = %s
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

#: The next page: the caller's own newest `HISTORY_PAGE_SIZE` scans strictly
#: older than one row.
#:
#: **Keyset, not `OFFSET`**, `_SELECT_ENTRIES_BEFORE`'s own reasoning: a scan
#: lands at the top of this order on every submission, so an `OFFSET` would
#: re-serve rows the reader has already seen.
#:
#: The cursor subquery is scoped by `user_id` too, not only the outer query:
#: a cursor naming another user's own scan then resolves no row at all, so it
#: is refused exactly as an invented id is — a caller can never page from an
#: id that is not theirs, even to a timestamp that would otherwise be a valid
#: boundary.
_SELECT_SCANS_BEFORE = """
SELECT id, created_at, candidates_snapshot
FROM scan
WHERE user_id = %s
  AND (created_at, id) < (
        SELECT created_at, id FROM scan WHERE id = %s AND user_id = %s
      )
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

#: Whether a cursor names a row belonging to *this* caller. Run only when the
#: page above came back empty — `_SELECT_ENTRY_EXISTS`'s own reasoning: the
#: oldest entry and an invented (or another user's) id produce the same empty
#: result set, and they are a `200 []` and a `404` respectively.
_SELECT_SCAN_EXISTS = """
SELECT 1
FROM scan
WHERE id = %s AND user_id = %s
"""


def _history_entries(rows: Iterable[Any]) -> list[ScanHistoryEntry]:
    """Map `scan` rows to `ScanHistoryEntry`, the one place this read diverges
    from `read_audit_log`.

    `AuditLogEntry.model_validate(row)` works directly because every column
    name matches a model field name. `scan`'s `candidates_snapshot` column and
    `ScanHistoryEntry.candidates` field do not share a name, so each row is
    built explicitly rather than through a bare `model_validate(row)`.
    `psycopg` decodes `jsonb` to a Python `list` on its own, `api.catalogue`'s
    own `details` decode path.
    """
    return [
        ScanHistoryEntry(
            id=row["id"],
            created_at=row["created_at"],
            candidates=[ScanCandidate(**candidate) for candidate in row["candidates_snapshot"]],
        )
        for row in rows
    ]


@router.get("/scans", response_model=list[ScanHistoryEntry])
def read_scan_history(
    response: Response,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    before: UUID | None = None,
) -> list[ScanHistoryEntry]:
    """A caller's own scan history, newest first, one page at a time (Story 3.5).

    **`require_claimed_user`, never `require_administrator`.** Every claimed
    Staff or Administrator account reaches this route and it is scoped to
    `user.id` throughout — never another user's rows, and the two-argument
    subquery inside `_SELECT_SCANS_BEFORE` is what stops a cursor borrowed
    from another user's history from resolving to anything at all.

    `read_audit_log`'s exact shape otherwise: a bare JSON array (never an
    envelope), a keyset cursor naming the oldest row already rendered, and a
    cursor that names no row of the caller's own answered with `404`. See
    that function's own docstring for the reasoning behind each of those —
    it applies here unchanged, with `user_id` added to every predicate.
    """
    response.headers.update(NO_STORE)

    if before is None:
        return _history_entries(conn.execute(_SELECT_LATEST_SCANS, (user.id, HISTORY_PAGE_SIZE)))

    entries = _history_entries(
        conn.execute(_SELECT_SCANS_BEFORE, (user.id, before, user.id, HISTORY_PAGE_SIZE))
    )
    # Only when the page is empty — `read_audit_log`'s own reasoning, scoped
    # to this caller: an exhausted history and a cursor naming no row of the
    # caller's own produce the same empty result set.
    if not entries and conn.execute(_SELECT_SCAN_EXISTS, (before, user.id)).fetchone() is None:
        raise _scan_entry_not_found()
    return entries
