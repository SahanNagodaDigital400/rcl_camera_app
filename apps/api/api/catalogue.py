"""`/admin/tiles` — the Catalogue's write path, its read door, and the query that proves it worked.

Eight routes and three functions that are not routes:

* `POST /admin/tiles` (FR-14) takes a Code, a Size, an optional Category and
  one to eight reference images, and creates a Tile that a Scan can return in
  the same session.
* `POST /admin/tiles/bulk` (FR-17) takes a CSV manifest and the image set it
  names, and does the same thing once per row — through the add's own intake
  and embedding helpers, never a second path — streaming one NDJSON line per
  row as that row completes.
* `PATCH /admin/tiles/{tile_id}` (FR-15) corrects one: its Code, its Size, its
  Category, and the Reference Images it carries — adding new ones through the
  *same* intake, embedding and derivative path the add uses, and removing old
  ones for real.
* `DELETE /admin/tiles/{tile_id}` (FR-16) withdraws one outright — the Tile,
  its Reference Images and every embedding those images produced leave the
  searchable graph in one statement, by the migration's own cascades.
* `GET /admin/tiles?q=` (FR-18) is the Catalogue itself: every Tile whose Code
  contains `q`, case-insensitively and anywhere in the string, ordered by Code,
  with its Size, its Category and its Reference Images. A blank `q` browses the
  whole Catalogue. Substrings of the **Code** and nothing else — Size and
  Category are displayed and never filtered on.
* `GET /admin/tiles/lookup?code=` finds one Tile by an **exact** Code. Not a
  search: no substring, no listing, no pagination. The list above is what the
  Catalogue screen opens Edit Tile from; this is what Edit Tile uses when
  nobody handed it a Tile.
* `GET /admin/tiles/{tile_id}/images/{image_id}` serves AD-17's capped
  derivative to an Administrator, and only that — the retained source asset
  has no route at all.
* `GET /tiles/{tile_id}/images/{image_id}` (Story 3.4) serves the same capped
  derivative to any claimed session — Results' Candidate cards, not an admin
  surface — through the one lookup helper the route above also uses.
* `_serve_reference_image` is that one lookup helper: the shared lookup-and-
  proxy logic both image routes above wrap, so a tile id and an image id that
  name no row are answered the same way from either door.
* `find_candidates` is the max-over-views search. It lives here, with the
  write path it validates, because "the Tile is immediately findable" is this
  story's acceptance criterion. Story 3.4's `POST /scans` wraps this function
  rather than writing a second query — the asymmetry AD-1 is about, one level
  up from the pixels.
* `primary_reference_image_ids` (Story 3.4) answers each candidate tile's
  earliest Reference Image id in one batched read, for the picture beside
  every Candidate card.

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
`DELETE FROM reference_image` and `remove_tile` issues `DELETE FROM tile`, in
both cases so that the rows below cascade out of the index: there is no
soft-delete flag and no query-time predicate, because a predicate is a thing
exactly one call site has to remember and Epic 3's scan is the call site that
must not forget. The one asymmetry with the add's ordering is deliberate and is
argued for at `edit_tile`: objects belonging to *removed* images — and to a
removed Tile — are deleted **after** the commit, because a live row pointing at
absent bytes is the unrecoverable state and an orphaned object is not.

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

**The bulk path is the add, N times, and not a second implementation of it**
(FR-17, epic context: "no shortcut for bulk"). Every image it takes reaches
storage through `_accept_bytes` and `_prepare` — the same content sniff, the
same colour management, the same sixteen views, the same capped derivative —
and `tests/test_source_guards.py` fails the build if the bulk handler ever
reaches the pixel pipeline on its own. What it adds is batching, a per-row
report and the classification of the defects the real catalogue carries: a
Category that cannot be recovered and a Code with no trailing number are
**flags on a Tile that was created**, while a zero-byte or unreadable file is
a **failure of that row alone** (AD-18, AD-7). Two rows sharing a Size and a
Category are two distinct Tiles, merged nowhere and reported as a conflict
nowhere.

**The bulk response is a stream, and that decides where its refusals live.**
The status is committed at the first byte, so everything refusable —
authorization, the manifest, the row cap, the missing model artifact and
AD-14's stamp — is checked while a real envelope under a 4xx or 5xx is still
possible. After that the status is `200` and every outcome is a row.

**The read is the write's own contract, unchanged** (2.5). The search answers
the same closed `Tile` model the four writes answer, in a bare array with no
envelope, no cursor and no cap — so a row of the Catalogue and a Tile just
saved are the same shape, and the screen hands one straight to Edit Tile. It
matches substrings of the **Code** only: Size and Category are groupings
(AD-18), they are displayed on every row, and nothing filters, facets or groups
by them. And it records nothing, for `lookup_tile`'s reason — a read changes
nothing, and FR-20 covers changes.

Not here, deliberately: a `GET /admin/tiles/{tile_id}` detail route (the list
carries the whole Tile), a Size or Category filter or picker — Epic 3's
proposed scan-side Size pre-filter is `[PROPOSED, PRD OQ-15]` and not adopted —
a staff-facing lookup (`SPEC.md:94` leaves that open), Epic 3's scan endpoint,
and any crop step — AD-11 resolved that one explicitly
as *no* for admin uploads. Nor any way back from a removal: no restore, no
undo, no trash state and no grace period. The confirmation on the screen is the
safeguard, and a Tile that should come back is added again. Nor a job table, a
queue, a worker, a polling endpoint or a resume verb for the bulk path: one
request, one stream, no state to garbage-collect.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a handler's
# annotations at runtime to build its dependency graph.
import psycopg
import shared_vision
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from PIL import Image
from psycopg import errors as pg_errors
from psycopg_pool import ConnectionPool
from shared_schema.errors import ApiError
from shared_schema.tile import (
    MAX_BULK_ROWS,
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_REQUEST,
    UNKNOWN_CATEGORY,
    ReferenceImage,
    Tile,
    clean_category,
    clean_code,
    clean_query,
    clean_size,
    face_number,
)
from shared_schema.user import User

# `api.audit` owns the only INSERT against the audit table in the repository
# and `tests/test_source_guards.py` forbids a second file from so much as
# naming it (AD-4). This module records through it and names nothing.
from api import audit
from api.audit import AuditAction
from api.db import get_connection, get_pool
from api.dependencies import NO_STORE, require_administrator, require_claimed_user
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
# Story 2.5's one. Separate from `INVALID_CODE` because a query is not a Code
# (`shared_schema.tile.clean_query`): a blank one is legal and browses the whole
# Catalogue, so the two refusals do not describe the same input and a screen
# marking its search box from `invalid_code` would mark it for a Code somebody
# typed into a different form.
INVALID_QUERY = "invalid_query"
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

# Story 2.4's five. The first two are *envelope* codes in the ordinary sense —
# they refuse the whole request before a byte of the stream is written. The
# last three can only ever appear inside a report line, under a `200`, because
# they describe one row of a batch the rest of which is fine; they are named
# here anyway and exported to `apps/web` on the same terms, since a code the
# screen has to recognise is a code that belongs in the parity check.
INVALID_MANIFEST = "invalid_manifest"
TOO_MANY_ROWS = "too_many_rows"
IMAGE_NOT_PAIRED = "image_not_paired"
IMAGE_UNMATCHED = "image_unmatched"
ROW_FAILED = "row_failed"

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

#: What a query the search will not run is told, after the rule it broke.
#:
#: `_invalid_manifest`'s shape: `clean_query` names the defect — longer than any
#: Code can be, or carrying a character Postgres text cannot hold — and this
#: names the way through, in that order. The fix is worth stating because the
#: obvious reading of "too long" is that the search box is broken, when in fact
#: a **fragment** is what this route wants.
#:
#: It names clearing the box deliberately: a blank `q` is not a refusal here, it
#: browses the whole Catalogue (EXPERIENCE.md:35), and an Administrator who has
#: just been refused is exactly the person who needs to know that.
BAD_QUERY = "Search for part of a code, or clear the box to browse the whole catalogue."

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

# --- The bulk manifest (FR-17) ------------------------------------------------

#: The three columns a manifest row must carry, and the one it may.
#:
#: **A CSV, and deliberately not an `.xlsx`.** Every spreadsheet tool exports
#: CSV, `csv` is in the standard library, and reading workbook bytes would mean
#: a new runtime dependency (`openpyxl`) that AGENTS.md asks to be flagged
#: before it is added. If `.xlsx` is ever genuinely required it is an additive
#: change behind this same route and this same report.
#:
#: `category` is optional because a Category that cannot be recovered is not an
#: error (AD-18): the row is created against the `UNKNOWN` sentinel and flagged
#: for follow-up. Every other column in the sheet is ignored rather than
#: refused — a real export carries notes, counts and a column somebody added
#: last week, and refusing the file over one of them would refuse the whole
#: range.
MANIFEST_COLUMNS = ("file", "code", "size")
MANIFEST_OPTIONAL_COLUMN = "category"

#: The manifest is missing, empty, unreadable or short of a column.
#:
#: One sentence for all four, because the Administrator's next action is the
#: same in every case and the specific defect is named in the sentence the
#: reader below composes from this plus what it found. It **names the fix for
#: the wrong file type** rather than describing the problem: somebody who
#: attached a workbook needs to know to export it, not that the bytes did not
#: parse.
NO_MANIFEST = (
    "Attach the spreadsheet of codes as a CSV file with "
    f"{', '.join(MANIFEST_COLUMNS)} columns. Export the sheet as CSV and upload that."
)

#: Above the cap — on the manifest's rows or on the uploaded images, since one
#: ceiling bounds both. The number is in the sentence for `TOO_MANY`'s reason:
#: an Administrator holding a longer sheet needs to know where to split it.
TOO_MANY_ROWS_MESSAGE = (
    f"A bulk upload takes at most {MAX_BULK_ROWS} rows and {MAX_BULK_ROWS} images at a time. "
    "Split the sheet and upload it in parts."
)

#: No upload matches what the row names, or two of them do. Worded about the
#: pairing rather than about the file, because both halves are the
#: Administrator's to fix and neither is a defect in the image.
NOT_PAIRED = "No image in this upload is named {file}."
AMBIGUOUS_PAIR = "Two images in this upload are named {file}. Give each tile its own file name."

#: The row's own `file` cell is blank, so there is no name to look for. The
#: same code as the two above — the pairing is what failed either way — with
#: its own sentence, because "No image in this upload is named ." is not a
#: sentence anybody can act on.
NO_FILE_NAMED = "This row names no image file."

#: An upload no row named. Reported rather than silently ignored: an image that
#: travelled and was not indexed is a tile the Administrator believes is in the
#: catalogue.
NOT_NAMED = "No row of the sheet names this image, so it was not added."

#: A multipart part that carried bytes and declared no file name at all. The
#: same code as the sentence above, because it is the same fact — an image that
#: travelled and was not indexed — with a different reason nothing could name
#: it. A browser's file input always sends a name, so this is a hand-built
#: request rather than anything an Administrator can have done by accident, and
#: the sentence says what to change rather than apologising for it.
UNNAMED_UPLOAD = "One uploaded file carries no file name, so no row can name it."

#: The batch stopped outside any one row. By the time this can happen the
#: response has already started, so there is no status left to carry it and
#: this line is the only honest way to say it: the rows above are real, the
#: rows below never ran. The cause is logged and deliberately not repeated
#: here, for `ROW_FAILED_MESSAGE`'s reason.
BATCH_STOPPED_MESSAGE = (
    "The upload stopped before every row was processed. "
    "The rows above were finished; send the rest again."
)

#: A row that failed in a way this handler cannot explain. **A fixed sentence**
#: — the exception's text can carry a file path, a query fragment or a
#: credential, and this response goes to the browser. The traceback is logged
#: instead, which is where an operator can act on it.
ROW_FAILED_MESSAGE = "This row could not be added. The failure has been logged."

#: The three outcomes a row can have, and the only three (DESIGN.md:144-149
#: paints exactly these). A `flagged` row **was created** and carries a
#: `tile_id`: the flag is follow-up, not failure.
ROW_CREATED = "created"
ROW_FLAGGED = "flagged"
ROW_FAILED_STATUS = "failed"

#: The follow-up markers, in the order a row carries them. Stable, so a screen
#: renders two flags the same way twice and a test can compare a list rather
#: than a set. None of the three is an error: each names a Tile that is in the
#: catalogue and searchable, with something about it worth a second look.
FLAG_UNKNOWN_CATEGORY = "unknown_category"
FLAG_UNKNOWN_FACE_NUMBER = "unknown_face_number"
FLAG_LOW_QUALITY_IMAGE = "low_quality_image"

#: The media type of the report. One JSON object per line, flushed as each row
#: finishes — which is what EXPERIENCE.md:94 asks for ("per-row status updates
#: as they complete, not a single spinner until the whole batch finishes") and
#: what a single JSON array could not give, since an array is only parseable
#: once it is closed.
NDJSON = "application/x-ndjson"


#: How many Candidates a search returns. Three, always (FR-7, AGENTS.md): size
#: and finish are not recoverable from a photo, so a single answer is
#: confidently wrong. Deliberately separate from whatever a screen chooses to
#: display (AD-20).
TOP_K = 3

#: AD-16's serialization: one forward pass at a time, within this server
#: process. A `threading.Lock` binds one process's threads and nothing wider —
#: a multi-worker deployment runs one of these per worker, each serializing
#: its own ONNX Runtime session. ONNX Runtime's CPU session is shared within a
#: process, and two scans embedding concurrently on it would contend for the
#: same cores rather than run in parallel for free — this turns that
#: contention into a queue instead of a slowdown neither caller can see.
#: Scoped to `shared_vision.embed` alone, inside `find_candidates`, and
#: never to `preprocess`, which touches no model and costs nothing to run
#: unserialized. Not extended to index-time embedding (`add_tile`/bulk
#: upload): AD-16 is about scan-time concurrency, and an Administrator's add
#: is already one request at a time by the nature of the screen that sends it.
_inference_lock = threading.Lock()

#: Why `_discard` was called, for its log line and for nothing else. The two
#: cases leave an identical orphaned object behind, and an operator reading the
#: warning cannot otherwise tell a write that was undone from a removal whose
#: bytes could not follow it.
DISCARD_ROLLED_BACK = "the write was rolled back"

#: **Worded about the rows rather than about a Reference Image**, because two
#: call sites now pass it: `edit_tile` removing one image from a Tile, and
#: `remove_tile` withdrawing the whole Tile. It read "the reference image was
#: removed" while only the first existed, and left as it was it would have told
#: an operator cleaning up after a Tile removal that an image had gone — which
#: is a different, and smaller, event than the one that happened. This sentence
#: is true of the orphan in front of them either way: the rows that pointed at
#: these bytes are gone and no further request will name them.
DISCARD_REMOVED = "the rows pointing at it were removed"

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
#:
#: `face_number` is written by the bulk path, which recovers it from the Code
#: (`shared_schema.tile.face_number`), and passed as `None` by `add_tile`,
#: whose form has no field for it — a display hint the Administrator would have
#: to transcribe by hand is a hint nobody would fill in correctly. **One
#: statement for both**, rather than a second `INSERT` differing in one column:
#: two statements writing one table is how the two come to disagree about a
#: column a later migration adds.
_INSERT_TILE = """
INSERT INTO tile (id, code, size_id, category_id, face_number)
VALUES (%s, %s, %s, %s, %s)
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

