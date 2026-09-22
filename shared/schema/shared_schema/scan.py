"""The `ScanCandidate` contract — one ranked match `POST /scans` answers with.

Story 3.4 wires Epic 2's tested vector search into the Scan surface: a
cropped, quality-gated photo becomes up to three of these, best match first.
The array's own order **is** the rank — there is no `rank` field, because a
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

`shared_schema/ts/scan.ts` is the TypeScript twin. The two files are one
contract in two languages and change together or not at all.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
