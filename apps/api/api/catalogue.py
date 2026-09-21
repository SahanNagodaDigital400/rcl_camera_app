"""`/admin/tiles` — the Catalogue's write path, and the query that proves it worked.

Four routes and one function that is not a route:

* `POST /admin/tiles` (FR-14) takes a Code, a Size, an optional Category and
  one to eight reference images, and creates a Tile that a Scan can return in
  the same session.
* `PATCH /admin/tiles/{tile_id}` (FR-15) corrects one: its Code, its Size, its
  Category, and the Reference Images it carries — adding new ones through the
  *same* intake, embedding and derivative path the add uses, and removing old
  ones for real.
* `GET /admin/tiles/lookup?code=` finds one Tile by an **exact** Code, which is
  the whole door the edit screen has until Story 2.5 ships the Catalogue list.
  Not a search: no substring, no listing, no pagination.
* `GET /admin/tiles/{tile_id}/images/{image_id}` serves AD-17's capped
  derivative, and only that — the retained source asset has no route at all.
* `find_candidates` is the max-over-views search. It lives here, with the
  write path it validates, because "the Tile is immediately findable" is this
  story's acceptance criterion and the Scan surface does not exist until Epic
  3. Epic 3 wraps this function in an endpoint rather than writing a second
  one — a second query is exactly the asymmetry AD-1 is about, one level up
  from the pixels.

What is load-bearing here, in the order it happens:

**Authorization is a dependency, never a line in the handler.**
`require_administrator` refuses a Staff caller before this module's code runs
at all — before a byte is decoded, before the ONNX session is touched, before
anything is written. `tests/test_admin_authorization.py` reads that off the
path in both directions.

**Every image byte goes through `shared_vision.intake_image` and nothing
else** (AD-7). Content is sniffed; neither the file name nor the client's
`content-type` is consulted anywhere in this file. Colour management to sRGB at
relative colorimetric intent runs first (AD-15), then the EXIF transpose, then
the strip, then the re-encode. This module never calls `Image.open`.

**16 embeddings per image, never pooled** (AD-13). Four clean rotations of the
full frame and twelve randomized augmented crops, written as separate
`reference_embedding` rows. Pooling them into one vector at write time would
give back the scale invariance the crops exist to buy, and nothing about it
would raise.

**The pipeline stamp is checked against the active generation, not per row**
(AD-14). One `embedding_generation` row is active at a time — the database
enforces that with a partial unique index — and a write whose running pipeline
does not match it is a hard error rather than a quiet mixing of two pipelines'
vectors.

**Storage first, database second, and the storage writes are undone on a
failure.** A Tile row pointing at bytes that are not there is unrecoverable
from inside the product; an orphaned object is a file an operator can delete.
So the objects are written, the transaction runs, and every key written by a
request that then failed is removed before the refusal is returned.

**The add and its audit entry share one `with conn.transaction():`**, exactly
as `api.users` does: a Tile that exists always has a record of who added it,
and an entry that cannot be written takes the Tile down with it. A refusal
writes no entry at all — a `409`, a `422` or a `413` changed nothing, so there
is nothing to record. The edit is the same shape, one story later.

**Removal is real removal** (AD-5, epic context). `edit_tile` issues
`DELETE FROM reference_image` so that `reference_embedding` cascades out of the
index: there is no soft-delete flag and no query-time predicate, because a
predicate is a thing exactly one call site has to remember and Epic 3's scan is
the call site that must not forget. The one asymmetry with the add's ordering
is deliberate and is argued for at `edit_tile`: objects belonging to *removed*
images are deleted **after** the commit, because a live row pointing at absent
bytes is the unrecoverable state and an orphaned object is not.

**A Tile always keeps at least one Reference Image.** An edit whose net effect
is zero images is refused (FR-7): the reference image is what lets a member of
staff verify a Code they do not recognise, so a Tile without one is a catalogue
row nobody can check and a Candidate nobody can confirm.

**No presigned or direct-to-storage URL, in either direction** (AD-9). The
`Tile` contract has nowhere to put one and this module returns none; bytes are
proxied by the `GET` below, which re-checks authorization on every request.

**No similarity value reaches `apps/web`** (AD-20). `find_candidates` returns
the score because ranking and every server log line need it; nothing on the
`Tile` contract carries one, and no route here emits one.

Not here, deliberately: the Tile removal (2.3), the bulk path (2.4), the
catalogue **list and substring search** (2.5), Epic 3's scan endpoint, and any
crop step — AD-11 resolved that one explicitly as *no* for admin uploads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID, uuid4

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a handler's
# annotations at runtime to build its dependency graph.
import psycopg
import shared_vision
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from PIL import Image
from psycopg import errors as pg_errors
from shared_schema.errors import ApiError
from shared_schema.tile import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_REQUEST,
    ReferenceImage,
    Tile,
    clean_category,
    clean_code,
    clean_size,
)
from shared_schema.user import User

# `api.audit` owns the only INSERT against the audit table in the repository
# and `tests/test_source_guards.py` forbids a second file from so much as
# naming it (AD-4). This module records through it and names nothing.
from api import audit
from api.audit import AuditAction
from api.db import get_connection
from api.dependencies import NO_STORE, require_administrator
from api.storage import ObjectNotFound, ObjectStore, get_object_store

logger = logging.getLogger("rocell.api.catalogue")

router = APIRouter(tags=["catalogue"])


# --- Envelope codes -----------------------------------------------------------
# Each is a code of its own rather than the generic `validation_error`, for the
# reason `api.users.INVALID_EMAIL` gives: `api.main.validation_error_handler`
# renders one sentence for every 422 in the product and names no field, so an
# Administrator who mistyped one thing would be told nothing they can act on.
# `apps/web`'s `error-code-parity.test.ts` pins every spelling below that the
# client exports.

INVALID_CODE = "invalid_code"
INVALID_SIZE = "invalid_size"
INVALID_CATEGORY = "invalid_category"
INVALID_IMAGE = "invalid_image"
UNREADABLE_IMAGE = "unreadable_image"
IMAGE_TOO_LARGE = "image_too_large"
TOO_MANY_IMAGES = "too_many_images"
CODE_ALREADY_EXISTS = "code_already_exists"
IMAGE_NOT_FOUND = "image_not_found"
TILE_NOT_FOUND = "tile_not_found"
LAST_REFERENCE_IMAGE = "last_reference_image"
MATCHING_UNAVAILABLE = "matching_unavailable"
PIPELINE_STAMP_MISMATCH = "pipeline_stamp_mismatch"

#: What a caller who sent no image at all is told. Named, because "add a Tile"
#: without a reference image is a catalogue row a Scan can never return and a
#: member of staff can never verify (FR-7: the picture is what makes the answer
#: usable).
NO_IMAGE = "Add at least one reference image."

#: The limit, in the refusal, because an Administrator with nine files needs to
#: know where to split them rather than that nine is too many.
TOO_MANY = (
    f"Add at most {MAX_IMAGES_PER_REQUEST} reference images at a time. "
    "Use Bulk upload for a whole range."
)

#: A file that is not an image, or is empty, or stops halfway. Worded about the
#: file rather than about the format: the extension was never consulted, so
#: naming one would suggest renaming it would help.
NOT_AN_IMAGE = "That file is not a readable image."

#: Above the ceiling. The byte and pixel limits produce one sentence between
#: them because the Administrator's answer is the same either way.
TOO_LARGE = (
    f"That image is too large. The limit is {MAX_IMAGE_BYTES // (1024 * 1024)} MB and "
    f"{shared_vision.REFERENCE_MAX_PIXELS // 1_000_000} megapixels."
)

#: The Code is the identity (AD-18), so a duplicate is a genuine conflict and
#: not a near-miss to be resolved by adding a suffix. The sentence says what
#: the Administrator can do about it.
CODE_IN_USE = "A tile with that code already exists. Edit that tile, or use a different code."

#: The pair names no Reference Image. One sentence for "no such tile", "no such
#: image" and "that image belongs to another tile", because they are the same
#: fact to a caller holding a pair that names nothing — and telling them apart
#: would confirm which ids exist. Shared by the image read and by the edit's
#: removal check, which must refuse another Tile's image the same way.
NO_SUCH_IMAGE = "No reference image has that id."

#: The id, or the Code, names no Tile. A `404` for both, so the screen refetches
#: rather than retrying — and worded without repeating back what was asked for,
#: because the same sentence answers a lookup by Code and an edit by id.
NO_SUCH_TILE = "No tile matches that. It may have been renamed or removed."

#: FR-7's floor, as a refusal. A Tile with no Reference Image is a catalogue row
#: no member of staff can verify and no Scan can return, so an edit that would
#: leave one that way is refused rather than accepted and flagged. The sentence
#: names the way through, because the Administrator replacing a bad asset with a
#: good one is doing exactly the thing this rule looks like it forbids.
LAST_IMAGE = (
    "A tile must keep at least one reference image. "
    "Add the replacement in the same save, or remove the tile instead."
)

#: The unique index the 409 is built from, by name. Postgres reports it as
#: `constraint_name` on the `UniqueViolation`, and this handler answers
#: `code_already_exists` for that name and for no other — a clash on any other
#: index (the primary key, or one a later migration adds) propagates and is
#: answered as a 500, which is honest, rather than pointing the Administrator
#: at a Code that is fine.
CODE_UNIQUE_INDEX = "tile_code_key"

#: The model artifact is absent. A `503` rather than a `500`: nothing about the
#: request is wrong, the service is missing a prerequisite, and the sentence
#: names the step that installs it.
NOT_INSTALLED = shared_vision.MODEL_MISSING

#: AD-14's hard error. A stamp mismatch means the running pipeline did not
#: build the generation being written to or searched, and mixing the two is
#: exactly the silent accuracy loss AD-1 and AD-14 exist to prevent. A `503`,
#: because the deployment is inconsistent rather than the request wrong, and
#: the fix is a re-index rather than anything a caller can do.
STAMP_MISMATCH = (
    "The catalogue index was built by a different version of the image pipeline. "
    "A re-index is required before tiles can be added or matched."
)

#: How many Candidates a search returns. Three, always (FR-7, AGENTS.md): size
#: and finish are not recoverable from a photo, so a single answer is
#: confidently wrong. Deliberately separate from whatever a screen chooses to
#: display (AD-20).
TOP_K = 3

#: Why `_discard` was called, for its log line and for nothing else. The two
#: cases leave an identical orphaned object behind, and an operator reading the
#: warning cannot otherwise tell a write that was undone from a removal whose
#: bytes could not follow it.
DISCARD_ROLLED_BACK = "the write was rolled back"
DISCARD_REMOVED = "the reference image was removed"

#: Sent with the reference-image bytes and with nothing else in the product.
#: See `read_reference_image` for why this one response needs it.
NO_SNIFF = {"x-content-type-options": "nosniff"}


def _refusal(code: str, message: str, status_code: int) -> ApiError:
    """One constructor for every refusal here. `api.users`'s error-factory idiom."""
    return ApiError(code, message, status_code=status_code, headers=NO_STORE)


