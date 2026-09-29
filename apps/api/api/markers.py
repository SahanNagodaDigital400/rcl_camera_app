"""The Administrator's Marker surface — register, list, correct and withdraw rulers.

A **Marker** is a physical object of known printed size that a staff member
lays on a tile before photographing it, so that `api.measure` can turn pixel
distances into millimetres. This module owns the table; `api.measure` owns the
geometry and never reads a row; `api.scan` reads rows and never writes one.

**Under `/admin/`, and therefore Administrator-only.** Registering a ruler is
exactly the kind of act that must not be self-service: the dimensions typed
here scale every measurement every staff member takes with that card, and a
`54mm` typed as `540mm` is not an error anybody downstream can see — the
measurement comes back confident and wrong by a factor of ten. One person
holding the printed card, typing what is on it, with an audit entry naming
them, is the control. `tests/test_admin_authorization.py` holds the boundary by
reading the path.

**Nothing here is a Tile.** A Marker names no Tile, no Size and no Category, and
there is no foreign key in either direction. It is a ruler that happens to live
in the same database. A Marker that "belonged to" a Size would be a second,
silent identity model of the kind AD-18 retired.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Response, status
from psycopg import errors as pg_errors
from pydantic import BaseModel, ConfigDict
from shared_schema.errors import ApiError
from shared_schema.marker import (
    ArucoDictionary,
    Marker,
    clean_edge_mm,
    clean_marker_name,
    validate_aruco_pair,
)
from shared_schema.user import User

from api import audit
from api.audit import AuditAction
from api.db import get_connection
from api.dependencies import NO_STORE, require_administrator

logger = logging.getLogger("rocell.api.markers")

router = APIRouter(tags=["markers"])


# --- Envelope codes -----------------------------------------------------------
# Each is a code of its own rather than the generic `validation_error`, for
# `api.catalogue`'s reason: `api.main.validation_error_handler` renders one
# sentence for every 422 in the product and names no field, so an Administrator
# who mistyped one thing would be told nothing they can act on.
# `apps/web`'s `error-code-parity.test.ts` pins every spelling below.

INVALID_MARKER_NAME = "invalid_marker_name"
INVALID_MARKER_DIMENSION = "invalid_marker_dimension"
INVALID_MARKER_FIDUCIAL = "invalid_marker_fiducial"
DUPLICATE_MARKER_NAME = "duplicate_marker_name"
MARKER_NOT_FOUND = "marker_not_found"

#: The unique index a duplicate name violates, by its Postgres name. Matched
#: against `UniqueViolation.diag.constraint_name` rather than parsed out of the
#: driver's message, which is `api.catalogue.CODE_UNIQUE_INDEX`'s rule: the
#: message is localized and unstable, the constraint name is neither.
NAME_UNIQUE_INDEX = "marker_name_key"

ALREADY_REGISTERED = "A marker with that name is already registered."
NO_SUCH_MARKER = "That marker does not exist."


def _refusal(code: str, message: str, status_code: int) -> ApiError:
    """One constructor for every refusal here. `api.catalogue._refusal`'s idiom."""
    return ApiError(code, message, status_code=status_code, headers=NO_STORE)


# --- Statements ---------------------------------------------------------------
# Every one is parameterized; nothing below is assembled from a value
# (`tests/test_source_guards.py`).

_COLUMNS = """
       id, name, width_mm, height_mm, aruco_dictionary, aruco_id,
       created_at, updated_at
"""

_INSERT_MARKER = f"""
INSERT INTO marker (name, width_mm, height_mm, aruco_dictionary, aruco_id)
VALUES (%s, %s, %s, %s, %s)
RETURNING {_COLUMNS}
"""

#: `ORDER BY name`, because that is what the picker on the Scan screen shows
#: and what an Administrator scans down. There will never be many rows — this
#: is a handful of rulers, not a catalogue — so there is no cursor and no page
#: size, and adding either would be machinery for a list that fits on a phone.
_SELECT_MARKERS = f"""
SELECT {_COLUMNS}
  FROM marker
 ORDER BY name
"""

