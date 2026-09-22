"""The `ScanCandidate` and `ScanHistoryEntry` contracts.

`ScanCandidate` is one ranked match `POST /scans` answers with. Story 3.4
wires Epic 2's tested vector search into the Scan surface: a cropped,
quality-gated photo becomes up to three of these, best match first. The
array's own order **is** the rank — there is no `rank` field, because a
client that reads the ordinal off a field can also read it off the wrong one,
and the array index cannot drift from itself.

**No similarity value has a field here, and none ever may** (AD-20). A
correct top-1 and a wrong one score close enough, and a frame of pure noise
still scores candidates above a number that would read as confidence — the
score decides ranking, server-side, and stops there.

**No storage URL either** (AD-9). A candidate's picture is fetched from
`GET /tiles/{tileId}/images/{imageId}`, which re-checks the caller's session
on every request; the id below is the only handle a client gets, the same
shape `tile.py`'s `ReferenceImage` already argues for.

`ScanHistoryEntry` is Story 3.5's addition: one past Scan a caller submitted,
as `GET /scans` renders it — a timestamp and the same closed `ScanCandidate`
array the original `POST /scans` answered with, persisted as a denormalized
snapshot (AD-10) rather than re-derived from the catalogue on every read.

`shared_schema/ts/scan.ts` is the TypeScript twin. The two files are one
contract in two languages and change together or not at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_serializer


class ScanCandidate(BaseModel):
    """One ranked match for a submitted Scan.

    Closed shape, `Tile`'s own reason: the TypeScript twin rejects a body
    carrying any key beyond the contract, so a `score` or a `source_key`
    reaching this model from a later change is a loud failure rather than a
    field a screen quietly starts reading.

    `tile_id` and `code` name the Tile (AD-18: the Code is the identity);
    `size` and `category` are the resolved, normalized groupings a reader
    checks a Code against, sent as plain strings for `Tile`'s own reason — a
    client has nothing to do with the underlying row ids. `image_id` builds
    the proxied path to the Tile's earliest Reference Image, the same "first
    image" `CatalogueScreen.thumbnail` already renders.
    """

    model_config = ConfigDict(extra="forbid")

    tile_id: UUID
    code: str
    size: str
    #: Always populated in practice — the `UNKNOWN` sentinel when nothing was
    #: recovered — and nullable anyway because the ERD says so, `Tile.category`'s
    #: own reason.
    category: str | None
    image_id: UUID


#: How many entries one page of a caller's own scan history carries.
#:
#: `shared_schema.audit.PAGE_SIZE`'s own reasoning, restated rather than
#: imported — `tile.py`'s own cross-import reasoning: this module owns its
#: two published constants rather than reaching into a sibling contract for
#: them, so a change to the audit log's page size can never silently move
#: this one with it. `GET /scans` declares no `limit` parameter and never
#: will: the client is told this number, it never chooses it, and a page
#: shorter than it is what lets the screen tell a last page from a full one
#: — the bare-array response says nothing else about what follows it.
HISTORY_PAGE_SIZE = 50

#: The query parameter the keyset cursor travels in —
#: `GET /scans?before=<id of the oldest row already rendered>`.
#:
#: `shared_schema.audit.CURSOR_PARAM`'s own twin, restated for the same
#: reason `HISTORY_PAGE_SIZE` is. `apps/api/api/scan.py`'s `read_scan_history`
#: reads the query string by this name, and `ts/scan.ts`'s
#: `HISTORY_CURSOR_PARAM` is the client's own copy of it.
HISTORY_CURSOR_PARAM = "before"


class ScanHistoryEntry(BaseModel):
    """One past Scan, as `GET /scans` renders it (Story 3.5).

    A denormalized snapshot (AD-10), not a live re-fetch: `candidates` is the
    same closed `ScanCandidate` array `POST /scans` answered with at the time,
    stored and served back byte-identical — the Code, Size and Category on a
    history entry read exactly as they did the moment the scan was submitted,
    whether or not the Tile they matched still exists. An empty list is a real
    answer (no confident match), never the absence of one.

    Closed shape, `ScanCandidate`'s own reason: the TypeScript twin rejects a
    body carrying any key beyond the contract, so a column added to the table
    and forgotten here is a loud failure rather than a field a screen quietly
    starts reading.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    # The database clock, never the application's. Written once and never
    # moved: a Scan is a record of what happened at submission time, not a
    # row anything in this product edits afterward.
    created_at: AwareDatetime
    candidates: list[ScanCandidate]

    @field_serializer("created_at", when_used="json")
    def _in_utc(self, value: datetime) -> str:
        """Emit the timestamp in UTC, whatever offset it arrived with.

        `AuditLogEntry._in_utc`'s own reason: `timestamptz` comes back from
        the driver in the *session's* time zone, so an API process whose
        session is not UTC would put that offset on the wire instead of the
        spine's ISO 8601 UTC convention.
        """
        return value.astimezone(UTC).isoformat()