#: FR-18's search: **substrings of the Code, case-insensitively, and nothing
#: else.** The sibling of the equality match above, join shape for join shape,
#: so the two cannot come to disagree about what a row of the Catalogue is.
#:
#: **The pattern is the parameter, never the statement.** The text below is a
#: constant carrying one `%s`; the `%`-wrapping and the escaping of `\`, `%` and
#: `_` happen on the Python value in `_pattern`. That is what makes `?q=%` mean
#: the *character* rather than "everything", and it is what keeps
#: `tests/test_source_guards.py`'s interpolation guard satisfied — psycopg's
#: `%s` is not string formatting and never becomes part of the statement.
#:
#: **A sequential scan, deliberately.** The only index on `tile.code` is the
#: unique btree from the migration, and an unanchored pattern cannot use it in
#: any collation. The alternative is a trigram index, which means
#: `CREATE EXTENSION pg_trgm` in a new migration — a new database dependency
#: for a table holding 381 rows today and a few hundred at the scale the whole
#: index is sized for. CLAUDE.md says measure before reaching for a bigger
#: mechanism; this is the measurement not yet being needed.
#:
#: **No `WHERE` on Size or Category, and no `LIMIT`.** Size and Category are
#: *displayed* (AD-18): they are groupings, never the identity, and a
#: `size + category` filter is the one query shape CLAUDE.md forbids outright
#: because it hides the very row somebody is looking for. A `LIMIT` would
#: answer "which tiles match" with "some of them", which is `api.users`'
#: argument for `_SELECT_USERS` on a table two orders of magnitude smaller
#: again; a caller-settable one is the DoS knob `api.audit` refuses.
#:
#: **`ORDER BY t.code`**, because the Code is what a reader is scanning for and
#: it is the table's only unique non-opaque column — so the order is total and a
#: test can assert it. A blank query orders the whole Catalogue the same way.
_SEARCH_TILES = """
SELECT t.id, t.code, t.face_number, t.created_at, t.updated_at,
       s.name AS size, c.name AS category
  FROM tile t
  JOIN tile_size s ON s.id = t.size_id
  LEFT JOIN tile_category c ON c.id = t.category_id
 WHERE t.code ILIKE %s
 ORDER BY t.code
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

#: **Many** Tiles' Reference Images, in one statement.
#:
#: The sibling of the single-Tile read above, and it exists because the two
#: obvious alternatives are both wrong at list scale. Calling
#: `_reference_images` once per row is a few hundred round trips on one pooled
#: connection for a screen that paints one table. Joining the images onto
#: `_SEARCH_TILES` returns one row per *image* with every Tile column repeated,
#: which then has to be un-repeated in Python — the same grouping this does,
#: over more bytes and with the Tile's identity smeared across rows.
#:
#: `tile_id` is selected here and nowhere else, because it is what the grouping
#: is keyed on. `ReferenceImage` is `extra="forbid"`, so it comes off the row
#: before `model_validate` sees it (`_search_images`).
#:
#: `ORDER BY tile_id, created_at, id` — the same `created_at, id` order the
#: single-Tile read states, so one Tile's images appear in the same order
#: whether they were reached from the Catalogue or from the lookup, with
#: `tile_id` leading so the grouping walk is over contiguous rows.
_SEARCH_TILE_IMAGES = """
SELECT tile_id, id, width, height, featureless, created_at
  FROM reference_image
 WHERE tile_id = ANY(%s)
 ORDER BY tile_id, created_at, id
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
       face_number = %s,
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