#: The unlocked single-row read `find_marker` serves — the measurement path
#: only needs the dimensions, and locking a ruler for the length of an image
#: decode would serialize every staff member holding the same card.
_SELECT_MARKER = f"""
SELECT {_COLUMNS}
  FROM marker
 WHERE id = %s
"""

#: `FOR UPDATE`, so two Administrators correcting the same card serialize
#: rather than interleaving a read and a write. Whichever commits second sees
#: the other's row.
_SELECT_MARKER_FOR_UPDATE = f"""
SELECT {_COLUMNS}
  FROM marker
 WHERE id = %s
 FOR UPDATE
"""

#: `updated_at` is set here rather than by a trigger — `users` and `tile` set
#: theirs by hand for the same reason (DW-17): this schema does not use
#: triggers for invariants.
_UPDATE_MARKER = f"""
UPDATE marker
   SET name = %s,
       width_mm = %s,
       height_mm = %s,
       aruco_dictionary = %s,
       aruco_id = %s,
       updated_at = now()
 WHERE id = %s
RETURNING {_COLUMNS}
"""

_DELETE_MARKER = "DELETE FROM marker WHERE id = %s"


class MarkerBody(BaseModel):
    """What an Administrator sends to register or correct a Marker.

    Closed shape (`extra="forbid"`), like every other contract in the product:
    a body carrying a key this does not declare is a caller writing against a
    contract that does not exist, and pydantic's default is to accept and
    silently discard it.

    **Every field is optional here and none of them is optional in practice.**
    The same model serves `POST` and `PATCH`: the create path requires all
    four through `_resolved`, and the edit path reads `model_fields_set` to
    tell "not sent" from "sent as null" — a distinction that matters only for
    the fiducial pair, where null is a meaningful value that clears it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    aruco_dictionary: ArucoDictionary | None = None
    aruco_id: int | None = None


def _as_marker(row: dict[str, Any]) -> Marker:
    """One row as the shared contract renders it."""
    return Marker(
        id=row["id"],
        name=row["name"],
        width_mm=row["width_mm"],
        height_mm=row["height_mm"],
        aruco_dictionary=(
            None if row["aruco_dictionary"] is None else ArucoDictionary(row["aruco_dictionary"])
        ),
        aruco_id=row["aruco_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validated(
    name: str, width_mm: float, height_mm: float, dictionary: Any, aruco_id: int | None
) -> tuple[str, float, float, ArucoDictionary | None, int | None]:
    """Every field through `shared_schema.marker`'s rules, or the matching refusal.

    The rules live in the contract rather than here because `shared_schema` is
    the one place both halves of the product read them from — the TypeScript
    twin mirrors the same bounds onto the form, so a field this refuses is a
    field the screen already refused before sending. This function is only the
    translation from `ValueError` to an envelope code, and each rule gets its
    own code so the sentence names the field that failed.
    """
    try:
        clean_name = clean_marker_name(name)
    except ValueError as invalid:
        raise _refusal(
            INVALID_MARKER_NAME, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    try:
        clean_width = clean_edge_mm(width_mm, "width")
        clean_height = clean_edge_mm(height_mm, "height")
    except ValueError as invalid:
        raise _refusal(
            INVALID_MARKER_DIMENSION, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    try:
        pair = validate_aruco_pair(dictionary, aruco_id)
    except ValueError as invalid:
        raise _refusal(
            INVALID_MARKER_FIDUCIAL, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    return clean_name, clean_width, clean_height, pair[0], pair[1]


def _details(marker: Marker) -> dict[str, Any]:
    """The AD-10 snapshot every entry here carries.

    **The dimensions are the point, not decoration.** A Marker silently
    re-measured from 85.6mm to 856mm scales every measurement taken with it by
    ten, and this log is the only place that would show when it happened and
    who did it. A snapshot rather than a foreign key, because removal is a hard
    delete and the log may neither block it nor be cascaded into.
    """
    return {
        "name": marker.name,
        "width_mm": marker.width_mm,
        "height_mm": marker.height_mm,
        "aruco_dictionary": marker.aruco_dictionary,
        "aruco_id": marker.aruco_id,
    }


@router.post("/admin/markers", response_model=Marker, status_code=status.HTTP_201_CREATED)
def register_marker(
    body: MarkerBody,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
) -> Marker:
    """Register a physical scale reference.

    **All four of name, width, height and the fiducial decision are required**,
    and the fiducial decision may be "none" — a bank card with no printed
    marker is a perfectly good ruler for the manual corner-tap path. What is
    refused is *half* a fiducial declaration, which is a card the detector will
    never find with nothing on screen to say why.

    **`201`, with the row.** The Administrator needs the id to edit it and the
    stored dimensions to check against the card in their hand.

    A duplicate name is `409`, decided by the unique index rather than by a
    pre-flight `SELECT`: a check-then-insert has a race between the two, and
    two rulers called "ID badge" with different dimensions is a measurement
    that is wrong half the time.
    """
    name, width_mm, height_mm, dictionary, aruco_id = _validated(
        body.name or "",
        body.width_mm or 0.0,
        body.height_mm or 0.0,
        body.aruco_dictionary,
        body.aruco_id,
    )

    try:
        row = conn.execute(
            _INSERT_MARKER,
            (name, width_mm, height_mm, dictionary, aruco_id),
        ).fetchone()
    except pg_errors.UniqueViolation as duplicate:
        if duplicate.diag.constraint_name != NAME_UNIQUE_INDEX:
            raise
        raise _refusal(
            DUPLICATE_MARKER_NAME, ALREADY_REGISTERED, status.HTTP_409_CONFLICT
        ) from duplicate

    assert row is not None  # noqa: S101 — RETURNING on a successful INSERT
    marker = _as_marker(row)

    # Inside the same transaction as the INSERT, so the entry exists exactly
    # when the row does. `target_email` stays empty: that column is an
    # account's, and a ruler is not one.
    audit.record(
        conn,
        action=AuditAction.MARKER_ADDED,
        actor_id=administrator.id,
        actor_email=administrator.email,
        target_id=marker.id,
        source_ip=source_ip,
        details=_details(marker),
    )

    response.headers.update(NO_STORE)
    return marker


def list_markers(conn: psycopg.Connection) -> list[Marker]:
    """Every registered Marker, by name — the reader both surfaces share.

    **This module owns the `marker` table, and that is why this is a function
    rather than two statements.** `api.scan` serves the staff-facing
    `GET /scans/markers` from the same rows, and a second `SELECT` over there
    is how the two would come to disagree about the ordering, the column set,
    or what a Marker is once a column is added. `api.catalogue.indexed_sizes`
    is the same arrangement read from the other direction.
    """
    return [_as_marker(row) for row in conn.execute(_SELECT_MARKERS).fetchall()]


def find_marker(conn: psycopg.Connection, marker_id: UUID) -> Marker | None:
    """One Marker by id, or `None` — the lookup `api.scan`'s measurement needs.

    No row lock: the caller is measuring, not writing, and holding a lock on a
    ruler for the length of an image decode would serialize every staff member
    using the same card.
    """
    row = conn.execute(_SELECT_MARKER, (marker_id,)).fetchone()
    return None if row is None else _as_marker(row)


@router.get("/admin/markers", response_model=list[Marker])
def read_markers(
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> list[Marker]:
    """Every registered Marker, by name.

    No paging and no filter. This is a handful of rulers — the whole list fits
    on a phone screen — and a cursor here would be machinery guarding nothing.

    Nothing is recorded: `AuditAction` has no member for a read, and FR-20
    covers changes.
    """
    response.headers.update(NO_STORE)
    return list_markers(conn)


@router.patch("/admin/markers/{marker_id}", response_model=Marker)
def edit_marker(
    marker_id: UUID,
    body: MarkerBody,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
) -> Marker:
    """Correct a registered Marker — a mistyped dimension, a renamed card.

    **Partial, and `model_fields_set` is what makes it partial.** A field the
    body omits keeps its stored value; a field sent as `null` clears it. The
    difference only matters for the fiducial pair, where `null` is a
    meaningful value that turns a detected card back into a tapped one — and
    where treating "absent" as "null" would silently un-register the fiducial
    of every Marker whose name was corrected.

    **The pair is re-validated against the merged row, not against the body.**
    Sending only `aruco_id` on a Marker that already declares a dictionary is a
    complete declaration once merged, and refusing it because the body carried
    one half would make a legal correction impossible.

    **`FOR UPDATE`**, so two Administrators correcting the same card serialize.
    An unknown id is `404`, decided by that locking read rather than by a
    zero-row `UPDATE` — a zero-row `UPDATE` cannot tell "no such id" from
    anything else.
    """
    current = conn.execute(_SELECT_MARKER_FOR_UPDATE, (marker_id,)).fetchone()
    if current is None:
        raise _refusal(MARKER_NOT_FOUND, NO_SUCH_MARKER, status.HTTP_404_NOT_FOUND)

    sent = body.model_fields_set
    existing = _as_marker(current)
    name, width_mm, height_mm, dictionary, aruco_id = _validated(
        body.name if "name" in sent else existing.name,
        body.width_mm if "width_mm" in sent else existing.width_mm,
        body.height_mm if "height_mm" in sent else existing.height_mm,
        body.aruco_dictionary if "aruco_dictionary" in sent else existing.aruco_dictionary,
        body.aruco_id if "aruco_id" in sent else existing.aruco_id,
    )

    try:
        row = conn.execute(
            _UPDATE_MARKER,
            (name, width_mm, height_mm, dictionary, aruco_id, marker_id),
        ).fetchone()
    except pg_errors.UniqueViolation as duplicate:
        if duplicate.diag.constraint_name != NAME_UNIQUE_INDEX:
            raise
        raise _refusal(
            DUPLICATE_MARKER_NAME, ALREADY_REGISTERED, status.HTTP_409_CONFLICT
        ) from duplicate

    assert row is not None  # noqa: S101 — the locking read above proved the row exists
    marker = _as_marker(row)

    # `details` carries what the Marker now is. The entry that recorded it
    # before still carries what it was, which is what makes the pair readable
    # as a change — the log is append-only (AD-4) and nothing rewrites history.
    audit.record(
        conn,
        action=AuditAction.MARKER_EDITED,
        actor_id=administrator.id,
        actor_email=administrator.email,
        target_id=marker.id,
        source_ip=source_ip,
        details=_details(marker),
    )

    response.headers.update(NO_STORE)
    return marker


@router.delete("/admin/markers/{marker_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_marker(
    marker_id: UUID,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
) -> None:
    """Withdraw a Marker — a card that has been lost, reprinted or mismeasured.

    **Real removal, and nothing cascades.** No table references `marker` and
    `marker` references none, so this is one row and one row only. No Scan is
    affected: a measurement is a suggestion that pre-fills the Size picker for
    one submission and is never stored, and the Size a staff member actually
    declared lives on the Scan row.

    **`204`, with no body**, exactly as `remove_tile` and `delete_user` answer.

    **Not idempotent, on purpose.** An unknown id is `404`, not a silent `204`:
    an Administrator told "removed" about a card that was never registered has
    been told they removed something they did not — and would stop looking for
    the one that is still there.

    The entry is written after the `DELETE` and inside its transaction, with an
    AD-10 snapshot taken from the locked read because there is nothing left to
    read it from afterwards.
    """
    row = conn.execute(_SELECT_MARKER_FOR_UPDATE, (marker_id,)).fetchone()
    if row is None:
        raise _refusal(MARKER_NOT_FOUND, NO_SUCH_MARKER, status.HTTP_404_NOT_FOUND)

    removed = _as_marker(row)
    conn.execute(_DELETE_MARKER, (marker_id,))

    audit.record(
        conn,
        action=AuditAction.MARKER_REMOVED,
        actor_id=administrator.id,
        actor_email=administrator.email,
        target_id=removed.id,
        source_ip=source_ip,
        details=_details(removed),
    )
