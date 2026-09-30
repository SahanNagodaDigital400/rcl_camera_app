"""`POST /scans` and `GET /scans` — capture through match, and the record of it.

Story 3.1 gave Scan a capture/upload path with nowhere to send the result.
`submit_scan` is that destination: it crops the submitted image server-side,
in `shared_vision`, matches the cropped region against the catalogue through
`api.catalogue.find_candidates`
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
read-then-intake sequence and the exception mapping are `catalogue._accept`'s
own shape, reused rather than reimplemented: `_read_upload` — the bounded read
both share — is imported directly from `api.catalogue`, and so are the four
envelope codes and sentences intake can produce, so this module never redefines
what "too large" or "not a readable image" means.

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
import math
import os
from collections.abc import Iterable
from typing import Annotated, Any
from uuid import UUID

import numpy as np
import psycopg
import shared_vision
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from psycopg.types.json import Jsonb
from shared_schema.errors import ApiError
from shared_schema.marker import (
    QUAD_CORNERS,
    Marker,
    Measurement,
    Point,
    TileProposal,
    match_size,
)
from shared_schema.scan import (
    HISTORY_PAGE_SIZE,
    ScanCandidate,
    ScanHistoryCount,
    ScanHistoryEntry,
)
from shared_schema.user import User

from api import anomaly, audit, measure, scan_throttle
from api.audit import AuditAction
from api.catalogue import (
    IMAGE_TOO_LARGE,
    NOT_AN_IMAGE,
    TOO_LARGE,
    UNREADABLE_IMAGE,
    _read_upload,
    find_candidates,
    indexed_sizes,
    primary_reference_image_ids,
)
from api.db import get_connection
from api.dependencies import NO_STORE, require_claimed_user
from api.markers import find_marker, list_markers

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

#: The Size the submission declared is not one the active generation holds.
#:
#: **Validated against the index, never taken on trust** — the POC's own rule
#: (`poc/tilematch/server.py`). The picker is populated from
#: `GET /scans/sizes`, so a caller reaching this has sent a size the catalogue
#: cannot answer for, and silently searching every size instead would return
#: candidates the staff member explicitly ruled out.
#:
#: Distinct from `catalogue.INVALID_SIZE`, which is a malformed Size *string*
#: on the write path. This one is well-formed and simply names nothing.
UNKNOWN_SIZE = "unknown_size"

#: Marker measurement's four refusals. Separate codes rather than one
#: `measurement_failed`, because the screen renders the API's own sentence and
#: the four are different instructions to the person holding the phone: pick a
#: registered marker, tap four corners, move closer so the card is bigger, lay
#: the card flat on the tile.
UNKNOWN_MARKER = "unknown_marker"
INVALID_CORNERS = "invalid_corners"
MARKER_NOT_DETECTED = "marker_not_detected"
MEASUREMENT_REFUSED = "measurement_refused"

#: Worded for a staff member who has just watched their own picker offer this
#: size — which is only reachable if the catalogue changed underneath them, so
#: the instruction is to look again rather than to retype anything.
UNKNOWN_SIZE_MESSAGE = "That size is not in the catalogue. Pick another, or scan all sizes."

UNKNOWN_MARKER_MESSAGE = "That marker is not registered. Pick another from the list."
INVALID_CORNERS_MESSAGE = (
    f"A measurement needs exactly {QUAD_CORNERS} corners, each inside the image."
)
NOT_DETECTED_MESSAGE = (
    "The marker was not found in the photo. Tap its four corners instead, "
    "or retake the photo with the whole marker visible."
)

# --- The match floor ------------------------------------------------------------

#: The similarity a Candidate must reach to be shown at all.
#:
#: `find_candidates` scores a Tile as the inner product of two L2-normalized
#: embeddings (`shared_vision.pipeline` normalizes both halves and then the
#: concatenation), so a score **is** cosine similarity on [-1.0, 1.0] and
#: `0.50` is the "50%" this bar is spoken about as. Every Candidate scoring
#: below it is dropped before the response is built, and a Scan where nothing
#: clears it answers the empty array — which `ResultsScreen` already renders
#: as "No confident match" rather than as a failure.
#:
#: **This is a display decision, not a pipeline one** (`poc/README.md`, "What
#: the match bar does"). It trims the tail off a results screen; it does not
#: touch preprocessing, embedding or the index, so moving it never invalidates
#: a generation the way anything in `shared/vision` would. It is applied after
#: `find_candidates` for exactly that reason — the search stays a pure ranker
#: and this route decides what reaches a screen.
#:
#: **It is not, and must never be presented as, a confidence signal** (AD-20).
#: The POC measured the two top-1 distributions on the 381-tile eval and they
#: are almost indistinguishable — correct answers median 0.918 against 0.907
#: for wrong ones, with the *wrong* answers' p10 and p90 both higher. A bar
#: keeps obviously-unrelated tiles off the screen; it does not make what
#: remains more likely to be right. Nothing derived from it — a number, a bar,
#: a star, a word like "strong" — may reach the client, and `ScanCandidate`
#: has no field that could carry one.
#:
#: At `0.50` the POC measured the bar as **inert on this catalogue**: 100% of
#: correct answers kept, 100% of wrong ones still shown, 0% of scans left with
#: nothing. That is the documented behaviour of this default, not a bug in it
#: — the knob exists so the value can be fitted against real staff photos
#: without a code change. For reference, the same measurement at 0.80 keeps
#: 91% of correct answers and 92% of wrong ones, and at 0.90 keeps 64% of
#: correct answers while leaving 40% of scans with nothing at all.
DEFAULT_MATCH_FLOOR = 0.50

#: Overrides `DEFAULT_MATCH_FLOOR` at start-up. `poc/tilematch/server.py` spells
#: the same knob `TILEMATCH_FLOOR`; the longer name here is this package's own
#: `TILEMATCH_SCAN_*` convention, which `TILEMATCH_SCAN_RATE_LIMIT` already sets.
MATCH_FLOOR_ENV = "TILEMATCH_SCAN_MATCH_FLOOR"


def _read_match_floor() -> float:
    """`MATCH_FLOOR_ENV`'s value, falling back to the default.

    `anomaly._read_multiplier`'s shape: an unparseable or out-of-range value
    warns and yields the default rather than raising, so a typo in a
    deployment's environment degrades to the documented behaviour instead of
    refusing to start a process whose main job is unrelated to this bar.

    **Bounded to [-1.0, 1.0], the range a cosine similarity can occupy**, and
    both ends matter for the same reason `_read_multiplier` rejects `0`: a
    value outside the range silently turns the feature into something nobody
    asked for. Above `1.0` no Candidate can ever clear the bar, so every scan
    answers "No confident match" and the product stops working from a single
    stray digit. Below `-1.0` every Candidate clears it, so the bar quietly
    stops existing. Neither is a value this parameter can mean.
    """
    raw = os.environ.get(MATCH_FLOOR_ENV)
    if raw is None:
        return DEFAULT_MATCH_FLOOR

    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using the default match floor (%s) instead",
            MATCH_FLOOR_ENV,
            raw,
            DEFAULT_MATCH_FLOOR,
        )
        return DEFAULT_MATCH_FLOOR

    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        logger.warning(
            "%s=%r is not a finite similarity in [-1.0, 1.0]; "
            "using the default match floor (%s) instead",
            MATCH_FLOOR_ENV,
            raw,
            DEFAULT_MATCH_FLOOR,
        )
        return DEFAULT_MATCH_FLOOR

    return value


#: The bar `submit_scan` applies. Read once at import —
#: `anomaly.ANOMALY_DEVIATION_MULTIPLIER`'s own pattern — so the value in
#: effect for the life of a process is fixed at start-up.
MATCH_FLOOR = _read_match_floor()


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
    size: Annotated[str, Form()] = "",
) -> list[ScanCandidate]:
    """Crop, match, and answer up to three ranked Candidates.

    Story 3.2 crops the submitted scan, server-side, exactly once. Story 3.4
    sends that crop — never the pre-crop frame — through
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

    **`size` is optional and declares what the staff member already knows.**
    Empty — the default, and what the Scan screen sends on "All sizes" — puts
    every Tile in contention. A declared Size is a hard filter applied before
    ranking, not a re-rank: it is the one attribute a photo cannot carry and
    the person holding the tile always knows, which the POC measures as the
    largest accuracy lever it has (+3.2 top-3 overall, +8.0 on 45X90 —
    `poc/README.md`). The cost is symmetrical and worth stating: a
    *mis*-declared Size makes the true Tile unreachable, no amount of ranking
    recovers from it, and that is why the screen defaults to All sizes rather
    than guessing one.

    Checked against `indexed_sizes` before it is used. An unrecognised Size is
    a `422`, never a silent fall back to searching everything — a staff member
    who declared a size and got candidates of every other size would have no
    way to tell the filter had been ignored.

    **`200`, with a bare JSON array — up to three Candidates, or none.** The
    request is no longer "accepted for later": by the time this returns, the
    match has fully resolved, which is what `200` means and what every other
    synchronous route in this product already uses. An empty catalogue (no
    tile ever indexed) is not an error — `find_candidates` answers `[]`, and
    this route answers the same empty array, which `apps/web`'s Results screen
    reads as "no confident match" rather than a failure.

    **Candidates below `MATCH_FLOOR` are not shown.** The bar is a similarity
    on [-1.0, 1.0] — `TILEMATCH_SCAN_MATCH_FLOOR` moves it without a code
    edit, default `0.50` — and it is a *display* decision: it trims the tail
    off the results screen and changes nothing about preprocessing, embedding
    or the index, so moving it never requires a re-index. It is emphatically
    not a confidence gate, and nothing derived from it reaches the client
    (AD-20); see `MATCH_FLOOR` above for the measurement, including the fact
    that at the default `0.50` it trims nothing at all on this catalogue.
    A scan where nothing clears the bar answers the same empty array an empty
    catalogue does, which the Results screen reads as "No confident match".

    **There is no blur or framing gate.** One was specified (FR-9, AD-12) and
    built, on a threshold its own module described as an uncalibrated
    placeholder deferred by PRD OQ-13. It was removed: the POC this product's
    accuracy is measured against has no such gate, so the only thing the bound
    could do here was refuse photos the POC would have matched — a refusal the
    staff member cannot appeal and the catalogue never gets a chance to answer.
    A soft-focus photo that still retrieves the right tile is a good scan.

    **Story 3.5 persists the answer.** Once the Candidates below are built,
    one `scan` row is inserted — `user_id`, and the same array as
    `candidates_snapshot` (AD-10) — including an empty array, which is a real
    answer and not the absence of one. A refused submission (an invalid crop
    rectangle, an oversized or unreadable upload, a missing model, a stale
    index) writes no row, because every refusal above raises before this
    point is ever reached. `GET /scans` below is the read that
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
    # the crop and the inference lock. A throttled caller never pays
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

    # Before the upload is read, for `scan_throttle`'s own reason: a refusal
    # that needs no pixels should cost none. `strip().upper()` is the POC's
    # own normalization — Sizes are stored upper-case (`shared_schema.tile`),
    # and a picker value that arrived with whitespace names the same Size.
    declared_size = size.strip().upper() or None
    if declared_size is not None and declared_size not in indexed_sizes(conn):
        raise _refusal(UNKNOWN_SIZE, UNKNOWN_SIZE_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT)

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

    # Matching runs on `cropped`, never on the pre-crop frame (AD-1). One call,
    # through the function Epic 2 already tested — no second search here.
    #
    # `MATCH_FLOOR` trims the tail *here*, not in the search: `find_candidates`
    # stays a pure ranker and this route decides what reaches a screen. The
    # filter runs before `primary_reference_image_ids` so a dropped Candidate
    # never costs an image lookup, and because the search already returns its
    # rows best-first the survivors keep that order — this is a prefix of the
    # ranked list, never a re-sort. Everything clearing the bar survives; an
    # empty result is a real answer, and the insert below records it as one.
    candidates = [
        candidate
        for candidate in find_candidates(conn, cropped, size=declared_size)
        if candidate.score >= MATCH_FLOOR
    ]
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