# --- Statements ---------------------------------------------------------------
# Every one is parameterized; nothing below is assembled from a value
# (`tests/test_source_guards.py`). The vector parameters are passed as text and
# cast in SQL (`%s::vector`), which is what lets this module talk to pgvector
# without the `pgvector` Python package and without a line of concatenation.

#: Create-if-missing, in one statement, on the normalized name.
#:
#: `ON CONFLICT ... DO UPDATE` rather than `DO NOTHING`, and the difference is
#: a race rather than a style: `DO NOTHING RETURNING id` returns no row when
#: another transaction has inserted the same name and not yet committed, and
#: the follow-up `SELECT` cannot see that uncommitted row either — so two
#: concurrent adds of the first tile in a new Size would leave one of them with
#: nothing. `DO UPDATE` takes the lock, waits, and returns the winning row.
#: The "update" is a no-op assignment of the value that is already there.
_RESOLVE_SIZE = """
INSERT INTO tile_size (name) VALUES (%s)
ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
RETURNING id
"""

_RESOLVE_CATEGORY = """
INSERT INTO tile_category (name) VALUES (%s)
ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
RETURNING id
"""

#: The id is supplied rather than left to `gen_random_uuid()` because the
#: storage keys are built from it and the objects are written before this runs.
_INSERT_TILE = """
INSERT INTO tile (id, code, size_id, category_id)
VALUES (%s, %s, %s, %s)
RETURNING id, code, face_number, created_at, updated_at
"""

_INSERT_REFERENCE_IMAGE = """
INSERT INTO reference_image (id, tile_id, source_key, derivative_key, sha256,
                             width, height, source_bytes, derivative_bytes,
                             pixel_std, featureless)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id, width, height, featureless, created_at
"""

_INSERT_EMBEDDING = """
INSERT INTO reference_embedding (reference_image_id, generation_id, embedding,
                                 view_kind, view_index)
VALUES (%s, %s, %s::vector, %s, %s)
"""

#: The duplicate-Code pre-flight. A read, and never the decision — see
#: `add_tile`. `SELECT 1` rather than the row: nothing needs the tile, only
#: whether there is one.
_SELECT_CODE = """
SELECT 1 FROM tile WHERE code = %s
"""

#: The same pre-flight for an *edit*, which must not collide with the Tile's own
#: Code. Without the second arm, saving a form whose Code was never touched
#: would answer `409 code_already_exists` against the very row being edited.
_SELECT_CODE_ELSEWHERE = """
SELECT 1 FROM tile WHERE code = %s AND id <> %s
"""

#: Does this id name a Tile at all. `add_tile`'s `_SELECT_CODE` reasoning, for
#: the edit's `404`: a read, taken before tens of seconds of embedding, and
#: never the decision — the locking read inside the transaction is.
_SELECT_TILE = """
SELECT 1 FROM tile WHERE id = %s
"""

#: The Tile as a caller sees it, locked for the duration of the edit.
#:
#: **`FOR UPDATE OF t`, not a bare `FOR UPDATE`.** The Category join is an outer
#: one — the column is nullable in the ERD — and PostgreSQL refuses a row lock
#: taken across the nullable side of an outer join. Naming the table is also the
#: honest statement of intent: this edit writes `tile` and nothing else here, so
#: locking the two reference rows would make two concurrent edits of unrelated
#: Tiles that happen to share a Size wait on each other.
#:
#: Distinguishes a `404` from every other outcome by *reading*, rather than by
#: guessing at a zero-row `UPDATE` — `api.users._SELECT_USER_FOR_UPDATE`'s
#: argument, unchanged.
_SELECT_TILE_FOR_UPDATE = """
SELECT t.id, t.code, t.face_number, t.created_at, t.updated_at,
       s.name AS size, c.name AS category
  FROM tile t
  JOIN tile_size s ON s.id = t.size_id
  LEFT JOIN tile_category c ON c.id = t.category_id
 WHERE t.id = %s
   FOR UPDATE OF t
"""

