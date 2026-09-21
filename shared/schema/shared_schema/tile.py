"""The `Tile` and `ReferenceImage` contracts, shared by `apps/web` and `apps/api`.

The field set is the architecture spine's ERD `TILE` and `REFERENCE_IMAGE`
blocks. The glossary names are used verbatim, and two words are **retired**:
`Product` and `Face` were the identity model AD-18 corrects and must not appear
as a type, a field or a label anywhere in new code. `Design` survives only as a
legacy key inside the POC's `meta.json`, never as a domain term.

**The Code is the identity** (AD-18). One catalogue row per file; every file in
a category folder is a different Tile. `Size` and `Category` are groupings, and
`face_number` is a nullable display hint that nothing may key, group or match
on — the dash-delimited names in the real tree carry no recoverable trailing
number at all.

**No similarity value has a field here, and none ever may** (AD-20). A Candidate
carries a Code, a Size, a Category and a reference image, and the score stays
server-side.

`shared_schema/ts/tile.ts` is the TypeScript twin. The two files are one
contract in two languages and change together or not at all.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_serializer

#: The AD-18 sentinel, as a real value rather than a NULL.
#:
#: A Tile whose Category could not be recovered from the source tree is grouped
#: under this, never dropped — and because it is a row in `tile_category` like
#: any other, no query has to special-case the absence. Spelled here because
#: three writers need the same word: the migration that seeds the row,
#: `apps/api`'s resolver, and `scripts/ingest`.
UNKNOWN_CATEGORY = "UNKNOWN"

#: Bounds on what the API will store. Generous, and about the *column* rather
#: than about what a Code looks like: the real tree holds
#: `RP.CMA.0001DJ.SM.0T`, `1Jk`, `279` and `6LD.MA Quarry Stone Natural`, and a
#: pattern tight enough to reject a bad Code would reject four of the five
#: naming conventions that genuinely exist.
MAX_CODE_LENGTH = 200
MAX_SIZE_LENGTH = 100
MAX_CATEGORY_LENGTH = 200

#: How many Reference Images one add may carry. A Tile in the real catalogue
#: has exactly one; FR-14/15 allow several, and this bounds a single request
#: rather than the Tile — eight images is 128 embeddings and a minute of CPU,
#: which is already the outer edge of what one HTTP request should own. A whole
#: range goes through Story 2.4's bulk path, which reports per row.
MAX_IMAGES_PER_REQUEST = 8

#: The byte ceiling on one uploaded file — 128 MB. The real reference set runs
#: to 96 MB originals, so this is above the largest asset anyone has and still
#: a bound; the pixel gate in `shared_vision.intake` is the one that matters,
#: and this is what stops a file reaching it at all.
#:
#: Written out rather than as `128 * 1024 * 1024` because `apps/web` mirrors it
#: onto the Add tile screen — which refuses an oversized file *before*
#: uploading it — and `error-code-parity.test.ts` pins the two together by
#: reading this line as an integer literal. An expression here would make that
#: comparison silently compare against nothing.
MAX_IMAGE_BYTES = 134217728

_WHITESPACE = re.compile(r"\s+")


def normalize_label(value: str) -> str:
    """The stored form of a Size or a Category: trim, collapse, uppercase.

    The POC's `normalize_folder` rule, and the one statement of it. Both
    writers — `apps/api`'s catalogue endpoints and `scripts/ingest` — resolve
    against the same create-if-missing lookup on this value, which is what
    stops `45X90`, `45x90` and `" 45X90 "` becoming three sizes nothing can
    join on (spine, Consistency Conventions).

    Internal whitespace is collapsed as well as trimmed: `"Crema  Marmol"` and
    `"Crema Marmol"` are the same range, and a double space is exactly the kind
    of thing that survives a copy out of a spreadsheet.
    """
    return _WHITESPACE.sub(" ", value).strip().upper()


def _has_control_character(value: str) -> bool:
    """Whether `value` holds a character Postgres text cannot carry or display.

    `api.users._has_control_character`'s argument, applied to this module's
    `text` columns for the same reason: a C string cannot carry a NUL, so
    Postgres text cannot hold one and psycopg raises rather than sending it.
    That raise would escape as a `500` where every other refused field gets a
    `422`. The rest of the control range goes with it — none of it belongs in a
    Code, and it renders as nothing at all on Story 2.5's catalogue list, which
    is a Tile nobody can identify created by a form that reported success.
    """
    return any(character < " " or character == "\x7f" for character in value)


def clean_code(value: str) -> str:
    """The Code as it will be stored, or a `ValueError` naming the rule it broke.

    Whitespace-trimmed and nothing else. The Code is a **file name**, cleaned
    of the `Copy of ` prefix and the extension, and its case is part of it —
    uppercasing it the way a Size is uppercased would turn `1Jk` into `1JK`,
    which is a different string from the one on the tile.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("A Code must not be blank.")
    if len(stripped) > MAX_CODE_LENGTH:
        raise ValueError(f"A Code must be at most {MAX_CODE_LENGTH} characters.")
    if _has_control_character(stripped):
        raise ValueError("A Code must not contain control characters.")
    return stripped