#: Every storage key one Tile's Reference Images point at.
#:
#: Read **before** the Tile is deleted, because afterwards there is no row to
#: read them from and these keys are the only way back to the bytes. Ordered so
#: that a log line naming a key that could not be removed is reproducible
#: between two runs of the same removal.
#:
#: The `ReferenceImage` contract deliberately carries neither column (AD-9), so
#: this is a statement of its own rather than a widening of
#: `_SELECT_TILE_IMAGES`: one query answers the screen and one answers the
#: store, and the day a key becomes servable it has to be an edit here.
_SELECT_TILE_IMAGE_KEYS = """
SELECT source_key, derivative_key
  FROM reference_image
 WHERE tile_id = %s
 ORDER BY created_at, id
"""

#: FR-16's whole mechanism. **One statement, and the schema carries the rest.**
#:
#: `reference_image` cascades from `tile` and `reference_embedding` cascades
#: from `reference_image`, both by the migration's own `ON DELETE CASCADE` and
#: both with AD-5 named in the comment there. Deleting the children by hand
#: would be a second statement of a rule the schema already makes, and the two
#: would drift the first time a table is added below `reference_image`.
#:
#: `tile_size` and `tile_category` are referenced *by* `tile` and never the
#: other way, so a removal cannot reach them: they are shared lookups, not the
#: Tile's property, and the next Tile filed under `45X90` finds it already
#: there.
#:
#: No `RETURNING`: the row was read and locked a moment earlier, so there is
#: nothing this statement could report that the caller does not already hold —
#: and the `404` is decided by that read, never by a zero-row `DELETE`.
_DELETE_TILE = """
DELETE FROM tile WHERE id = %s
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

#: `_SELECT_CANDIDATES` with one predicate added: only Tiles of a declared
#: Size compete.
#:
#: **A hard filter, not a re-rank**, the POC's own reasoning
#: (`poc/tilematch/search.py`): a 60X30 tile is never the answer to a scan the
#: staff member has declared to be 45X90, and leaving those references in the
#: running only gives them a chance to outrank the truth. Applied in the
#: `WHERE`, before the `GROUP BY`, so a filtered-out Tile never reaches the
#: ranking at all rather than being dropped from its tail.
#:
#: **A separate statement rather than a null-guard bolted onto the one above.**
#: `_SELECT_LATEST_SCANS`/`_SELECT_SCANS_BEFORE`'s own split: two questions
#: that read differently are two statements, and `(%s IS NULL OR s.name = %s)`
#: would make the unfiltered scan — by far the common one — carry a predicate
#: it never uses.
_SELECT_CANDIDATES_OF_SIZE = """
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
   AND s.name = %s
 GROUP BY t.id, t.code, s.name, c.name, t.face_number
 ORDER BY min(e.embedding <#> %s::vector), t.code
 LIMIT %s
"""

#: The Sizes a scan may declare: those with at least one Tile embedded into the
#: active generation, commonest first.
#:
#: **Read from the index rather than from `tile_size`.** A Size row can exist
#: with no indexed Tile behind it — a removal takes vectors out of the graph
#: (AD-5) without retiring the row — and offering it would be offering a
#: filter that can only ever return nothing. Ordered by tile count so the
#: picker opens on the sizes staff actually meet, `Matcher.sizes`'s own order.
_SELECT_INDEXED_SIZES = """
SELECT s.name AS size, count(DISTINCT t.id) AS tiles
  FROM reference_embedding e
  JOIN reference_image ri ON ri.id = e.reference_image_id
  JOIN tile t ON t.id = ri.tile_id
  JOIN tile_size s ON s.id = t.size_id
 WHERE e.generation_id = %s
 GROUP BY s.name
 ORDER BY count(DISTINCT t.id) DESC, s.name
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


def indexed_sizes(conn: psycopg.Connection) -> list[str]:
    """Every Size with an indexed Tile behind it, commonest first.

    Empty for a catalogue that has never been indexed — the same "no active
    generation" shape `find_candidates` answers `[]` for, and for the same
    reason: there is nothing to filter, so there is nothing to offer.

    Names only. The tile counts the statement orders by are not published:
    the picker needs to know *which* sizes can be declared, and a count beside
    each one is a catalogue statistic on a screen whose job is to take one
    photo.
    """
    generation_id = active_generation(conn)
    if generation_id is None:
        return []
    return [row["size"] for row in conn.execute(_SELECT_INDEXED_SIZES, (generation_id,)).fetchall()]


def find_candidates(
    conn: psycopg.Connection, image: Image.Image, limit: int = TOP_K, size: str | None = None
) -> list[Candidate]:
    """The top `limit` Tiles for `image`, max-pooled over every stored view.

    **`size` restricts the search to Tiles of that Size — a hard filter, never
    a re-rank.** It is the one attribute a photo cannot carry and the person
    holding the tile always knows, which is what makes it the cheapest
    accuracy lever available: the POC measures it at +3.2 points of top-3
    overall and +8.0 on 45X90 (`poc/README.md`). `None` — the default, and
    what the Scan screen sends unless a staff member declares a size — leaves
    every Tile in contention.

    The caller is responsible for having checked the Size against
    `indexed_sizes`: an unrecognised one is not an error here, it simply
    matches no Tile and returns `[]`, which is the truthful answer to "which
    tiles of that size look like this".

    **This is the function Epic 3's scan endpoint calls.** It embeds through
    `shared_vision` with no wrapping and no second preprocessing step, which is
    the query half of AD-1 — the write path above embeds the same way, and
    `shared/vision/tests/test_pipeline.py` asserts the two produce bit-identical
    vectors.

    **The embedding forward pass is serialized within this server process,
    AD-16.** `preprocess` runs unlocked — it touches no model and costs
    nothing to run concurrently — and only the `shared_vision.embed` call is
    held under `_inference_lock`, so two scans that reach *this process's*
    model together queue for the one forward pass rather than contending for
    it. `_inference_lock` is a `threading.Lock`, which binds only the threads
    of the process that holds it; a multi-worker deployment serializes within
    each worker, not across them.

    Fewer than `limit` come back when the catalogue holds fewer Tiles, and none
    at all when it holds none. There are two shapes of "none" and both answer
    the empty list, by different routes: a catalogue that has *never* been
    indexed has no active generation and returns below without embedding, while
    one emptied by removals keeps its generation — a removal takes vectors out
    of the graph (AD-5), it does not retire the generation they were cut into —
    so it embeds and then finds nothing. Answering either with an empty list
    rather than by opening a generation is what keeps this function a reader.
    Never padded, never deduplicated by Category (AD-18), never averaged across
    views (AD-13).
    """
    generation_id = active_generation(conn)
    if generation_id is None:
        # Nothing has ever been indexed. Not an error: it is what a catalogue
        # looks like before the first tile is added, and the embed below would
        # be tens of seconds of CPU spent to search nothing.
        return []

    preprocessed = shared_vision.preprocess(image)
    try:
        with _inference_lock:
            embedding = shared_vision.embed(preprocessed)[0]
    except FileNotFoundError as missing_model:
        # The same refusal the add path raises for the same condition. Named
        # here as well so that Epic 3's scan endpoint inherits the sentence
        # that says how to fix it rather than an unexplained 500.
        raise _refusal(
            MATCHING_UNAVAILABLE, NOT_INSTALLED, status.HTTP_503_SERVICE_UNAVAILABLE
        ) from missing_model
    query = _vector_literal(embedding)

    rows = (
        conn.execute(_SELECT_CANDIDATES, (query, generation_id, query, limit)).fetchall()
        if size is None
        else conn.execute(
            _SELECT_CANDIDATES_OF_SIZE, (query, generation_id, size, query, limit)
        ).fetchall()
    )
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


#: The Scan surface's own picture for a Tile — the earliest Reference Image,
#: `_SELECT_TILE_IMAGES`'s `created_at, id` order, so the image a Candidate
#: card shows is the same one `CatalogueScreen.thumbnail` shows first. A batch
#: read over the (≤3) tile ids `find_candidates` returns, `_SEARCH_TILE_IMAGES`'s
#: own reasoning for one round trip over several: `DISTINCT ON` picks the
#: first row per `tile_id` under the `ORDER BY` that follows it, which is
#: Postgres's own way to answer "the first of each group" in one scan rather
#: than N.
_SELECT_PRIMARY_IMAGES = """
SELECT DISTINCT ON (tile_id) tile_id, id AS image_id
  FROM reference_image
 WHERE tile_id = ANY(%s)
 ORDER BY tile_id, created_at, id
"""


def primary_reference_image_ids(conn: psycopg.Connection, tile_ids: list[UUID]) -> dict[UUID, UUID]:
    """Each `tile_id`'s earliest Reference Image id, for `submit_scan`'s Candidate cards.

    **A second query rather than a join onto `_SELECT_CANDIDATES`.** That
    statement is AD-13's tested max-pool search, carrying its own review
    history; folding "which image represents this tile" into it would couple
    two independent concerns — ranking and display — inside one query. This is
    one extra indexed round trip, batched over at most three ids, well inside
    the scan's budget.

    `{}` on an empty list, without querying — `find_candidates` answers `[]`
    for an empty or never-indexed catalogue, and `ANY('{}')` is a query worth
    skipping rather than sending.
    """
    if not tile_ids:
        return {}
    rows = conn.execute(_SELECT_PRIMARY_IMAGES, (tile_ids,)).fetchall()
    return {row["tile_id"]: row["image_id"] for row in rows}


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

    The read and the intake are two functions rather than one so that the bulk
    path can call the second half over bytes it already holds — see
    `_accept_bytes`.
    """
    return _accept_bytes(_read_upload(upload))


def _accept_bytes(data: bytes) -> shared_vision.IntakeResult:
    """AD-7's intake over bytes that are already in hand.

    **This is what makes "the bulk path uses the same intake" a fact rather
    than a claim.** `add_tile` reaches it through `_accept` above, having read
    an `UploadFile`; the bulk handler reaches it directly, having read its own
    spooled copy — and there is exactly one content sniff, one colour
    management step, one EXIF strip and one re-encode between them. A second
    intake written for the batch path is the asymmetry AD-1 and AD-7 exist to
    prevent, and nothing about it would raise.

    The refusals are raised as `ApiError` rather than returned, so that
    `add_tile` answers a `413` or a `422` unchanged. The bulk handler catches
    them and turns each into a failed row, which is the only difference between
    the two callers.
    """
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

    Three call sites in two shapes, which is what `why` is for. It reaches the
    log line and nothing else: both shapes leave an identical orphan behind and
    an operator reading a warning has no other way to tell "a write failed and
    was undone" from "the rows committed their disappearance and the bytes
    could not follow".

    * `add_tile` and `edit_tile` call it from their `except` clause, with every
      key the failed request wrote. The transaction has rolled back, so the
      rows those objects belonged to do not exist.
    * `edit_tile` calls it once more *after* its commit, with the keys of the
      images the edit removed. The rows are gone, so the objects are next.
    * `remove_tile` calls it after its own commit, with every key the removed
      Tile's images held. Same reasoning one level up: the rows are gone.

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
                    # `None` for the trailing number. This form has no field
                    # for it and inventing one would ask an Administrator to
                    # transcribe a display hint by hand; the bulk path
                    # recovers it from the Code, which is the only place the
                    # rule belongs.
                    (tile_id, tile_code, size_id["id"], category_id["id"], None),
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


# --- The bulk upload (FR-17) --------------------------------------------------
# The add, once per manifest row, reported row by row. Everything expensive
# here is `add_tile`'s: `_accept_bytes` and `_prepare` are the intake and the
# embedding, unchanged and uncopied, and `tests/test_source_guards.py` fails
# the build if anything below reaches the pixel pipeline on its own.


#: The ceiling on the manifest itself — a megabyte. Not `MAX_IMAGE_BYTES`: a
#: hundred rows of `file,code,size,category` is a few kilobytes, and a bound
#: sized for a 128 MB press file would let an unbounded read masquerade as a
#: bounded one. One byte past this is enough to refuse; nothing reads the rest.
MAX_MANIFEST_BYTES = 1048576

#: How much of one image is read at a time while it is copied to the spool.
#: The whole point of copying in chunks is that memory holds one buffer rather
#: than the whole batch — a hundred reference images at 96 MB each is not a
#: thing a process can hold.
SPOOL_CHUNK_BYTES = 1048576


@dataclass(frozen=True, slots=True)
class _ManifestRow:
    """One data row of the manifest, as text. Nothing here is validated yet.

    `category` is `None` when the column was absent *or* the cell was blank,
    which are the same thing to AD-18: both mean "no Category was recovered",
    and both produce a Tile under the `UNKNOWN` sentinel with a flag on it.
    """

    number: int
    file: str
    code: str
    size: str
    category: str | None


@dataclass(frozen=True, slots=True)
class _Spooled:
    """One uploaded image, copied to a handler-owned file on disk.

    `oversized` is decided during the *copy* rather than after it: the copy
    stops one byte past `MAX_IMAGE_BYTES` and writes no more, so an oversized
    part costs one buffer of disk rather than its own size on disk. It does
    **not** mean the bytes never travelled — Starlette has parsed the whole
    multipart body before this handler is entered, so the transfer has already
    happened and the part is already in Starlette's own spool. What this bound
    buys is the second copy, the read of it and everything downstream of that.
    The count bound in `bulk_upload` is what limits the transfer itself.

    **`path` is never built from the uploaded name.** The name is
    caller-controlled and is kept as data alone; the file on disk is named
    after its position in the request, so nothing a manifest or a multipart
    part can say reaches the filesystem.

    `name` is the base name exactly as it was declared, kept beside the folded
    key the pairing matches on so that a report line quotes what the
    Administrator actually sent rather than a lowercased version of it.
    """

    path: Path
    name: str
    oversized: bool


@dataclass(frozen=True, slots=True)
class _RowResult:
    """What became of one row, in the shape the report line carries.

    A `flagged` row **was created** and carries a `tile_id`. The three flags
    are follow-up markers on a Tile that is in the catalogue and searchable,
    never a softer word for a refusal (AD-18, epic context).
    """

    status: str
    tile_id: UUID | None
    flags: list[str]
    error: dict[str, str] | None


def _failed(code: str, message: str) -> _RowResult:
    """One refused row, in the envelope's own `{code, message}` shape.

    Reusing that shape rather than inventing a second one is what makes a
    per-row failure read the same as any other refusal in the product: the
    screen renders `error.message` here exactly as it renders an envelope's.
    """
    return _RowResult(
        status=ROW_FAILED_STATUS,
        tile_id=None,
        flags=[],
        error={"code": code, "message": message},
    )


def _invalid_manifest(detail: str) -> ApiError:
    """The manifest is not one. A `422`, before a byte of the stream exists.

    Pre-stream, which is the only reason a real envelope is possible at all:
    once the first row has been written the status is `200` and there is
    nowhere left to put a `422`. `detail` names what was wrong with the file
    and `NO_MANIFEST` names the fix, in that order.
    """
    return _refusal(
        INVALID_MANIFEST, f"{detail} {NO_MANIFEST}", status.HTTP_422_UNPROCESSABLE_CONTENT
    )


def _read_manifest(manifest: UploadFile | None) -> bytes:
    """The manifest's bytes, bounded, or the `422` that says none arrived."""
    if manifest is None or not (manifest.filename or manifest.size):
        raise _invalid_manifest("No spreadsheet was attached.")

    data = manifest.file.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise _invalid_manifest("That spreadsheet is too large to be a list of codes.")
    if not data:
        raise _invalid_manifest("That spreadsheet is empty.")
    return data


def _manifest_rows(data: bytes) -> list[_ManifestRow]:
    """The manifest's data rows, or the `422` naming why there are none.

    **`utf-8-sig`, not `utf-8`.** A sheet exported from Excel carries a byte
    order mark, and read as plain UTF-8 its first header becomes `﻿file`
    — a column named `file` that no lookup matches, so every real export would
    be refused for missing the column it plainly has.

    **Headers are matched case- and whitespace-insensitively** for the same
    reason: `File `, `CODE` and ` Size` are what a hand-maintained sheet
    actually contains, and refusing them would be refusing the data this
    endpoint exists to load. Every other column is ignored rather than refused
    — a real export carries notes and counts, and none of them is this
    endpoint's business.

    A row whose three required cells are *all* empty is a blank line and is
    skipped; a row with some of them filled is a real row that will fail
    below, with a code naming the cell. The difference matters because a
    trailing newline is not a row an Administrator has to be told about.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as undecodable:
        # Almost always a workbook rather than a CSV: `.xlsx` is a ZIP archive
        # and its first bytes do not decode as text at all.
        raise _invalid_manifest("That file is not a readable CSV.") from undecodable

    reader = csv.DictReader(io.StringIO(text))
    try:
        # **`csv` raises, and what it raises is not a `ValueError` a caller
        # would think to expect.** A cell past `csv.field_size_limit()`
        # (131072 characters by default) and a NUL byte anywhere in the stream
        # both raise `csv.Error` — out of the handler, past every refusal
        # below, and into `api.main`'s unhandled-error path as a `500`. A
        # spreadsheet this endpoint cannot read is a `422` whatever shape the
        # defect takes, and the sentence is the same one: export it as CSV.
        #
        # `fieldnames` is where the header is actually parsed — the attribute
        # reads the first row lazily — so the guard has to be here and not on
        # the constructor above.
        header = reader.fieldnames
    except csv.Error as malformed:
        raise _invalid_manifest("That spreadsheet could not be read as a CSV.") from malformed
    if not header:
        raise _invalid_manifest("That spreadsheet has no header row.")

    # First spelling wins, so a sheet carrying `code` and `Code` resolves to
    # the leftmost of the two rather than to whichever `dict` iteration order
    # happened to keep.
    columns: dict[str, str] = {}
    for name in header:
        if name is None:
            continue
        columns.setdefault(name.strip().lower(), name)

    missing = [column for column in MANIFEST_COLUMNS if column not in columns]
    if missing:
        raise _invalid_manifest(f"The spreadsheet has no {' or '.join(missing)} column.")

    def cell(record: dict[str, Any], column: str) -> str:
        value = record.get(columns[column]) if column in columns else None
        # `DictReader` answers `None` for a short row and a list for a long
        # one (under `restkey`, which is not set here, the extras are
        # discarded). Neither is a string, and both mean the cell is empty.
        return value.strip() if isinstance(value, str) else ""

    try:
        # Drained in one go, and guarded for the header's reason: the same
        # `csv.Error` can come out of any row rather than only out of the
        # first. Materialising is safe because `MAX_MANIFEST_BYTES` has already
        # bounded the text this is parsed from.
        records = list(reader)
    except csv.Error as malformed:
        raise _invalid_manifest("That spreadsheet could not be read as a CSV.") from malformed

    rows: list[_ManifestRow] = []
    for record in records:
        file_name = cell(record, "file")
        code = cell(record, "code")
        size = cell(record, "size")
        if not (file_name or code or size):
            continue
        category = cell(record, MANIFEST_OPTIONAL_COLUMN)
        rows.append(
            _ManifestRow(
                number=len(rows) + 1,
                file=file_name,
                code=code,
                size=size,
                category=category or None,
            )
        )

    if not rows:
        raise _invalid_manifest("That spreadsheet has a header row and no tiles under it.")
    return rows


def _pairing_key(name: str) -> str:
    """The name a manifest cell and an upload are paired on.

    **The base name, case-folded.** The base name because a `file` cell reading
    `45X90/POLISH/a.jpg` — which is how the source tree names a file, and what
    a sheet built from a directory listing carries — names the same image as a
    part called `a.jpg`. Case-folded because a sheet exported on one machine
    routinely spells `IMG_1.JPG` where the file on disk is `img_1.jpg`, and
    refusing that pair would refuse the row *and* report its image as unmatched
    — two lines of report for one difference the Administrator cannot see.

    Both separators are folded before the base name is taken. A sheet
    maintained on Windows spells that same directory listing
    `45X90\\POLISH\\a.jpg`, and `Path` on this server splits on `/` only —
    so the backslash form would arrive whole, pair with nothing, and produce
    the two lines this function exists to prevent.

    A real collision still survives this: two uploads that differ only by case
    fold to one key, land in one list, and the pairing below refuses that row
    as ambiguous rather than picking one of them.
    """
    return Path(name.replace("\\", "/")).name.casefold()


def _spool(uploads: list[UploadFile], directory: Path) -> tuple[dict[str, list[_Spooled]], int]:
    """Copy every uploaded image into `directory`, keyed for pairing.

    Returns the spool and how many parts carried bytes but no usable file name.

    **The handler owns the bytes it reads later, and this is why.** Under a
    `StreamingResponse` the endpoint function returns before the body runs, and
    FastAPI's dependency exit stack — which closes the multipart form — unwinds
    at that return. Reading an `UploadFile` from inside the generator is
    therefore reading a file that may already be closed. Copying first makes
    the lifetime explicit, and copying in chunks keeps memory at one buffer
    rather than the whole batch.

    A key is allowed to arrive twice. The list is what lets the pairing below
    refuse that row as ambiguous rather than silently picking one of the two
    files — which would put the wrong image under a Code with nothing raised.

    **A part with bytes and no name is counted, not dropped.** It cannot be
    paired — nothing can name it — but silently discarding it is the exact
    failure `image_unmatched` exists to prevent: an image that travelled, was
    not indexed, and that the Administrator believes is in the catalogue. The
    caller reports one line per such part. A part with neither a name nor any
    bytes is a picker with nothing chosen and really is nothing, so it is
    filtered out before this is called.
    """
    spooled: dict[str, list[_Spooled]] = {}
    unnamed = 0

    for index, upload in enumerate(uploads):
        # Both separators folded before the base name is taken, exactly as
        # `_pairing_key` folds them. A part declared `C:\shots\a.jpg` pairs on
        # `a.jpg` either way, but this is the name the report quotes back and
        # sorts on — so without the fold one line of the report names a file
        # and another names a whole Windows path for the same image.
        name = Path((upload.filename or "").replace("\\", "/")).name
        if not name:
            # Reported by the caller as `image_unmatched`. Not spooled, because
            # no row can name it and there is therefore nothing to read it for.
            unnamed += 1
            continue

        path = directory / str(index)
        written = 0
        oversized = False
        with path.open("wb") as sink:
            while True:
                chunk = upload.file.read(SPOOL_CHUNK_BYTES)
                if not chunk:
                    break
                if written + len(chunk) > MAX_IMAGE_BYTES:
                    # One byte past the ceiling is enough to decide. Nothing
                    # more is copied, read or decoded — see `_Spooled` for what
                    # that does and does not save.
                    oversized = True
                    break
                sink.write(chunk)
                written += len(chunk)

        spooled.setdefault(_pairing_key(name), []).append(
            _Spooled(path=path, name=name, oversized=oversized)
        )

    return spooled, unnamed


def _bulk_row(
    conn: psycopg.Connection,
    store: ObjectStore,
    administrator: User,
    source_ip: str | None,
    row: _ManifestRow,
    spooled: dict[str, list[_Spooled]],
) -> _RowResult:
    """One row: validate, pair, intake, embed, write, record. `add_tile`'s shape.

    **Its own transaction and its own audit entry**, so a failure takes only
    this row down and the next one proceeds — which is the whole of "reports
    per row, not per batch". A refused row leaves nothing behind: no `tile`, no
    `reference_image`, no `reference_embedding` and no stored object.

    **The defects the real catalogue carries are classified, not conflated**
    (AD-18): a blank Category and a Code with no trailing number are flags on a
    Tile that was created, while a zero-byte or unreadable file is a failure of
    this row. Two rows sharing a Size and a Category are two distinct Tiles and
    nothing here merges, deduplicates or reports a conflict between them — they
    resolve to the same two lookup rows and to two `tile` rows, which is what
    AD-18 says a Category folder holding 26 files is.
    """
    if not row.file:
        return _failed(IMAGE_NOT_PAIRED, NO_FILE_NAMED)

    candidates = spooled.get(_pairing_key(row.file), [])
    if not candidates:
        return _failed(IMAGE_NOT_PAIRED, NOT_PAIRED.format(file=row.file))
    if len(candidates) > 1:
        return _failed(IMAGE_NOT_PAIRED, AMBIGUOUS_PAIR.format(file=row.file))
    spool_entry = candidates[0]

    # The cheap rules first, exactly as `add_tile` orders them: nothing a rule
    # can reject costs a decode, let alone sixteen forward passes.
    try:
        tile_code = clean_code(row.code)
    except ValueError as invalid:
        return _failed(INVALID_CODE, str(invalid))
    try:
        size_name = clean_size(row.size)
    except ValueError as invalid:
        return _failed(INVALID_SIZE, str(invalid))
    try:
        # Never a refusal for being absent (AD-18) — the sentinel and a flag.
        category_name = clean_category(row.category)
    except ValueError as invalid:
        return _failed(INVALID_CATEGORY, str(invalid))

    flags: list[str] = []
    # Read off the *resolved* Category rather than off the cell. A blank cell
    # and a cell that spells the sentinel are the same fact — this Tile has no
    # recoverable Category — and flagging only the first would file a Tile
    # under `UNKNOWN` and report it as a clean success (AD-18).
    if row.category is None or category_name == UNKNOWN_CATEGORY:
        flags.append(FLAG_UNKNOWN_CATEGORY)
    # A display hint and nothing else. The dash-delimited names in the real
    # tree carry none, so this is a flag rather than a guess or a refusal.
    trailing_number = face_number(tile_code)
    if trailing_number is None:
        flags.append(FLAG_UNKNOWN_FACE_NUMBER)

    if spool_entry.oversized:
        return _failed(IMAGE_TOO_LARGE, TOO_LARGE)

    # The duplicate-Code pre-flight. **An optimisation and not the decision** —
    # `tile_code_key` is, and the `UniqueViolation` below is what enforces it.
    # What this buys is the ordinary case: a Code already in the catalogue is
    # reported before sixteen forward passes are spent on an image that is
    # about to be thrown away.
    if conn.execute(_SELECT_CODE, (tile_code,)).fetchone() is not None:
        return _failed(CODE_ALREADY_EXISTS, CODE_IN_USE)

    tile_id = uuid4()
    try:
        # The add's own two halves, and nothing of this path's own. A zero-byte
        # file, a renamed text file and a truncated one all raise out of the
        # first of them, which is what keeps a garbage embedding out of the
        # index (AD-7).
        accepted = _accept_bytes(spool_entry.path.read_bytes())
        prepared = _prepare(tile_id, accepted)
    except ApiError as refused:
        return _failed(refused.code, refused.message)

    if prepared.featureless:
        # FR-19's threshold. Still created and still searchable — the flag is
        # what tells an Administrator the reference is worth re-shooting, and
        # `reference_image.featureless` carries it on the Tile's own screen.
        flags.append(FLAG_LOW_QUALITY_IMAGE)

    written: list[str] = []
    try:
        store.put(prepared.source_key, prepared.source)
        written.append(prepared.source_key)
        store.put(prepared.derivative_key, prepared.derivative)
        written.append(prepared.derivative_key)

        with conn.transaction():
            generation_id = ensure_active_generation(conn)
            size_id = conn.execute(_RESOLVE_SIZE, (size_name,)).fetchone()
            category_id = conn.execute(_RESOLVE_CATEGORY, (category_name,)).fetchone()
            assert size_id is not None and category_id is not None

            try:
                tile_row = conn.execute(
                    _INSERT_TILE,
                    (
                        tile_id,
                        tile_code,
                        size_id["id"],
                        category_id["id"],
                        trailing_number,
                    ),
                ).fetchone()
            except pg_errors.UniqueViolation as clash:
                # Two rows of one batch claiming a Code land here, as does a
                # Code another request claimed in between. Narrowed to the one
                # index by name; a clash this handler cannot explain is
                # re-raised and becomes `row_failed`.
                if clash.diag.constraint_name != CODE_UNIQUE_INDEX:
                    raise
                raise _refusal(
                    CODE_ALREADY_EXISTS, CODE_IN_USE, status.HTTP_409_CONFLICT
                ) from clash
            assert tile_row is not None

            image_row = conn.execute(
                _INSERT_REFERENCE_IMAGE,
                (
                    prepared.image_id,
                    tile_id,
                    prepared.source_key,
                    prepared.derivative_key,
                    prepared.sha256,
                    prepared.width,
                    prepared.height,
                    len(prepared.source),
                    len(prepared.derivative),
                    prepared.pixel_std,
                    prepared.featureless,
                ),
            ).fetchone()
            assert image_row is not None

            with conn.cursor() as cursor:
                cursor.executemany(
                    _INSERT_EMBEDDING,
                    [
                        (prepared.image_id, generation_id, vector, kind, index)
                        for kind, index, vector in prepared.embeddings
                    ],
                )

            # **`catalogue_tile_added`, and no new action.** A Tile added by
            # bulk is a Tile added: same actor, same consequence, same
            # `details` shape. A second action naming the same fact is drift,
            # and a `bulk` marker inside `details` would fork a shape three
            # tests pin. Inside this row's transaction, so a Tile that exists
            # always has a record of who added it.
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
                    "reference_images": 1,
                },
            )
    except ApiError as refused:
        # The `409` above, raised from inside the transaction. The rows rolled
        # back with it, so the objects are next.
        _discard(store, written)
        return _failed(refused.code, refused.message)
    except BaseException:
        # Every other failure, `BaseException` included for `add_tile`'s
        # reason: a cancelled request must not leave objects behind either.
        # Re-raised — the caller turns it into `row_failed` and logs it.
        _discard(store, written)
        raise

    return _RowResult(
        status=ROW_FLAGGED if flags else ROW_CREATED,
        tile_id=tile_id,
        flags=flags,
        error=None,
    )


def _row_line(number: int | None, file_name: str, code: str | None, result: _RowResult) -> str:
    """One report line: a JSON object and the newline that terminates it.

    Two shapes travel on this stream and `kind` is what tells them apart, so a
    reader never has to infer which it is holding from which keys are present.
    Every key is written on every row line, `null` included: a screen that had
    to test for a key's presence as well as its value is a screen with two
    ways to be wrong.

    **`row` is the row's position among the manifest's data rows, or `null`.**
    Counted from one, with the header row not counted and blank lines skipped,
    so it is an ordinal within the sheet's tiles rather than a physical line
    number — "the twelfth tile in the sheet", not "line twelve of the file".
    That is what an Administrator needs to find the row that was refused, and
    it has to mean a position in that sheet and nothing else. The lines that
    report an upload no row named, and the one that reports the batch
    stopping, therefore carry `null` rather than a number counted on past the
    manifest's end — which would send somebody to row 14 of a sheet that has
    twelve.
    """
    return (
        json.dumps(
            {
                "kind": "row",
                "row": number,
                "file": file_name,
                "code": code,
                "status": result.status,
                "tile_id": None if result.tile_id is None else str(result.tile_id),
                "flags": result.flags,
                "error": result.error,
            },
            separators=(",", ":"),
        )
        + "\n"
    )


def _bulk_stream(
    pool: ConnectionPool,
    store: ObjectStore,
    administrator: User,
    source_ip: str | None,
    rows: list[_ManifestRow],
    spooled: dict[str, list[_Spooled]],
    unnamed: int,
    spool: tempfile.TemporaryDirectory[str],
) -> Iterator[str]:
    """The report, a line at a time, then the summary that closes it.

    **The connection is opened here, not declared as a dependency.** A yielded
    `get_connection` is returned to the pool when the *request function*
    returns, which under a `StreamingResponse` is before a byte of this has
    run — so the rows below would be written on a connection the pool had
    already handed to somebody else.

    **Rows are processed one after another, never concurrently.** AD-16's
    argument applied to the write side: parallel forward passes oversubscribe
    the same cores, so a batch run four at a time finishes no sooner and every
    individual row takes longer to report.

    **The summary always closes the report, including when the batch stops.**
    A failure outside any one row — a pool with no free connection, a database
    that went away between rows — happens *after* the response has started, so
    there is no status left to change and an exception escaping here would
    leave the client holding a `200` with a truncated body: no row saying what
    went wrong, no summary, and rows that really were created looking like
    rows that never ran. So an unexpected failure is logged, reported as a
    final failed line, counted, and the summary is written anyway.

    The spool is removed in the `finally`, which is what makes an abandoned
    batch leave nothing on disk: a client that disconnects mid-stream closes
    the iterator, the generator is thrown into, and the cleanup still runs.
    """
    counts = {ROW_CREATED: 0, ROW_FLAGGED: 0, ROW_FAILED_STATUS: 0}
    try:
        stopped = False
        try:
            with pool.connection() as conn:
                for row in rows:
                    try:
                        result = _bulk_row(conn, store, administrator, source_ip, row, spooled)
                    except Exception:
                        # One row's unexplained failure is not the batch's.
                        # Logged with its traceback, reported as a fixed
                        # sentence that leaks nothing, and the loop continues —
                        # tearing the stream down here would lose the report
                        # for every row that already succeeded.
                        logger.exception(
                            "bulk row %s (%s) could not be added", row.number, row.file
                        )
                        result = _failed(ROW_FAILED, ROW_FAILED_MESSAGE)

                    counts[result.status] += 1
                    yield _row_line(row.number, row.file, row.code or None, result)

                # An image no row named. Reported rather than silently dropped:
                # an upload that travelled and was not indexed is a tile the
                # Administrator believes is in the catalogue. Sorted by the
                # name as declared, so two runs of the same batch report them
                # in the same order, and one line per *file* rather than per
                # key — two uploads differing only by case are two images and
                # two things to go and look at.
                named = {_pairing_key(row.file) for row in rows}
                orphans = [
                    entry
                    for key, entries in spooled.items()
                    if key not in named
                    for entry in entries
                ]
                for entry in sorted(orphans, key=lambda spooled_file: spooled_file.name):
                    counts[ROW_FAILED_STATUS] += 1
                    yield _row_line(None, entry.name, None, _failed(IMAGE_UNMATCHED, NOT_NAMED))

                # A part that carried bytes and declared no file name. Nothing
                # can name it, so it is reported rather than dropped — the
                # whole reason `image_unmatched` exists. The line carries an
                # empty `file` because there is none, and the sentence says so.
                for _ in range(unnamed):
                    counts[ROW_FAILED_STATUS] += 1
                    yield _row_line(None, "", None, _failed(IMAGE_UNMATCHED, UNNAMED_UPLOAD))
        except Exception:
            # Outside any row, and after the response has started. See above.
            logger.exception("the bulk upload stopped before every row was processed")
            stopped = True

        if stopped:
            counts[ROW_FAILED_STATUS] += 1
            yield _row_line(None, "", None, _failed(ROW_FAILED, BATCH_STOPPED_MESSAGE))

        yield (
            json.dumps(
                {
                    "kind": "summary",
                    "created": counts[ROW_CREATED],
                    "flagged": counts[ROW_FLAGGED],
                    "failed": counts[ROW_FAILED_STATUS],
                },
                separators=(",", ":"),
            )
            + "\n"
        )
    finally:
        # Guarded, because this runs *after* the summary has been written: a
        # directory that will not go away is an operator's problem, and letting
        # it escape here would turn a complete report into a torn-down response
        # for the one reader who had already received every line of it.
        try:
            spool.cleanup()
        except OSError:
            logger.exception("the bulk spool could not be removed")


@router.post("/admin/tiles/bulk")
def bulk_upload(
    administrator: Annotated[User, Depends(require_administrator)],
    pool: Annotated[ConnectionPool, Depends(get_pool)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
    manifest: Annotated[UploadFile | None, File()] = None,
    images: Annotated[list[UploadFile] | None, File()] = None,
) -> StreamingResponse:
    """FR-17 — load a whole range, and report on it row by row.

    **Registered above every route that takes a path parameter under
    `/admin/tiles/`**, so the literal `bulk` segment can never be read as a
    Tile id. There is no `POST /admin/tiles/{tile_id}` today; the ordering is
    what keeps that a property of the route table rather than of nobody having
    added one yet.

    **Everything refusable is refused before the first byte of the stream.**
    The HTTP status is committed at that byte, so authorization, the manifest,
    the row cap, the missing model artifact and AD-14's stamp are all decided
    while a real `{"error": {...}}` envelope under a 4xx or 5xx is still
    possible. Afterwards the status is `200` and every outcome is a row —
    which is the cost of streaming, paid deliberately in exchange for a report
    that arrives as it happens rather than after minutes of silence
    (EXPERIENCE.md:94).

    **No job table, no queue, no worker, no polling endpoint.** One request,
    one stream, nothing to garbage-collect. The connection stays busy for the
    life of the batch, so no idle timeout fires on a run that takes minutes.

    Sync, not `async def`, for `add_tile`'s reason: psycopg is synchronous and
    the embedding is CPU-bound for tens of seconds per image. The generator is
    sync too, and Starlette iterates it in the threadpool.
    """
    rows = _manifest_rows(_read_manifest(manifest))

    # A part with neither a name nor any bytes is a file picker with nothing
    # chosen, which `add_tile` filters the same way at its own `uploads` line.
    # It is nothing, so it counts as nothing — against the cap below and in the
    # report.
    uploads = [upload for upload in (images or []) if upload.filename or upload.size]

    # **One ceiling, counted on both sides.** The row count alone bounds the
    # manifest and nothing else, so a one-row sheet sent with four hundred
    # image parts would pass it and then be spooled in full — a copy of every
    # part at up to `MAX_IMAGE_BYTES`, for a batch that can produce one Tile.
    # Counting the parts against the same number is what makes
    # `MAX_BULK_ROWS`'s claim to bound the spool true.
    if len(rows) > MAX_BULK_ROWS or len(uploads) > MAX_BULK_ROWS:
        raise _refusal(TOO_MANY_ROWS, TOO_MANY_ROWS_MESSAGE, status.HTTP_422_UNPROCESSABLE_CONTENT)

    # The two deployment-level refusals, pre-flighted rather than discovered on
    # row 1. Both would otherwise fail every row of the batch identically,
    # which is a report of a hundred lines saying one thing that belongs in an
    # envelope. `_prepare` still raises its own for the artifact, because a
    # file deleted between this check and that call is a real state.
    if not shared_vision.MODEL_PATH.exists():
        raise _refusal(MATCHING_UNAVAILABLE, NOT_INSTALLED, status.HTTP_503_SERVICE_UNAVAILABLE)
    with pool.connection() as conn:
        # AD-14, read-only: a deployment running ahead of its re-index refuses
        # the whole batch in milliseconds rather than one row at a time.
        active_generation(conn)

    # Spooled *here*, inside the request function, because the multipart form
    # is closed when it returns. See `_spool`.
    spool = tempfile.TemporaryDirectory(prefix="rocell-bulk-")
    try:
        spooled, unnamed = _spool(uploads, Path(spool.name))
    except BaseException:
        # Nothing has been streamed yet, so the caller is about to be told this
        # failed — and the directory must not outlive the request either way.
        spool.cleanup()
        raise

    return StreamingResponse(
        _bulk_stream(pool, store, administrator, source_ip, rows, spooled, unnamed, spool),
        media_type=NDJSON,
        # `no-store` like every other authenticated response: a report naming
        # Codes is catalogue data. `nosniff` because a browser that sniffed its
        # way from NDJSON to something executable would be running script from
        # the catalogue — the same argument the reference-image read makes.
        headers={**NO_STORE, **NO_SNIFF},
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
#: absent because it is not sent: it is derived from the Code, so an edit that
#: moved it moved the Code, and the Code's own entry already says so.
#: `updated_at` is absent because it moves on
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


#: The three characters `ILIKE` reads as syntax, and what each becomes.
#:
#: A `str.translate` table rather than three chained `str.replace` calls,
#: because the chain has a correctness trap the table does not: it has to
#: escape `\` *first*, or the second and third replacements re-escape the
#: backslashes the first one just added and `%` arrives as `\\%` — a literal
#: backslash followed by a wildcard. `translate` walks the string once and
#: never re-reads what it wrote.
#:
#: `\` is the escape character `LIKE`/`ILIKE` use by default in PostgreSQL, so
#: no `ESCAPE` clause is needed and none is written — adding one would be a
#: second statement of the same fact for the reader to keep in step.
_PATTERN_ESCAPES = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def _pattern(query: str) -> str:
    """`query` as an unanchored `ILIKE` pattern that matches it **literally**.

    Two things happen here and both are about the *value*, never the statement
    (`_SEARCH_TILES` says why): the query is wrapped in `%` so it matches
    anywhere in a Code, and the three characters the pattern language owns are
    escaped so a Code is the only thing they can match.

    Without the escaping, `?q=%` would be "every tile" and `?q=_` would be
    "every tile whose Code is at least one character" — both of which read as a
    working search returning nonsense rather than as the empty answer they
    should be. `?q=\\` would be worse: a trailing lone backslash is a malformed
    pattern and Postgres raises on it, which would leave a `500` behind a
    character somebody can type by accident.

    A blank query becomes `%%`, which matches every Code including the empty
    string — there are none, since `clean_code` refuses a blank Code — so
    browsing the whole Catalogue needs no second statement and no branch.
    """
    return f"%{query.translate(_PATTERN_ESCAPES)}%"


def _search_images(
    conn: psycopg.Connection, tile_ids: list[UUID]
) -> dict[UUID, list[ReferenceImage]]:
    """Every named Tile's Reference Images, grouped by Tile, in one statement.

    **`tile_id` is popped off the row before validation.** `ReferenceImage` is
    `extra="forbid"`, so leaving it on would fail every row — which is the
    contract doing its job: the key is how this function finds the Tile, and it
    is not a field of the image the client is handed.

    **The empty case short-circuits and does not run the statement.** An empty
    Python list has no element type for psycopg to infer, so `ANY(%s)` on it is
    a driver error rather than an empty answer — and there is nothing to ask
    about anyway when no Tile matched.

    A Tile with no surviving image is simply absent from the answer, and the
    caller reads it out with a default rather than indexing: nothing in the
    schema guarantees a row here, and a `KeyError` on the list would take the
    whole Catalogue screen down over one Tile.
    """
    if not tile_ids:
        return {}

    grouped: dict[UUID, list[ReferenceImage]] = {}
    for row in conn.execute(_SEARCH_TILE_IMAGES, (tile_ids,)).fetchall():
        grouped.setdefault(row.pop("tile_id"), []).append(ReferenceImage.model_validate(row))
    return grouped


@router.get("/admin/tiles", response_model=list[Tile])
def search_tiles(
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    q: str = "",
) -> list[Tile]:
    """FR-18 — the Catalogue, and the substring search that narrows it.

    **Substrings of the Code, case-insensitively, and nothing else.** `q=CMA`
    answers every Tile whose Code contains `CMA` anywhere, in either case;
    `q=cma` answers the same ones. Size and Category are **displayed** on every
    row and consulted by nothing: they are groupings rather than the identity
    (AD-18), and a `size + category` filter is the one query shape CLAUDE.md
    forbids outright, because two Tiles sharing both are two different tiles and
    filtering on them hides the row somebody opened the screen to find.

    **A blank `q` browses the whole Catalogue.** EXPERIENCE.md:35 is
    "Search/**browse** Tiles" — the screen opens on the full list and narrows
    from there — so an absent or empty query is the ordinary case and not a
    refusal. `_pattern` turns it into `%%` and the same statement serves both.

    **No match is `200` and an empty array, never a `404`.** "Nothing matches
    that fragment" is an answer; `lookup_tile`'s `404` is for an exact Code that
    names no Tile, which is a different question.

    **A bare JSON array, with no cursor, total, page or cap.** `api.users`'
    `list_users` argues this on a table of tens of rows; the argument is the
    same here and the numbers are still small — 381 files today, and the whole
    index is sized at ~10k vectors, which is a few hundred Tiles at sixteen
    views each. So the largest answer this route can give is a few hundred rows
    of short text plus their image ids. A cap would need a number, a TypeScript
    twin, a `BOUNDS` parity row and a "showing the first N" sentence that stops
    being true the moment somebody narrows the search; a caller-settable
    `limit` is the DoS knob `api.audit` refuses. If the Catalogue ever outgrows
    this, both halves of the contract change together — and measure first
    (CLAUDE.md).

    **Two statements, not a join and not one read per row.** `_SEARCH_TILES`
    answers the Tiles and `_SEARCH_TILE_IMAGES` answers their images by
    `tile_id = ANY(...)`; `_search_images` says why that shape beats both
    alternatives.

    **No storage key and no URL crosses the wire** (AD-9). The `Tile` contract
    has nowhere to put one and this route emits none: a row's image is fetched
    from `GET /admin/tiles/{tile_id}/images/{image_id}`, which re-checks the
    Administrator role on every request. No similarity value either (AD-20) —
    this route does not rank anything.

    The `administrator` parameter is unread: on this route the dependency is the
    whole of its job. And **nothing is recorded** — `lookup_tile`'s own
    argument, and FR-20 covers *changes*: a read changes nothing, and an entry
    per search would bury the entries the log exists for.

    Deliberately absent: a `GET /admin/tiles/{tile_id}` detail route. The list
    already carries the whole `Tile`, and the Catalogue row hands it to Edit
    Tile the way the user list hands a `User` to Edit User — a second route
    fetching by id would serve nothing and would have to be ordered around the
    `lookup` segment.
    """
    response.headers.update(NO_STORE)

    try:
        wanted = clean_query(q)
    except ValueError as invalid:
        raise _refusal(
            INVALID_QUERY, f"{invalid} {BAD_QUERY}", status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from invalid

    rows = conn.execute(_SEARCH_TILES, (_pattern(wanted),)).fetchall()
    images = _search_images(conn, [row["id"] for row in rows])

    return [
        Tile(
            id=row["id"],
            code=row["code"],
            size=row["size"],
            category=row["category"],
            face_number=row["face_number"],
            # `.get` with a default, never `[...]`: see `_search_images`.
            reference_images=images.get(row["id"], []),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


@router.get("/admin/tiles/lookup", response_model=Tile)
def lookup_tile(
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    code: str = "",
) -> Tile:
    """One Tile by an **exact** Code. The API's exact-code door.

    **This is not the catalogue search and must not become it.** `search_tiles`
    above is FR-18's substring match over the whole Catalogue, and the
    Catalogue screen is where EXPERIENCE.md reaches Edit Tile from — a row
    hands that screen the whole `Tile` it already holds. This route answers a
    different question: one Code, exactly, and the Tile it names or nothing.
    `?code=RP.CMA` answers `404` while `RP.CMA.0001DJ.SM.0T` exists, and that
    is the behaviour rather than a gap in it — a prefix match returning "the"
    Tile would answer one of several and the Administrator would edit whichever
    row sorted first.

    **`apps/web` no longer opens a screen with it, and that is not why it
    stays.** Since Story 2.5, `EditTileScreen` is only ever rendered with a
    Tile a Catalogue row handed it, so its code-entry stage is a *fallback*
    rather than an entry point: it is what that screen falls back to when a save
    is refused `404` because the Tile was renamed or removed from under the
    form, and it calls this route from there.

    It stays because the API owes the lookup independently of which screen
    happens to call it. Story 2.2's authorization acceptance clause names it,
    `tests/test_tile_lookup.py` is the suite that holds the exact-match rule to
    account, and "look up one Code" is a question a client can reasonably ask
    without reading the whole Catalogue to find the answer. Deleting a tested
    route inside a search story would be a separate decision with its own
    review.

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

            # **Re-derived whenever the Code is, and left alone otherwise.**
            # The trailing number is read off the Code and nothing else, so a
            # Tile whose Code changed and whose stored hint did not would show
            # a number belonging to a Code it no longer carries — a Tile the
            # bulk path created as `RP.CMA.0008DJ.SM.0T` (hint `8`) and that was
            # then renamed still reading `8`. An edit that did not send a Code
            # writes the stored value back untouched, the way every other
            # column here does: nothing about the Code changed, so nothing
            # derived from it may.
            trailing_number = current["face_number"] if new_code is None else face_number(tile_code)

            try:
                tile_row = conn.execute(
                    _UPDATE_TILE,
                    (tile_code, size_row["id"], category_id, trailing_number, tile_id),
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


# --- The removal (FR-16) ------------------------------------------------------


@router.delete("/admin/tiles/{tile_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_tile(
    tile_id: UUID,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
) -> None:
    """FR-16 — withdraw a Tile from the Catalogue, index and all.

    **Real removal, and one statement of it** (AD-5). `DELETE FROM tile` and the
    migration's two `ON DELETE CASCADE`s carry `reference_image` and then
    `reference_embedding` out of the HNSW graph with it. There is no
    soft-delete column, no `deleted_at` and no query-time predicate anywhere:
    a predicate is a thing exactly one call site has to remember, and Epic 3's
    scan is the call site that must not forget. `_SELECT_CANDIDATES` joins
    through both tables, so a removed Tile leaves the result set by the cascade
    alone, with no filter to add and none to forget.

    **`204`, with no body**, exactly as `delete_user` answers. There is no row
    left to return and answering with the one that was deleted would be the
    product describing something that no longer exists; `apps/web`'s
    `apiRequest` answers `null` for a `204` without parsing a body.

    **Not idempotent, on purpose.** An unknown id is `404 tile_not_found` and
    not a silent `204`: a caller told "removed" about a Tile that was never
    there has been told they removed something they did not. The `404` is
    decided by the locking read, never by a zero-row `DELETE` — a zero-row
    `DELETE` cannot tell "no such id" from anything else.

    **`FOR UPDATE OF t`**, so a `PATCH` on the same Tile serializes against this
    rather than adding an image into a row that is going. Whichever commits
    second sees the other: an edit that loses the race answers `404` and
    discards every object it wrote.

    **Database first, storage second — the inverse of the add's ordering, and
    the same rule read backwards.** `add_tile` writes objects before rows so a
    failed request leaves an orphan rather than a row pointing at nothing;
    deleting the bytes before this commit would leave a live row pointing at
    nothing if the transaction then rolled back. So the bytes go last, best
    effort and logged — a file an operator can delete, never a `500` over a
    removal that succeeded.

    **The entry is written after the `DELETE` and inside its transaction**, so
    it exists exactly when the removal committed, and its `details` are an
    AD-10 snapshot taken from the locked read because there is nothing left to
    read them from. `target_user_id`/`target_email` stay empty — those columns
    are an account's, and a Tile is not one.

    **Nothing here touches the log** beyond appending to it (AD-4). The entries
    that already name this Tile — the `catalogue_tile_added` that recorded it,
    every `catalogue_tile_edited` since — stay exactly as they are, which is
    the whole point of recording the removal beside them. The log carries no
    foreign key into `tile` for precisely this reason — AD-4 grants the
    application no `DELETE` there, so one would leave a choice between blocking
    every removal and cascading into a table nothing may delete from.

    Sync, not `async def`, for `add_tile`'s reason: psycopg is synchronous.
    Nothing here decodes or embeds anything — a removal takes rows out of the
    active generation, it does not cut a new one — so the route needs no model
    artifact and reads no pipeline stamp.
    """
    response.headers.update(NO_STORE)

    with conn.transaction():
        current = conn.execute(_SELECT_TILE_FOR_UPDATE, (tile_id,)).fetchone()
        if current is None:
            raise _tile_not_found()

        # Before the `DELETE`, because afterwards there is no row to read them
        # from — and these keys are the only way back to the bytes.
        held = conn.execute(_SELECT_TILE_IMAGE_KEYS, (tile_id,)).fetchall()

        deleted = conn.execute(_DELETE_TILE, (tile_id,)).rowcount
        # The row was found and locked three lines above, so the statement
        # cannot have matched nothing. Asserted rather than branched on: there
        # is no second outcome for this handler to describe.
        assert deleted == 1, "the locked tile cannot have vanished under its own lock"

        # FR-20's answer to "who took this out of the Catalogue, and when".
        # Every value is a snapshot from the locked read (AD-10) and none of
        # them is a foreign key — the Tile they name is gone by the time this
        # row is visible, which is exactly the state the log has to survive.
        audit.record(
            conn,
            action=AuditAction.CATALOGUE_TILE_REMOVED,
            actor_id=administrator.id,
            actor_email=administrator.email,
            source_ip=source_ip,
            details={
                "tile_id": str(tile_id),
                "code": current["code"],
                "size": current["size"],
                "category": current["category"],
                "images_removed": len(held),
            },
        )

    # Committed. The rows are gone, so the bytes can follow — best effort and
    # logged, for the reason above. A storage failure here must not turn a
    # removal that has already landed into a `500` the Administrator would read
    # as "nothing happened".
    _discard(
        store,
        [key for row in held for key in (row["source_key"], row["derivative_key"])],
        DISCARD_REMOVED,
    )


# --- The image read (AD-9, AD-17) ---------------------------------------------


def _serve_reference_image(
    conn: psycopg.Connection, store: ObjectStore, tile_id: UUID, image_id: UUID
) -> Response:
    """Look up and proxy one Reference Image's capped derivative. No authorization here.

    **The shared lookup+response logic behind both image routes** — the
    Administrator-only one below and Epic 3's Scan-surface one — so that a
    tile id and an image id that name no row are answered the same "does not
    exist" way from either door, by one implementation rather than two that
    could drift.

    **The source asset has no route**, here or anywhere: AD-17 says the
    original is never served, and the way to make that true is to give it
    nowhere to be asked for. This reads `derivative_key` and there is no
    parameter that can make it read the other column.

    **Proxied, never redirected** (AD-9). The bytes travel through the caller's
    endpoint, which re-checks the caller's role or claimed-user status on every
    request through its own dependency; `apps/web` never holds a storage URL,
    presigned or otherwise.

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

    Nothing here is recorded, because nothing is changed — `AuditAction` has no
    member for a read (FR-20 covers changes), and a log entry per rendered
    thumbnail would bury the entries that matter.
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


@router.get("/admin/tiles/{tile_id}/images/{image_id}")
def read_reference_image(
    tile_id: UUID,
    image_id: UUID,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
) -> Response:
    """Serve one Reference Image's capped derivative to an Administrator.

    A thin, `require_administrator`-gated wrapper over `_serve_reference_image`
    — see that function for the lookup, the proxying and the headers. The
    `administrator` parameter is unread: on this route the dependency is the
    whole of its job.
    """
    return _serve_reference_image(conn, store, tile_id, image_id)


@router.get("/tiles/{tile_id}/images/{image_id}")
def read_scan_reference_image(
    tile_id: UUID,
    image_id: UUID,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
) -> Response:
    """Serve one Reference Image's capped derivative to any claimed session.

    Story 3.4's own door: a Candidate card on the Results screen is not an
    admin surface, and Scan is reachable by every authenticated role — so this
    is gated by `require_claimed_user` alone, never `require_administrator`,
    and it does not sit under `/admin/` (`tests/test_admin_authorization.py`'s
    route-table guard fails the build if a route outside that prefix declares
    the role check).

    **A second route rather than loosening the admin one's gate.**
    `GET /admin/tiles/{tile_id}/images/{image_id}` is deliberately
    Administrator-only; widening it would open an admin surface to Staff. A
    second, thin route over the same `_serve_reference_image` helper keeps
    both authorization boundaries exactly where they are, with one lookup
    implementation behind both.

    The `user` parameter is unread: on this route the dependency is the whole
    of its job.
    """
    return _serve_reference_image(conn, store, tile_id, image_id)