#: The same shape without the lock, keyed on the Code.
#:
#: **Equality, never a pattern.** `LIKE`, `ILIKE` and `%` are Story 2.5's
#: substring search, and the difference is not a nicety: a prefix match that
#: returned "the" Tile would answer one of several and the Administrator would
#: edit whichever row sorted first.
_SELECT_TILE_BY_CODE = """
SELECT t.id, t.code, t.face_number, t.created_at, t.updated_at,
       s.name AS size, c.name AS category
  FROM tile t
  JOIN tile_size s ON s.id = t.size_id
  LEFT JOIN tile_category c ON c.id = t.category_id
 WHERE t.code = %s
"""

#: One Tile's Reference Images, in the `ReferenceImage` contract's own shape —
#: no storage key, no byte count of the original (AD-9). Ordered so that the
#: screen renders them the same way twice.
_SELECT_TILE_IMAGES = """
SELECT id, width, height, featureless, created_at
  FROM reference_image
 WHERE tile_id = %s
 ORDER BY created_at, id
"""

#: **`updated_at` is set by hand.** This schema carries no BEFORE UPDATE trigger
#: — the migration's own header says so, and `api.users` sets it the same way —
#: and the column's DEFAULT applies to inserts only.
#:
#: Every column is written unconditionally rather than through `COALESCE`,
#: because `edit_tile` has already resolved "absent means unchanged" against the
#: locked row: a multipart body has no `null` on the wire, so the distinction
#: cannot be pushed down into SQL the way `_UPDATE_USER` pushes it.
_UPDATE_TILE = """
UPDATE tile
   SET code = %s,
       size_id = %s,
       category_id = %s,
       updated_at = now()
 WHERE id = %s
RETURNING id, code, face_number, created_at, updated_at
"""

#: Real removal (AD-5). `reference_embedding` cascades from this by the
#: migration's own `ON DELETE CASCADE`, so the views leave the searchable graph
#: with the row rather than being filtered out at query time.
#:
#: **Both ids in the predicate**, for `_SELECT_DERIVATIVE_KEY`'s reason: an
#: image id borrowed from another Tile must delete nothing, and a zero-row
#: result is what `edit_tile` turns into `404 image_not_found`.
#:
#: The two keys come back because the objects behind them are removed *after*
#: the commit and nothing else in the request knows them.
_DELETE_REFERENCE_IMAGE = """
DELETE FROM reference_image
 WHERE id = %s AND tile_id = %s
RETURNING source_key, derivative_key
"""

_SELECT_ACTIVE_GENERATION = """
SELECT id, pipeline_version, config_hash
  FROM embedding_generation
 WHERE is_active
"""

_INSERT_ACTIVE_GENERATION = """
INSERT INTO embedding_generation (pipeline_version, config_hash, is_active)
VALUES (%s, %s, true)
RETURNING id, pipeline_version, config_hash
"""

#: AD-13's max-over-views, in SQL.
#:
#: **A grouped scan, not a k-NN probe, and that is a correctness decision.**
#: `<#>` is pgvector's negative inner product, so with unit-norm vectors (AD-5)
#: the *smallest* `<#>` is the *largest* similarity: `min()` per Tile
#: reproduces the POC's `np.maximum.at` over views exactly, and `-min()` is the
#: score. An HNSW `ORDER BY ... LIMIT` probe would rank *vectors* and then need
#: a second pass to collapse them to Tiles, which can drop a Tile whose best
#: view sits just outside the probe's window. At this catalogue's real size
#: (381 tiles x 16 views is about 6k vectors) the scan is milliseconds; the
#: HNSW index still earns its place per AD-5, because that is what makes an
#: insert immediately searchable with no rebuild.
#:
#: **Grouped by Tile, never by Size or Category** (AD-18). Three candidates
#: from `45X90/POLISH` are three distinct answers competing on merit, and
#: collapsing them would hide correct ones.
_SELECT_CANDIDATES = """
SELECT t.id AS tile_id,
       t.code,
       s.name AS size,
       c.name AS category,
       t.face_number,
       -min(e.embedding <#> %s::vector) AS score
  FROM reference_embedding e
  JOIN reference_image ri ON ri.id = e.reference_image_id
  JOIN tile t ON t.id = ri.tile_id
  JOIN tile_size s ON s.id = t.size_id
  LEFT JOIN tile_category c ON c.id = t.category_id
 WHERE e.generation_id = %s
 GROUP BY t.id, t.code, s.name, c.name, t.face_number
 -- `t.code` breaks a tie deterministically. Two Tiles at an identical distance
 -- are not hypothetical here: the same artwork can be catalogued under two
 -- Codes, and without a second key the three candidates a Scan shows would
 -- differ between two runs of the same query.
 ORDER BY min(e.embedding <#> %s::vector), t.code
 LIMIT %s
"""

#: Both ids, never just the image's. A caller holding one Tile's id must not be
#: able to read another Tile's image by pairing it with a guessed image id —
#: and a mismatched pair is a `404`, not a `403`, because the pair names
#: nothing rather than naming something forbidden.
_SELECT_DERIVATIVE_KEY = """
SELECT derivative_key
  FROM reference_image
 WHERE id = %s AND tile_id = %s
"""


def _vector_literal(vector: Any) -> str:
    """One embedding as the text pgvector's input parser accepts.

    Passed as an ordinary parameter and cast in SQL (`%s::vector`), so nothing
    here is string-built SQL: the value never becomes part of a statement. This
    is what keeps the `pgvector` Python package — and a second set of type
    adaptation rules over the same column — out of the dependency list.
    """
    return "[" + ",".join(repr(float(component)) for component in vector) + "]"


# --- Generations (AD-14) ------------------------------------------------------


def _verify_stamp(row: dict[str, Any]) -> UUID:
    """The generation's id, or AD-14's hard refusal if it is not ours.

    **The check is global, not per row.** AD-14 is explicit: a search compares
    the running pipeline's stamp against the single active generation, and a
    mismatch is a hard error rather than a degraded search. Nothing here ever
    rewrites a stamp — a re-index is a complete new generation cut over by
    flipping `is_active`, not a per-row migration.
    """
    if (
        row["pipeline_version"] != shared_vision.PIPELINE_VERSION
        or row["config_hash"] != shared_vision.config_hash()
    ):
        # Logged as well as refused: the operator needs both stamps to know
        # which way round the mismatch is, and the envelope deliberately
        # carries neither — an error message is not a place to publish the
        # build's internals.
        logger.error(
            "pipeline stamp mismatch: index %s/%s, running %s/%s",
            row["pipeline_version"],
            row["config_hash"],
            shared_vision.PIPELINE_VERSION,
            shared_vision.config_hash(),
        )
        raise _refusal(PIPELINE_STAMP_MISMATCH, STAMP_MISMATCH, status.HTTP_503_SERVICE_UNAVAILABLE)

    generation_id: UUID = row["id"]
    return generation_id


def active_generation(conn: psycopg.Connection) -> UUID | None:
    """The active generation's id, or `None` when the catalogue has none.

    **Read-only, and that is the whole point of it being separate.** A search
    must not write: a scan against an empty catalogue that opened a generation
    row would make the read path a writer, would need the write privileges and
    the transaction the read path does not otherwise have, and would leave a
    row behind for every probe of a catalogue nobody has populated yet. Only
    `ensure_active_generation` below creates one, and only the add path calls
    it.

    A stamp that is not the running pipeline's is still refused here: reading
    is exactly where AD-14 says the check belongs.
    """
    row = conn.execute(_SELECT_ACTIVE_GENERATION).fetchone()
    return None if row is None else _verify_stamp(row)