def clean_size(value: str) -> str:
    """The Size as it will be resolved, normalized, or a `ValueError`."""
    normalized = normalize_label(value)
    if not normalized:
        raise ValueError("A Size must not be blank.")
    if len(normalized) > MAX_SIZE_LENGTH:
        raise ValueError(f"A Size must be at most {MAX_SIZE_LENGTH} characters.")
    if _has_control_character(normalized):
        raise ValueError("A Size must not contain control characters.")
    return normalized


def clean_category(value: str | None) -> str:
    """The Category as it will be resolved — the sentinel when nothing was given.

    **Never a refusal for being absent** (AD-18): a Tile with no recoverable
    Category is indexed under `UNKNOWN` and flagged for follow-up, because
    dropping it would remove a real tile from the catalogue over a grouping
    attribute that is not its identity.
    """
    normalized = normalize_label(value or "")
    if not normalized:
        return UNKNOWN_CATEGORY
    if len(normalized) > MAX_CATEGORY_LENGTH:
        raise ValueError(f"A Category must be at most {MAX_CATEGORY_LENGTH} characters.")
    if _has_control_character(normalized):
        raise ValueError("A Category must not contain control characters.")
    return normalized


class ReferenceImage(BaseModel):
    """One image of a Tile, as the API renders it.

    Closed shape, for the reason `User` is closed: the TypeScript twin rejects
    a body carrying any key beyond the contract, and pydantic's default is to
    accept and silently discard.

    **No storage key, no URL, no byte count of the original.** AD-9 forbids
    `apps/web` ever holding a directly-usable storage reference, and the way to
    make that structurally true is to give the contract nowhere to put one: the
    image is fetched from `GET /admin/tiles/{tile_id}/images/{image_id}`, which
    re-checks authorization and proxies the bytes. The id below is what builds
    that path, and it is the only handle the client gets.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    #: The dimensions of the colour-managed, 2048px-capped asset — what the
    #: pipeline actually saw, not what the operator uploaded. The derivative
    #: served to the browser is smaller again (AD-17).
    width: int
    height: int
    #: FR-19's flag: below the texture threshold, this image matches any
    #: washed-out photo and can never be reliably retrieved itself. Surfaced on
    #: the Tile's own screen rather than only in a report.
    featureless: bool
    created_at: AwareDatetime

    @field_serializer("created_at", when_used="json")
    def _in_utc(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class Tile(BaseModel):
    """A catalogue entry — **one file, one Tile** (AD-18).

    `code` is the identity and the answer a Scan returns. `size` and `category`
    are the resolved, normalized names of their reference rows, sent as plain
    strings because a client has nothing to do with their ids. `face_number` is
    a display hint and nothing else.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    size: str
    #: Always populated in practice — the sentinel when nothing was recovered —
    #: and nullable anyway because the ERD says so and a reader should not
    #: infer that `UNKNOWN` is a domain value.
    category: str | None
    face_number: str | None
    reference_images: list[ReferenceImage]
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_serializer("created_at", "updated_at", when_used="json")
    def _in_utc(self, value: datetime) -> str:
        """Emit every timestamp in UTC, whatever offset it arrived with.

        `shared_schema.user.User._in_utc`'s argument, unchanged: `timestamptz`
        comes back from the driver in the session's time zone, and the twin's
        `isUtcTimestamp` accepts only a UTC designator.
        """
        return value.astimezone(UTC).isoformat()