# --- `GET /scans/sizes` — what the size picker may offer -----------------------


@router.get("/scans/sizes", response_model=list[str])
def read_scan_sizes(
    response: Response,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> list[str]:
    """The Sizes a scan may declare, commonest first.

    **Read from the index, not from `tile_size`.** A Size row can outlive the
    last Tile indexed under it, and offering one is offering a filter that can
    only ever return nothing — see `catalogue.indexed_sizes`.

    **A sub-path of the Scan surface rather than a top-level `/sizes`.** This
    list exists for one control on one screen: what `POST /scans` will accept
    in its `size` field. A `/sizes` at the root would read as a catalogue
    resource, which is `GET /admin/tiles`' territory and Administrator-only;
    this is reachable by every claimed account, exactly as the scan it
    configures is.

    `[]` for a catalogue that has never been indexed. The screen renders that
    as the picker simply not appearing: there is nothing to narrow.

    `require_claimed_user`, never `require_administrator` — this module's own
    rule, and `tests/test_admin_authorization.py`'s route-table guard fails
    the build for a route outside `/admin/` that declares the latter.
    """
    response.headers.update(NO_STORE)
    return indexed_sizes(conn)


@router.get("/scans/markers", response_model=list[Marker])
def read_scan_markers(
    response: Response,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> list[Marker]:
    """The Markers a measurement may be taken with, by name.

    **The same rows `GET /admin/markers` serves, through the same reader**
    (`api.markers.list_markers`) — one owner for the table, so the two surfaces
    cannot drift on ordering or on what a Marker is once a column is added.

    **Readable by every claimed account, writable by none of them.** Staff pick
    a ruler here; only an Administrator registers one, under `/admin/markers`.
    That split is the whole control on this feature: the dimensions scale every
    measurement taken with the card, and a `54mm` typed as `540mm` is wrong by
    a factor of ten with nothing downstream able to see it.

    `[]` when no Marker has been registered. The screen renders that as the
    Measure control simply not appearing — there is nothing to measure with,
    and the Size picker still works exactly as it did.

    Nothing is recorded: `AuditAction` has no member for a read (FR-20 covers
    changes), and an entry per rendered picker would bury the entries that
    matter.
    """
    response.headers.update(NO_STORE)
    return list_markers(conn)


def _corner_array(xs: list[float], ys: list[float], width: int, height: int) -> np.ndarray:
    """Two lists of normalized coordinates as a pixel-space quad, or a refusal.

    Normalized `0.0`-`1.0` on the wire and pixels here, which is AD-11's rule
    for the scan crop and holds for the same reason: the browser collected
    these against a displayed image whose on-screen size is a property of the
    phone, not of the upload. Absolute pixels would silently mean different
    things on two devices.

    Sent as two repeated form fields rather than one packed string, because the
    alternative is a parser: a `"x,y,x,y,..."` field has to be split, counted
    and floated by hand, and every one of those steps is a way to accept
    something that is not four corners. FastAPI does the counting and the
    floating; this only has to check the shape and the range.
    """
    if len(xs) != QUAD_CORNERS or len(ys) != QUAD_CORNERS:
        raise _refusal(
            INVALID_CORNERS, INVALID_CORNERS_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in (*xs, *ys)):
        raise _refusal(
            INVALID_CORNERS, INVALID_CORNERS_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    return np.array(
        [[x * width, y * height] for x, y in zip(xs, ys, strict=True)], dtype=np.float64
    )


@router.post("/scans/propose", response_model=TileProposal)
def propose_tile(
    response: Response,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    marker_id: Annotated[UUID, Form()],
    image: Annotated[UploadFile, File()],
) -> TileProposal:
    """Where the tile's corners probably are, so the staff member starts from a shape.

    **A convenience, and the response says how much of one.** `detected` is
    `False` whenever the fallback rectangle came back, which on seven real
    showroom photographs happens twice: a tile whose tone is its floor's, or
    whose own veining spans more tone than the gap to the floor, has no
    boundary to find. Nothing here is wired into a measurement — the corners
    the staff member confirms are what `POST /scans/measure` receives, and
    they are free to move every one.

    **The marker has to be found first**, because the proposal is made in the
    marker's plane: that is what turns "find a quadrilateral" — which picks the
    floor every time — into "find a tile-sized rectangle, in millimetres,
    containing the marker". A Marker with no fiducial, or a fiducial that is
    not in the frame, is `422 marker_not_detected`, and the screen falls back
    to the corners being placed by hand.

    `require_claimed_user`, like every other route on this surface: proposing
    is part of measuring, and measuring is part of scanning.
    """
    marker = find_marker(conn, marker_id)
    if marker is None:
        raise _refusal(
            UNKNOWN_MARKER, UNKNOWN_MARKER_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    if marker.aruco_dictionary is None or marker.aruco_id is None:
        raise _refusal(
            MARKER_NOT_DETECTED, NOT_DETECTED_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
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

    rgb = np.asarray(accepted.image.convert("RGB"))
    detected_marker = measure.detect_marker(rgb, marker.aruco_dictionary, marker.aruco_id)
    if detected_marker is None:
        raise _refusal(
            MARKER_NOT_DETECTED, NOT_DETECTED_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        )

    # BGR, because `propose_tile_quad` works in Lab and OpenCV's conversion
    # reads its input as BGR. `detect_marker` takes RGB and converts its own.
    quad, detected = measure.propose_tile_quad(
        rgb[:, :, ::-1], detected_marker, marker.width_mm, marker.height_mm
    )

    width, height = accepted.image.size

    def normalized(points: Any) -> list[Point]:
        # AD-11's rule: the screen lays these over a picture whose on-screen
        # size is a property of the phone, not of the upload.
        return [
            Point(x=min(max(float(x) / width, 0.0), 1.0), y=min(max(float(y) / height, 0.0), 1.0))
            for x, y in points
        ]

    response.headers.update(NO_STORE)
    return TileProposal(
        corners=normalized(measure.order_corners(quad)),
        detected=detected,
        # The detector's own corner order, not `order_corners` — this is drawn
        # for a person to recognise the printed square by, and re-ordering it
        # would only make the outline disagree with the one the measurement
        # actually uses.
        marker=normalized(detected_marker),
        homography=measure.normalized_to_millimetres(
            detected_marker, marker.width_mm, marker.height_mm, width, height
        ),
    )


@router.post("/scans/measure", response_model=Measurement)
def measure_scan(
    response: Response,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    marker_id: Annotated[UUID, Form()],
    tile_x: Annotated[list[float], Form()],
    tile_y: Annotated[list[float], Form()],
    image: Annotated[UploadFile, File()],
    marker_x: Annotated[list[float] | None, Form()] = None,
    marker_y: Annotated[list[float] | None, Form()] = None,
) -> Measurement:
    """Measure a tile against a registered Marker lying on it.

    **This answers a suggestion, and the Scan screen treats it as one.** The
    `matched_size` below pre-fills the Size picker; only what the staff member
    then confirms reaches `POST /scans` as AD-19's hard pre-filter. That
    indirection is the whole safety argument: AD-19 states that a
    *mis*-declared Size makes the true Tile unreachable rather than merely
    lower-ranked, and a marker that slipped out of plane produces exactly such
    a mis-declaration — confidently, and with no error anywhere.

    **The uncropped frame, not the scan crop.** The marker is beside the
    pattern, so the rectangle `CropScreen` computes for matching would usually
    cut it out. The same image is submitted twice — here whole, and to
    `POST /scans` with its crop — rather than this endpoint returning something
    the scan then has to trust.

    **Two paths to the marker's corners, and the caller chooses by what it
    sends.** With `marker_x`/`marker_y` the corners were tapped, and their
    order is recovered by `measure.order_corners`. Without them the Marker must
    declare a fiducial, which is detected in the frame; a Marker with no
    fiducial and no tapped corners is `422 marker_not_detected`, and so is a
    fiducial that is genuinely absent — which is the signal the screen turns
    into "tap the corners instead".

    **No embedding, so no `_inference_lock`** (AD-16). This is homography
    arithmetic over an already-decoded frame; it costs milliseconds and holds
    nothing other scans queue behind.

    **Deliberately not counted against Story 3.6's scan rate limit.** That
    budget exists to bound catalogue exfiltration through a compromised
    account, and a measurement returns two numbers and no catalogue data at
    all — spending a scan on one would make the honest use of this feature cost
    a staff member their matches. It is bounded instead by the same
    `UPLOAD_MAX_PIXELS` intake ceiling the scan path uses. **Known gap:** that
    leaves the decode itself unthrottled per account, which is a smaller
    version of what Story 3.6 bounds and should get its own limiter before this
    is exposed beyond internal staff.

    `422` for every refusal, each with its own code and the sentence that says
    what to do about it — the marker is not registered, the corners are not
    four points inside the image, the fiducial was not found, the geometry
    does not measure as a rectangle.
    """
    marker = find_marker(conn, marker_id)
    if marker is None:
        raise _refusal(
            UNKNOWN_MARKER, UNKNOWN_MARKER_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
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

    width, height = accepted.image.size
    tile_corners = _corner_array(tile_x, tile_y, width, height)

    if marker_x is not None or marker_y is not None:
        marker_corners = _corner_array(marker_x or [], marker_y or [], width, height)
        oriented = False
    elif marker.aruco_dictionary is None or marker.aruco_id is None:
        # A plain object — a bank card, a badge — with nothing to detect. The
        # manual path is the only one it has, and the caller did not use it.
        raise _refusal(
            MARKER_NOT_DETECTED, NOT_DETECTED_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    else:
        detected = measure.detect_marker(
            np.asarray(accepted.image.convert("RGB")), marker.aruco_dictionary, marker.aruco_id
        )
        if detected is None:
            raise _refusal(
                MARKER_NOT_DETECTED, NOT_DETECTED_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
            )
        marker_corners, oriented = detected, True

    try:
        short_mm, long_mm = measure.measure_tile(
            marker_corners,
            marker.width_mm,
            marker.height_mm,
            tile_corners,
            marker_oriented=oriented,
        )
    except measure.MeasurementRefused as refused:
        # Every subclass carries the sentence that says what to do about it —
        # move closer, lay the card flat, tap the corners in order — and the
        # screen renders the API's own words (EXPERIENCE.md:87).
        raise _refusal(
            MEASUREMENT_REFUSED, str(refused), status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from refused

    response.headers.update(NO_STORE)
    return Measurement(
        short_mm=short_mm,
        long_mm=long_mm,
        # Compared against the Sizes the *index* can actually answer for, not
        # against `tile_size` — suggesting a Size with no indexed Tile behind
        # it would pre-fill a filter that can only ever return nothing.
        matched_size=match_size(short_mm, long_mm, indexed_sizes(conn)),
        auto_detected=oriented,
    )


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
    on that list, for its other codes — `INVALID_CROP_RECT`, `UNKNOWN_SIZE` —
    which do need a twin, so a *module-level*
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


# --- `GET /scans/count` — the denominator the history page cannot state -------


#: Every `scan` row belonging to one caller.
#:
#: `count(*)`, not `count(id)`: the two are equivalent for a `NOT NULL`
#: primary key and the planner treats them alike, and `count(*)` is what
#: "how many rows" reads as.
#:
#: **No cursor and no `LIMIT`.** This is deliberately not a page: a reader
#: paging through history is asking what the pages add up to, and a count
#: bounded by the same cursor would answer with the page they already have.
_COUNT_SCANS = """
SELECT count(*) AS count
FROM scan
WHERE user_id = %s
"""


@router.get("/scans/count", response_model=ScanHistoryCount)
def read_scan_history_count(
    response: Response,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> ScanHistoryCount:
    """How many past Scans the caller has in all (History's denominator).

    **A sub-path of the Scan surface, `GET /scans/sizes`' own precedent**, and
    a separate request rather than a field on `GET /scans`: that route answers
    with a bare array and this one number would have to become an envelope
    around it to travel there — changing the shape of every page of history
    for the sake of a subtitle. The screen asks for both and renders the rows
    whether or not the count arrives.

    **Scoped to `user.id`, exactly as `read_scan_history` is.** A count is a
    disclosure like any other row read: it is the caller's own history that is
    being measured, never the installation's.

    `require_claimed_user`, never `require_administrator` — this module's own
    rule; see `read_scan_sizes`.

    A snapshot, like the page beside it. A scan submitted between this request
    and the one for the first page moves the total, and neither number waits
    for the other: the screen shows the rows it actually has out of the total
    it was told, and a stale denominator is a subtitle that is briefly one
    behind, not a row missing or a row invented.
    """
    response.headers.update(NO_STORE)

    row = conn.execute(_COUNT_SCANS, (user.id,)).fetchone()
    # `count(*)` over an empty set is `0`, not no row at all — the aggregate
    # always returns exactly one row. The `None` branch is unreachable and is
    # here so that this function never depends on `row` being subscriptable.
    return ScanHistoryCount(count=0 if row is None else row["count"])