def ensure_active_generation(conn: psycopg.Connection) -> UUID:
    """`active_generation`, opening the first one when the catalogue is empty.

    Called by the write path alone, inside its transaction, so the generation
    a Tile's embeddings belong to is created and used in one unit of work.
    """
    generation_id = active_generation(conn)
    if generation_id is not None:
        return generation_id

    # First write into an empty catalogue. Two concurrent first-writes race
    # here; the partial unique index on `is_active` decides between them, and
    # the loser reads the winner's row. The nested `transaction()` is a
    # savepoint, so the violation does not abort the caller's unit of work.
    try:
        with conn.transaction():
            row = conn.execute(
                _INSERT_ACTIVE_GENERATION,
                (shared_vision.PIPELINE_VERSION, shared_vision.config_hash()),
            ).fetchone()
    except pg_errors.UniqueViolation:
        row = conn.execute(_SELECT_ACTIVE_GENERATION).fetchone()

    assert row is not None, "the active-generation re-read cannot come back empty"
    return _verify_stamp(row)


# --- Search (AD-13, AD-18) ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    """One Tile, scored. **One per Tile, never one per image or per view.**"""

    rank: int
    tile_id: UUID
    code: str
    size: str
    category: str | None
    face_number: str | None
    #: Stays server-side. It decides ranking and it belongs in every log line;
    #: it is never rendered (AD-20) and the `Tile` contract has no field for it.
    score: float


def find_candidates(
    conn: psycopg.Connection, image: Image.Image, limit: int = TOP_K
) -> list[Candidate]:
    """The top `limit` Tiles for `image`, max-pooled over every stored view.

    **This is the function Epic 3's scan endpoint calls.** It embeds through
    `shared_vision` with no wrapping and no second preprocessing step, which is
    the query half of AD-1 — the write path above embeds the same way, and
    `shared/vision/tests/test_pipeline.py` asserts the two produce bit-identical
    vectors.

    Fewer than `limit` come back when the catalogue holds fewer Tiles, and
    none at all when it holds none — an empty catalogue has no active
    generation, and answering that with an empty list rather than by opening
    one is what keeps this function a reader. Never padded, never deduplicated
    by Category (AD-18), never averaged across views (AD-13).
    """
    generation_id = active_generation(conn)
    if generation_id is None:
        # Nothing has ever been indexed. Not an error: it is what a catalogue
        # looks like before the first tile is added, and the embed below would
        # be tens of seconds of CPU spent to search nothing.
        return []

    try:
        query = _vector_literal(shared_vision.embed(shared_vision.preprocess(image))[0])
    except FileNotFoundError as missing_model:
        # The same refusal the add path raises for the same condition. Named
        # here as well so that Epic 3's scan endpoint inherits the sentence
        # that says how to fix it rather than an unexplained 500.
        raise _refusal(
            MATCHING_UNAVAILABLE, NOT_INSTALLED, status.HTTP_503_SERVICE_UNAVAILABLE
        ) from missing_model

    rows = conn.execute(_SELECT_CANDIDATES, (query, generation_id, query, limit)).fetchall()
    return [
        Candidate(
            rank=rank,
            tile_id=row["tile_id"],
            code=row["code"],
            size=row["size"],
            category=row["category"],
            face_number=row["face_number"],
            score=float(row["score"]),
        )
        for rank, row in enumerate(rows, 1)
    ]


# --- The add ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Prepared:
    """One accepted image, everything about it computed, nothing written yet.

    Held in memory so that the whole request can be refused — a duplicate Code,
    a corrupt second file — before a single row or object exists. The expensive
    part (16 forward passes) is paid before the transaction opens rather than
    inside it: a minute of held locks on `tile` buys nothing.
    """

    image_id: UUID
    source_key: str
    derivative_key: str
    source: bytes
    derivative: bytes
    sha256: str
    width: int
    height: int
    pixel_std: float
    featureless: bool
    #: 16 `(view_kind, view_index, vector literal)` triples, in view order.
    embeddings: list[tuple[str, int, str]]


def _source_key(tile_id: UUID, image_id: UUID) -> str:
    """The retained asset a re-index reads. Never served — there is no route."""
    return f"tiles/{tile_id}/{image_id}/source.jpg"


def _derivative_key(tile_id: UUID, image_id: UUID) -> str:
    """AD-17's capped view: the only bytes `apps/web` ever sees."""
    return f"tiles/{tile_id}/{image_id}/view.jpg"


def _read_upload(upload: UploadFile) -> bytes:
    """The uploaded bytes, bounded.

    Read through the spooled file rather than `await upload.read()` because
    this handler is sync — psycopg is a synchronous driver and the embedding
    below is CPU-bound for the better part of a minute, so FastAPI runs the
    whole thing in its threadpool where it cannot block the event loop.

    One byte past the ceiling is enough to refuse: nothing reads the rest.
    """
    data = upload.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise _refusal(IMAGE_TOO_LARGE, TOO_LARGE, status.HTTP_413_CONTENT_TOO_LARGE)
    return data


def _accept(upload: UploadFile) -> shared_vision.IntakeResult:
    """One upload, read and taken through AD-7's intake. Embeds nothing.

    Separate from `_prepare` because of what each half costs. This half is a
    read and a decode; the other is sixteen forward passes, tens of seconds per
    image. `add_tile` runs this over *every* file before it embeds any of them,
    so an oversized or corrupt second file is refused in milliseconds rather
    than after the first file has been embedded and thrown away.
    """
    data = _read_upload(upload)

    try:
        # AD-7's single intake, and the only place in `apps/api` that turns
        # bytes into pixels. Content-sniffed; the name and the client's
        # declared type are not consulted here or anywhere below.
        accepted = shared_vision.intake_image(data, max_pixels=shared_vision.REFERENCE_MAX_PIXELS)
    except shared_vision.ImageTooLarge as oversized:
        raise _refusal(IMAGE_TOO_LARGE, TOO_LARGE, status.HTTP_413_CONTENT_TOO_LARGE) from oversized
    except shared_vision.UnreadableImage as unreadable:
        raise _refusal(
            UNREADABLE_IMAGE, NOT_AN_IMAGE, status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from unreadable

    return accepted


def _prepare(tile_id: UUID, accepted: shared_vision.IntakeResult) -> _Prepared:
    """Derivative and 16 embeddings for one accepted image. Writes nothing.

    Every refusal in here is raised before anything has been stored, which is
    what makes "nothing stored, no partial Tile" true for a corrupt second file
    in a request whose first file was fine.
    """
    image_id = uuid4()

    try:
        # AD-13. Keyed on the digest of the bytes, so a rebuild of the same
        # asset reproduces the same 16 views and a different asset never
        # collides with it.
        views = shared_vision.generate_views(accepted.image, accepted.sha256)
        vectors = shared_vision.embed_images(views)
    except FileNotFoundError as missing_model:
        # The artifact is not installed. Named as its own refusal rather than
        # allowed to become a 500, because the message is the fix.
        raise _refusal(
            MATCHING_UNAVAILABLE, NOT_INSTALLED, status.HTTP_503_SERVICE_UNAVAILABLE
        ) from missing_model

    return _Prepared(
        image_id=image_id,
        source_key=_source_key(tile_id, image_id),
        derivative_key=_derivative_key(tile_id, image_id),
        source=accepted.data,
        derivative=shared_vision.display_derivative(accepted.image),
        sha256=accepted.sha256,
        width=accepted.width,
        height=accepted.height,
        pixel_std=accepted.pixel_std,
        featureless=accepted.featureless,
        embeddings=[
            (shared_vision.view_kind(index), index, _vector_literal(vector))
            for index, vector in enumerate(vectors)
        ],
    )


def _discard(store: ObjectStore, keys: list[str], why: str = DISCARD_ROLLED_BACK) -> None:
    """Remove objects no row points at any more. Best effort, always.

    Two call sites, and they are mirror images of each other — which is what
    `why` is for. It reaches the log line and nothing else: the two cases leave
    an identical orphan behind and an operator reading a warning has no other
    way to tell "a write failed and was undone" from "a removal committed and
    its bytes could not follow".

    * `add_tile` and `edit_tile` call it from their `except` clause, with every
      key the failed request wrote. The transaction has rolled back, so the
      rows those objects belonged to do not exist.
    * `edit_tile` calls it once more *after* its commit, with the keys of the
      images the edit removed. The rows are gone, so the objects are next.

    Best effort by construction: an object that resists deletion must not turn
    a `409` the Administrator can act on into a `500` they cannot, nor turn a
    committed edit into a failure. What is left behind is a file with no row
    pointing at it, which an operator can remove; the inverse — a row pointing
    at bytes that are not there — is what this exists to prevent.

    **`Exception`, not `OSError`, and per key rather than around the loop.**
    This runs inside the `except` of a failed add, so anything it raises
    *replaces* the failure the caller is about to be told about — a `409` the
    Administrator could act on would become a `ValueError` from a driver they
    cannot. Narrowing the clause does not make that safer, it makes it rarer
    and therefore harder to find; and a clause around the whole loop would
    abandon every key after the first bad one. `BaseException` is deliberately
    *not* caught: a cancellation or a `KeyboardInterrupt` during cleanup is not
    this function's to swallow.
    """
    for key in keys:
        try:
            store.delete(key)
        except Exception:
            logger.warning("could not remove object %s from storage (%s)", key, why, exc_info=True)


@router.post("/admin/tiles", response_model=Tile, status_code=status.HTTP_201_CREATED)
def add_tile(
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
    code: Annotated[str, Form()] = "",
    size: Annotated[str, Form()] = "",
    category: Annotated[str | None, Form()] = None,
    images: Annotated[list[UploadFile] | None, File()] = None,
) -> Tile:
    """FR-14 — add one Tile and make it findable, with no re-index step.

    **The `administrator` parameter is the authorization *and* the actor**, as
    it is on every write in `api.users`: declaring the dependency is what
    refuses a Staff caller, and reading it is what lets the audit entry say who
    changed the Catalogue.

    **The three text fields are optional at the framework level and required
    here.** A missing `code` would otherwise be answered by
    `api.main.validation_error_handler`'s one generic sentence, which names no
    field — the Administrator would be told the request was "not in the
    expected shape" and left to guess which of four parts was wrong. Declared
    with defaults and refused below, each with a code of its own.

    Sync, not `async def`: psycopg is synchronous and the embedding is CPU-bound
    for tens of seconds per image. FastAPI runs a sync endpoint in its
    threadpool; an `async def` around the same calls would block every other
    request in the process.
    """
    response.headers.update(NO_STORE)

    # The cheap refusals first, so nothing a rule can reject costs a decode,
    # let alone 16 forward passes.
    try:
        tile_code = clean_code(code)
    except ValueError as invalid:
        raise _refusal(
            INVALID_CODE, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    try:
        size_name = clean_size(size)
    except ValueError as invalid:
        raise _refusal(
            INVALID_SIZE, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    try:
        # Never a refusal for being absent: a Tile with no recoverable Category
        # resolves to the UNKNOWN sentinel (AD-18) rather than being dropped.
        category_name = clean_category(category)
    except ValueError as invalid:
        raise _refusal(
            INVALID_CATEGORY, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    uploads = [upload for upload in (images or []) if upload.filename or upload.size]
    if not uploads:
        raise _refusal(INVALID_IMAGE, NO_IMAGE, status.HTTP_422_UNPROCESSABLE_CONTENT)
    if len(uploads) > MAX_IMAGES_PER_REQUEST:
        raise _refusal(TOO_MANY_IMAGES, TOO_MANY, status.HTTP_422_UNPROCESSABLE_CONTENT)

    # Two more refusals that cost one query each, taken *before* the images are
    # decoded and embedded. Both are states the request cannot recover from, and
    # `_prepare` below is tens of seconds of CPU per image plus two object
    # writes — all of it thrown away.
    #
    # AD-14's stamp first, read-only: a deployment running ahead of its
    # re-index refuses every add, and it should refuse them in milliseconds.
    active_generation(conn)

    # Then the Code. **This is an optimisation and not the decision** — two
    # requests claiming one Code can both pass this `SELECT` and only the unique
    # index can separate them, which is why the `UniqueViolation` catch below
    # stays exactly as it was and is what `test_add_tile.py` drives the
    # concurrent case through. What this buys is the ordinary case: an
    # Administrator re-adding a tile that is already there is told so at once
    # rather than after a minute of embedding.
    if conn.execute(_SELECT_CODE, (tile_code,)).fetchone() is not None:
        raise _refusal(CODE_ALREADY_EXISTS, CODE_IN_USE, status.HTTP_409_CONFLICT)

    tile_id = uuid4()
    # Both loops, in this order. Reading and decoding every file first means a
    # request whose *second* image is oversized or corrupt is refused before
    # the first one has been embedded — sixteen forward passes that the refusal
    # would have thrown away.
    accepted = [_accept(upload) for upload in uploads]
    prepared = [_prepare(tile_id, image) for image in accepted]

    # Storage before the database, and every key recorded so a failure can undo
    # it. See the module docstring: an orphaned object is recoverable, a row
    # pointing at absent bytes is not.
    written: list[str] = []
    try:
        for item in prepared:
            store.put(item.source_key, item.source)
            written.append(item.source_key)
            store.put(item.derivative_key, item.derivative)
            written.append(item.derivative_key)

        # One unit of work for the Tile, its images, every embedding and the
        # audit entry. `api.db` hands out autocommit connections, so this is
        # what makes them atomic.
        with conn.transaction():
            generation_id = ensure_active_generation(conn)
            size_id = conn.execute(_RESOLVE_SIZE, (size_name,)).fetchone()
            category_id = conn.execute(_RESOLVE_CATEGORY, (category_name,)).fetchone()
            assert size_id is not None and category_id is not None

            try:
                tile_row = conn.execute(
                    _INSERT_TILE,
                    (tile_id, tile_code, size_id["id"], category_id["id"]),
                ).fetchone()
            except pg_errors.UniqueViolation as clash:
                # Caught rather than pre-empted by a `SELECT`: a read-then-write
                # is a race that lets two requests claim one Code, and the
                # database is the only thing that can decide between two
                # arriving together. Narrowed to the one index by name — a
                # clash this endpoint cannot explain is re-raised.
                if clash.diag.constraint_name != CODE_UNIQUE_INDEX:
                    raise
                raise _refusal(
                    CODE_ALREADY_EXISTS, CODE_IN_USE, status.HTTP_409_CONFLICT
                ) from clash
            assert tile_row is not None

            stored_images: list[ReferenceImage] = []
            for item in prepared:
                image_row = conn.execute(
                    _INSERT_REFERENCE_IMAGE,
                    (
                        item.image_id,
                        tile_id,
                        item.source_key,
                        item.derivative_key,
                        item.sha256,
                        item.width,
                        item.height,
                        len(item.source),
                        len(item.derivative),
                        item.pixel_std,
                        item.featureless,
                    ),
                ).fetchone()
                assert image_row is not None
                stored_images.append(ReferenceImage.model_validate(image_row))

                # 16 rows, one per view, never pooled (AD-13). `executemany`
                # rather than a loop of `execute`: one round trip instead of
                # sixteen, and the statement is the same parameterized one.
                with conn.cursor() as cursor:
                    cursor.executemany(
                        _INSERT_EMBEDDING,
                        [
                            (item.image_id, generation_id, vector, kind, index)
                            for kind, index, vector in item.embeddings
                        ],
                    )

            # FR-20's answer to "who changed the Catalogue, and when". The Code
            # is a snapshot in `details`, not a foreign key (AD-10): removal is
            # a hard delete and the log may neither block it nor be cascaded
            # into. `target_user_id` stays empty — this write is not about an
            # account.
            audit.record(
                conn,
                action=AuditAction.CATALOGUE_TILE_ADDED,
                actor_id=administrator.id,
                actor_email=administrator.email,
                source_ip=source_ip,
                details={
                    "code": tile_row["code"],
                    "tile_id": str(tile_id),
                    "size": size_name,
                    "category": category_name,
                    "reference_images": len(stored_images),
                },
            )
    except BaseException:
        # Every failure, not only `Exception`: a cancelled request must not
        # leave objects behind either. Re-raised immediately — this clause
        # decides nothing about what the caller is told.
        _discard(store, written)
        raise

    return Tile(
        id=tile_row["id"],
        code=tile_row["code"],
        size=size_name,
        category=category_name,
        face_number=tile_row["face_number"],
        reference_images=stored_images,
        created_at=tile_row["created_at"],
        updated_at=tile_row["updated_at"],
    )


# --- The lookup and the edit (FR-15) ------------------------------------------


#: The three fields `PATCH /admin/tiles/{tile_id}` may move, and the only ones
#: an edit's `details.changed` describes.
#:
#: Named here rather than derived from the handler's parameters, for
#: `api.users._EDITABLE_COLUMNS`'s reason: the parameters are what a caller may
#: *send*, and the day those two stop being the same set — a part that maps to
#: two columns, a column written by something other than the body — a diff built
#: off the request would silently describe the wrong thing. `face_number` is
#: absent because nothing writes it; `updated_at` is absent because it moves on
#: every edit and would be noise in every entry; the Reference Images are absent
#: because they are counted separately, and a list of image ids is not something
#: a reader of the log can do anything with.
_EDITABLE_FIELDS = ("code", "size", "category")


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, object]]:
    """`{field: {from, to}}` over the three fields an edit may move.

    Compared value by value rather than trusting the request, exactly as
    `api.users._changed_fields` does: an absent part means "leave it alone" and
    a present one may carry what is already stored, so an entry claiming a
    change that did not happen is worse than a terse one — nothing downstream
    can tell it from a real one.

    An edit that moved nothing therefore produces `{}`, which is the honest
    record of a `PATCH` that was accepted and changed no value. Both sides are
    the resolved, normalized names rather than the ids behind them: `45X90` is
    what an Administrator reading the log recognises, and a `tile_size` id is
    not.
    """
    return {
        field: {"from": before[field], "to": after[field]}
        for field in _EDITABLE_FIELDS
        if before[field] != after[field]
    }


def _tile_not_found() -> ApiError:
    """The id, or the Code, names no Tile. `404`, so the screen refetches."""
    return _refusal(TILE_NOT_FOUND, NO_SUCH_TILE, status.HTTP_404_NOT_FOUND)


def _supplied(part: list[str] | None) -> str | None:
    """One text part's value, or `None` when the request did not carry it.

    **The three editable parts are declared `list[str] | None` rather than
    `str | None`, and that is not a style choice — FastAPI cannot otherwise tell
    an absent form field from a blank one.** For a non-required `Form` field it
    substitutes the default whenever the submitted value is the empty string, so
    `code=` and a missing `code` arrive at the handler as the same `None`. On
    this endpoint those two mean opposite things: absent is "leave it alone" and
    blank is a refusal (`code`, `size`) or the `UNKNOWN` sentinel (`category`).
    Collapsing them would mean an Administrator who cleared the Size field and
    saved got the old Size silently back.

    A *sequence* field is read straight off `form.getlist(...)`, which preserves
    an empty value — so an absent part is `None`, a blank one is `[""]`, and the
    distinction survives. The last value wins where a part is repeated, which is
    what a browser does with two inputs of one name; the screen sends each part
    once, so it never arises there.
    """
    if part is None:
        return None
    return part[-1] if part else None


def _reference_images(conn: psycopg.Connection, tile_id: UUID) -> list[ReferenceImage]:
    """One Tile's Reference Images in the contract's shape.

    Read back rather than assembled from what this request happened to write:
    an edit's answer is the Tile as it now stands, which is the images that
    survived plus the images that arrived, and composing that in Python from
    two lists is a second statement of a fact the table already holds.
    """
    return [
        ReferenceImage.model_validate(row)
        for row in conn.execute(_SELECT_TILE_IMAGES, (tile_id,)).fetchall()
    ]


def _removals(
    conn: psycopg.Connection, tile_id: UUID, requested: list[str], incoming: int
) -> list[UUID]:
    """The image ids this edit removes, refusing the two ways it can be wrong.

    **An id that is not this Tile's is a `404`, and so is one that is not a
    UUID.** They are the same fact to the caller — the id names no Reference
    Image of this Tile — and separating them would tell an Administrator
    holding a borrowed id that it exists somewhere, which is exactly what
    `read_reference_image` refuses to confirm. The refusal names neither Tile.

    **A net of zero images is a `409`** (FR-7). Counted as
    `held - removed + incoming`, so removing the only image *and* uploading its
    replacement in one request is accepted — which is the whole reason the two
    halves are one endpoint rather than two.

    Called twice: once as a pre-flight, before any byte is embedded or stored,
    and once inside the transaction under the Tile's own row lock. The first is
    what makes the refusal cheap; the second is what makes it true when two
    edits of one Tile arrive together.
    """
    wanted: list[UUID] = []
    # The `set` is the membership test and the list is the answer: `requested`
    # is whatever the caller put in the form and has no ceiling, so a linear
    # scan per id would make the refusal quadratic in something an authenticated
    # caller chooses. Both structures are maintained together for that reason.
    seen: set[UUID] = set()
    for value in requested:
        try:
            image_id = UUID(value)
        except ValueError as malformed:
            raise _refusal(IMAGE_NOT_FOUND, NO_SUCH_IMAGE, status.HTTP_404_NOT_FOUND) from malformed
        # Deduplicated rather than refused: naming one image twice is a request
        # for it to be gone, which is what the caller gets. Order is preserved
        # so the `DELETE`s run in the order they were asked for.
        if image_id not in seen:
            seen.add(image_id)
            wanted.append(image_id)

    held = [row["id"] for row in conn.execute(_SELECT_TILE_IMAGES, (tile_id,)).fetchall()]
    if not seen.issubset(held):
        raise _refusal(IMAGE_NOT_FOUND, NO_SUCH_IMAGE, status.HTTP_404_NOT_FOUND)
    if len(held) - len(wanted) + incoming < 1:
        raise _refusal(LAST_REFERENCE_IMAGE, LAST_IMAGE, status.HTTP_409_CONFLICT)

    return wanted


@router.get("/admin/tiles/lookup", response_model=Tile)
def lookup_tile(
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    code: str = "",
) -> Tile:
    """One Tile by an **exact** Code. The edit screen's only door until 2.5.

    **This is not Story 2.5's catalogue search and must not become it.**
    EXPERIENCE.md reaches Edit Tile from a Catalogue row, and that list — with
    its substring matching, its filtering and its pagination — is 2.5's whole
    surface. Without *some* door this story would ship a screen nothing can
    open, so this is the smallest thing that makes it usable: an equality match
    returning one Tile or nothing. `?code=RP.CMA` answers `404` while
    `RP.CMA.0001DJ.SM.0T` exists, and that is the behaviour, not a gap in it.
    When the list arrives it opens the same screen by id, and this route can
    stay or go.

    **The Code is cleaned the same way the writes clean it**, so a Code pasted
    with a trailing space finds its Tile rather than missing by a character
    nobody can see. Case is *not* folded: `1Jk` is not `1JK` (AD-18), and
    `clean_code` is the one statement of that rule.

    The `administrator` parameter is unread: on this route the dependency is the
    whole of its job. Nothing is recorded — nothing changed, and FR-20 covers
    changes; an entry per lookup would bury the entries that matter.
    """
    response.headers.update(NO_STORE)

    try:
        wanted = clean_code(code)
    except ValueError as invalid:
        raise _refusal(
            INVALID_CODE, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    row = conn.execute(_SELECT_TILE_BY_CODE, (wanted,)).fetchone()
    if row is None:
        raise _tile_not_found()

    return Tile(
        id=row["id"],
        code=row["code"],
        size=row["size"],
        category=row["category"],
        face_number=row["face_number"],
        reference_images=_reference_images(conn, row["id"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.patch("/admin/tiles/{tile_id}", response_model=Tile)
def edit_tile(
    tile_id: UUID,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
    code: Annotated[list[str] | None, Form()] = None,
    size: Annotated[list[str] | None, Form()] = None,
    category: Annotated[list[str] | None, Form()] = None,
    remove_image_ids: Annotated[list[str] | None, Form()] = None,
    images: Annotated[list[UploadFile] | None, File()] = None,
) -> Tile:
    """FR-15 — correct a Tile, and keep the index true in the same breath.

    **Multipart, and an absent part means "unchanged".** The request carries
    files, so the body is multipart and there is no `null` on the wire. A
    present-but-blank `code` or `size` is therefore a refusal, exactly as on the
    add, and a present-but-blank `category` resolves to the `UNKNOWN` sentinel,
    also exactly as on the add (AD-18). The screen sends all three because its
    form is prefilled, so the two readings never both apply to one request.

    **Every new image byte goes through the same path the add uses** — the same
    `_accept` (AD-7's intake: content sniff, ICC to sRGB at relative colorimetric
    intent, EXIF strip, re-encode) and the same `_prepare` (AD-13's 16 views,
    AD-17's capped derivative). Not a copy of them: a second intake here is the
    AD-1 asymmetry one level up from the pixels, and it would not raise.

    **Nothing that was not uploaded in this request is re-embedded.** Changing a
    Code changes no pixels, and rebuilding untouched embeddings is a re-index by
    another name — which AD-14 says is a whole new generation cut over by a
    pointer, not something a `PATCH` does on the side.

    **The order, and why removal's objects go last.**

    ::

        cheap refusals -> active_generation (stamp) -> tile exists (404)
          -> remove ids are this tile's (404) -> net images >= 1 (409)
          -> duplicate-Code pre-flight (409, fast path only)
          -> _accept every upload -> _prepare every accepted one
          -> store.put new objects, recording each key
          -> BEGIN: lock the tile FOR UPDATE (404) ; re-check the removals ;
                    UPDATE tile (UniqueViolation -> 409) ; DELETE removed images
                    (embeddings cascade) ; INSERT new images + 16 embeddings
                    each ; audit.record  COMMIT
          -> delete the removed images' objects, best effort, logged
        except BaseException: _discard(new keys); raise

    Deleting a removed image's bytes *before* the commit would leave a live row
    pointing at nothing if anything after it failed — the one state this
    module's docstring says must never happen. After the commit the row is gone,
    so the worst case is a file an operator can delete.

    **The pre-flights are pre-flights, never the decision.** The Code check can
    be passed by two requests at once and only `tile_code_key` can separate
    them; the removal check is re-run inside the transaction under the Tile's
    own row lock, because two edits each removing one of a Tile's two images
    would otherwise both see a survivor.

    Sync, not `async def`, for `add_tile`'s reason: psycopg is synchronous and
    the embedding is CPU-bound for tens of seconds per image.
    """
    response.headers.update(NO_STORE)

    # The cheap refusals first, as on the add: nothing a rule can reject costs a
    # decode. Each field is validated *as supplied* here and resolved against
    # the stored row below, so "absent" never has to mean "blank".
    sent_code = _supplied(code)
    sent_size = _supplied(size)
    sent_category = _supplied(category)

    new_code: str | None = None
    if sent_code is not None:
        try:
            new_code = clean_code(sent_code)
        except ValueError as invalid:
            raise _refusal(
                INVALID_CODE, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
            ) from invalid

    new_size: str | None = None
    if sent_size is not None:
        try:
            new_size = clean_size(sent_size)
        except ValueError as invalid:
            raise _refusal(
                INVALID_SIZE, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
            ) from invalid

    new_category: str | None = None
    if sent_category is not None:
        try:
            # Never a refusal for being blank: a Category that cannot be
            # recovered resolves to the UNKNOWN sentinel (AD-18).
            new_category = clean_category(sent_category)
        except ValueError as invalid:
            raise _refusal(
                INVALID_CATEGORY, str(invalid), status.HTTP_422_UNPROCESSABLE_CONTENT
            ) from invalid

    # `add_tile`'s filter, unchanged: a browser sends an empty part for a file
    # input nobody touched. Unlike the add there is no floor of one — a
    # metadata-only edit uploads nothing — only the ceiling.
    uploads = [upload for upload in (images or []) if upload.filename or upload.size]
    if len(uploads) > MAX_IMAGES_PER_REQUEST:
        raise _refusal(TOO_MANY_IMAGES, TOO_MANY, status.HTTP_422_UNPROCESSABLE_CONTENT)

    # Stripped, not merely filtered on: a Code pasted with padding is trimmed by
    # `clean_code` a few lines above, and an id pasted the same way must not
    # refuse the whole edit over whitespace nobody can see. A text part that is
    # nothing but padding carries no id at all and is dropped rather than
    # answered with a `404` about the empty string.
    requested_removals = [
        stripped for stripped in (value.strip() for value in remove_image_ids or []) if stripped
    ]

    # AD-14's stamp, read-only and before anything is decoded: a deployment
    # running ahead of its re-index refuses every write, in milliseconds.
    active_generation(conn)

    if conn.execute(_SELECT_TILE, (tile_id,)).fetchone() is None:
        # Before any decode, as the matrix requires. The locking read inside the
        # transaction is what actually decides; this is what stops an unknown id
        # costing a minute of CPU.
        raise _tile_not_found()

    _removals(conn, tile_id, requested_removals, len(uploads))

    if new_code is not None and (
        conn.execute(_SELECT_CODE_ELSEWHERE, (new_code, tile_id)).fetchone() is not None
    ):
        raise _refusal(CODE_ALREADY_EXISTS, CODE_IN_USE, status.HTTP_409_CONFLICT)

    # Both loops, in this order, for `add_tile`'s reason: a request whose
    # *second* image is corrupt is refused before the first has been embedded.
    accepted = [_accept(upload) for upload in uploads]
    prepared = [_prepare(tile_id, image) for image in accepted]

    written: list[str] = []
    orphaned: list[str] = []
    try:
        for item in prepared:
            store.put(item.source_key, item.source)
            written.append(item.source_key)
            store.put(item.derivative_key, item.derivative)
            written.append(item.derivative_key)

        with conn.transaction():
            current = conn.execute(_SELECT_TILE_FOR_UPDATE, (tile_id,)).fetchone()
            if current is None:
                # Removed between the pre-flight and this lock. Distinguished by
                # a read rather than by a zero-row `UPDATE`, because a zero-row
                # `UPDATE` cannot tell "no such id" from anything else.
                raise _tile_not_found()

            # Re-checked under the lock. See `_removals`.
            removals = _removals(conn, tile_id, requested_removals, len(prepared))

            tile_code = current["code"] if new_code is None else new_code
            size_name = current["size"] if new_size is None else new_size

            size_row = conn.execute(_RESOLVE_SIZE, (size_name,)).fetchone()
            assert size_row is not None

            # **An absent part means unchanged, and that has to hold for a
            # column that is NULL.** `category_id` is nullable in the ERD, so a
            # Tile can be stored with no Category at all — and
            # `clean_category(None)` is the `UNKNOWN` sentinel, so resolving the
            # stored value unconditionally would refile such a Tile under the
            # sentinel on any edit that merely renamed it, and `changed` would
            # report a move nobody asked for. Resolved only when the caller
            # actually sent a Category; otherwise the stored value is written
            # back as it stands, sentinel or NULL alike.
            category_name: str | None
            category_id: UUID | None
            if new_category is None and current["category"] is None:
                category_name = None
                category_id = None
            else:
                category_name = current["category"] if new_category is None else new_category
                category_row = conn.execute(_RESOLVE_CATEGORY, (category_name,)).fetchone()
                assert category_row is not None
                category_id = category_row["id"]

            try:
                tile_row = conn.execute(
                    _UPDATE_TILE,
                    (tile_code, size_row["id"], category_id, tile_id),
                ).fetchone()
            except pg_errors.UniqueViolation as clash:
                # The pre-flight above is the fast path; this is the decision.
                # Narrowed to the one index by name — a clash this endpoint
                # cannot explain is re-raised and answered as a 500, which is
                # honest, rather than pointing at a Code that is fine.
                if clash.diag.constraint_name != CODE_UNIQUE_INDEX:
                    raise
                raise _refusal(
                    CODE_ALREADY_EXISTS, CODE_IN_USE, status.HTTP_409_CONFLICT
                ) from clash
            # The id was found and locked above, so the statement cannot have
            # matched nothing.
            assert tile_row is not None

            for image_id in removals:
                gone = conn.execute(_DELETE_REFERENCE_IMAGE, (image_id, tile_id)).fetchone()
                assert gone is not None, "the locked removal check found this image"
                # Recorded, not deleted: the bytes go after the commit.
                orphaned.append(gone["source_key"])
                orphaned.append(gone["derivative_key"])

            if prepared:
                # Only when there is something to embed. A rename opens no
                # generation and needs no model artifact — which is the whole
                # difference between correcting a typo and re-indexing.
                generation_id = ensure_active_generation(conn)
                for item in prepared:
                    conn.execute(
                        _INSERT_REFERENCE_IMAGE,
                        (
                            item.image_id,
                            tile_id,
                            item.source_key,
                            item.derivative_key,
                            item.sha256,
                            item.width,
                            item.height,
                            len(item.source),
                            len(item.derivative),
                            item.pixel_std,
                            item.featureless,
                        ),
                    )

                    # 16 rows, one per view, never pooled (AD-13).
                    with conn.cursor() as cursor:
                        cursor.executemany(
                            _INSERT_EMBEDDING,
                            [
                                (item.image_id, generation_id, vector, kind, index)
                                for kind, index, vector in item.embeddings
                            ],
                        )

            stored_images = _reference_images(conn, tile_id)

            # FR-20. The Code is a snapshot in `details`, never a foreign key
            # (AD-10), and it is the Code as it *now* stands — `changed` carries
            # the one it had. Compared between the locked read and the
            # `UPDATE`'s own `RETURNING`, so the entry describes what landed
            # rather than what was asked for.
            audit.record(
                conn,
                action=AuditAction.CATALOGUE_TILE_EDITED,
                actor_id=administrator.id,
                actor_email=administrator.email,
                source_ip=source_ip,
                details={
                    "tile_id": str(tile_id),
                    "code": tile_row["code"],
                    "changed": _changed_fields(
                        {
                            "code": current["code"],
                            "size": current["size"],
                            "category": current["category"],
                        },
                        {"code": tile_row["code"], "size": size_name, "category": category_name},
                    ),
                    "images_added": len(prepared),
                    "images_removed": len(removals),
                },
            )
    except BaseException:
        # Every failure, not only `Exception`, and only the objects *this*
        # request wrote. The removed images' objects are deliberately not in
        # this list: their rows are still there.
        _discard(store, written)
        raise

    # Committed. The rows are gone, so the bytes can follow — best effort and
    # logged, because a file nothing points at is an operator's tidy-up and a
    # failed `DELETE` here must not turn a successful edit into a `500`.
    _discard(store, orphaned, DISCARD_REMOVED)

    return Tile(
        id=tile_row["id"],
        code=tile_row["code"],
        size=size_name,
        category=category_name,
        face_number=tile_row["face_number"],
        reference_images=stored_images,
        created_at=tile_row["created_at"],
        updated_at=tile_row["updated_at"],
    )


# --- The image read (AD-9, AD-17) ---------------------------------------------


@router.get("/admin/tiles/{tile_id}/images/{image_id}")
def read_reference_image(
    tile_id: UUID,
    image_id: UUID,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
) -> Response:
    """Serve one Reference Image's capped derivative, and only ever that.

    **The source asset has no route**, here or anywhere: AD-17 says the
    original is never served, and the way to make that true is to give it
    nowhere to be asked for. This handler reads `derivative_key` and there is
    no parameter that can make it read the other column.

    **Proxied, never redirected** (AD-9). The bytes travel through this
    endpoint, which re-checks the Administrator role on every request through
    the dependency above; `apps/web` never holds a storage URL, presigned or
    otherwise.

    `no-store`, like every other authenticated response in the product. A
    reference image is catalogue data, and catalogue exfiltration through a
    compromised account is this product's primary commercial threat — a copy
    left in a shared proxy cache is a copy outside the audit trail.

    **`X-Content-Type-Options: nosniff`, which no other route in the product
    needs.** Every other response here is JSON this service composed; this one
    is bytes that began life as an upload. They have been content-sniffed,
    colour-managed and re-encoded by `shared_vision` on the way in, so what is
    stored really is a JPEG — but the header costs nothing and closes the gap
    between "we re-encode" and "the browser believes the type we declare". A
    browser that sniffed its way to `text/html` on a response served from this
    origin would be executing script from the catalogue.

    The `administrator` parameter is unread: on this route the dependency is
    the whole of its job. Nothing here is recorded, because nothing is changed
    — `AuditAction` has no member for a read (FR-20 covers changes), and a log
    entry per rendered thumbnail would bury the entries that matter.
    """
    row = conn.execute(_SELECT_DERIVATIVE_KEY, (image_id, tile_id)).fetchone()
    if row is None:
        # One answer for "no such tile", "no such image" and "that image
        # belongs to another tile". They are the same fact to a caller holding
        # a pair that names nothing, and telling them apart would confirm which
        # ids exist.
        raise _refusal(IMAGE_NOT_FOUND, NO_SUCH_IMAGE, status.HTTP_404_NOT_FOUND)

    try:
        data = store.get(row["derivative_key"])
    except ObjectNotFound as missing:
        # The row exists and the object does not. Logged, because it means the
        # store and the database have diverged, and answered as a 404 rather
        # than a 500 — there is genuinely nothing to serve.
        logger.error("reference image %s has no stored derivative", image_id)
        raise _refusal(IMAGE_NOT_FOUND, NO_SUCH_IMAGE, status.HTTP_404_NOT_FOUND) from missing

    return Response(content=data, media_type="image/jpeg", headers={**NO_STORE, **NO_SNIFF})
