---
title: 'Story 2.4 — Bulk Upload'
type: 'feature'
created: '2026-09-22'
baseline_revision: 'f9872825e11bb7a19193f52b129676c0626b480f'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-3-remove-product.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The whole multipart body is received and spooled to disk before
      `require_administrator` runs, so a session-holder can push a large body
      before being refused.
    evidence: |-
      FastAPI reads the form before solving dependencies, so the role check
      fires only after every part has been written. Not caused by this story —
      `add_tile` has had the same property since 2.1, and the root cause is
      that nothing in the product bounds a request body: there is no
      middleware (the spine forbids adding one here), no proxy limit in
      `infra/`, and no aggregate ceiling anywhere. A body bound is a
      deployment contract this codebase has no authority to invent.
    location: >-
      apps/api/api/catalogue.py bulk_upload, add_tile
    severity: medium
  - summary: >-
      A batch has no aggregate byte budget, and every upload is written to disk
      twice.
    evidence: |-
      With the row/part cap in place the worst case is `MAX_BULK_ROWS` x
      `MAX_IMAGE_BYTES` of temporary files, and Starlette has already spooled
      each part before `_spool` copies it again. Both copies are needed as
      written — the second is what makes the bytes outlive the multipart form
      under a `StreamingResponse` — so removing the duplication means changing
      how the form's lifetime is held, and a total-bytes ceiling would refuse
      legitimate batches of the 96 MB press files this catalogue really
      contains. The number is a product decision.
    location: >-
      apps/api/api/catalogue.py _spool
    severity: low
  - summary: >-
      `session-expiry.test.tsx`'s 401 assertion is flaky under the full suite's
      parallel load, failing roughly one run in four while passing every time
      the file is run alone.
    evidence: |-
      Observed once during this pass: `make test` failed at `a 401 from any
      request drops the app to the login screen > swaps the shell for the login
      screen and says the session ended` (`findByLabelText(/password/i)` timing
      out with the signed-in shell still rendered), then passed on an isolated
      run of that file and on three consecutive full web-suite runs. The file
      is untouched by this story and nothing here reaches session handling.
      The same flake is already recorded on Story 2.3.
    location: >-
      apps/web/src/__tests__/session-expiry.test.tsx
    severity: low
  - summary: >-
      `EditTileScreen`'s reference-image gallery strips its list markers
      without restating `role="list"`, so it stops being announced as a list.
    evidence: |-
      `EditTileScreen.module.css:200` sets `list-style: none` under a comment
      claiming "the list is still a list to a screen reader, which is what
      makes 'three reference images' audible" — the exact claim this story
      disproved on its own report list and corrected there with an explicit
      `role="list"`. Safari and VoiceOver drop list semantics from a
      marker-less list, so on that pairing the gallery announces neither
      "list, 3 items" nor "image 2 of 3". Pre-existing since Story 2.2;
      nothing in this change touches that screen, and no test in
      `edit-tile.test.tsx` asserts the role or the item count.
    location: >-
      apps/web/src/screens/EditTileScreen.tsx:823
    severity: low
---

<intent-contract>

## Intent

**Problem:** A range is many Tiles, and the only way in is `POST /admin/tiles` — one Code, one form, one page load at a time, with a 26-file category folder costing 26 round trips and no record of which ones landed. `TOO_MANY_IMAGES`' own sentence already sends the Administrator somewhere that does not exist: *"Use Bulk upload for a whole range."* The real catalogue also carries defects a one-at-a-time form has no way to classify — zero-byte files, categories that cannot be recovered, Codes with no trailing number — and a whole-batch pass/fail would hide every one of them.

**Approach:** One admin-only `POST /admin/tiles/bulk` taking a CSV manifest plus the image set, which processes rows **sequentially through the single-add path's own intake and embedding helpers** and streams one NDJSON line per row as that row completes — `created`, `flagged` or `failed` — followed by a summary line; plus a Bulk Upload screen that renders those lines as DESIGN.md's per-row report. Each row is its own transaction and its own `catalogue_tile_added` audit entry, so N valid pairs become N individually searchable Tiles and a failure takes only its own row down.

## Boundaries & Constraints

**Always:**
- **No shortcut for bulk (FR-17, AD-1, AD-7, AD-15).** Every image reaches storage through `_accept` → `_prepare` — the same content-sniff, ICC→sRGB, EXIF-strip, re-encode, 16-view embed and capped derivative that `add_tile` calls. The bulk handler makes no `shared_vision.` call of its own.
- **Per row, not per batch.** One transaction, one audit entry and one report line per row. A refused row leaves nothing behind — no `tile`, no `reference_image`, no `reference_embedding`, no stored object — and the next row proceeds.
- **Rows stream as they complete** (EXPERIENCE.md:94). The response is `application/x-ndjson`, one JSON object per line, flushed when the row finishes. The screen paints each line as it arrives; it never sits behind one spinner until the batch ends.
- **Everything refusable is refused before the first byte of the stream.** Authorization, the manifest parse, the row cap, the AD-14 generation stamp and the missing-model check all run while a real `{"error": {...}}` envelope with a 4xx/5xx status is still possible. Once streaming starts the status is `200` and every outcome is a row.
- **The handler owns the bytes it reads later.** Uploads are spooled to a handler-owned temporary directory before the response is returned, and the generator reads from that spool — never from an `UploadFile` whose form may already be closed. The spool is removed in the generator's `finally`.
- Rows are processed **sequentially**, never concurrently — AD-16's reasoning applied to the write side: parallel forward passes oversubscribe the same cores and make every row slower.
- **Defects are classified, not conflated** (AD-18, epics.md:398-411): a blank/unrecoverable Category is `UNKNOWN_CATEGORY` **and a flag**, never a refusal; a Code with no recoverable trailing number leaves `face_number` NULL **and a flag**; a zero-byte or unreadable file is a **failure**; two rows sharing a Size and Category are two distinct Tiles, merged and deduplicated nowhere and reported as a conflict nowhere.
- `require_administrator` on the route; it lives under `/admin/`. `NO_STORE` and `NO_SNIFF` on the streaming response.
- Domain vocabulary only: `Tile`, `Code`, `Size`, `Category`, `Reference image`. `Product`, `Face` and `Design` appear nowhere as a type, column, class, label or sentence.
- Parameterized SQL only; `api/audit.py` stays the only module naming the audit table.

**Block If:**
- The manifest cannot be a CSV — i.e. something in the repo or the intent requires reading `.xlsx` bytes. That needs a new runtime dependency (`openpyxl`), which AGENTS.md says to flag before adding. Read-only evidence below says CSV is sufficient; this fires only if that turns out false.

**Never:**
- Do not change `add_tile`'s observable behaviour, its response, its refusals or its route. The only edits it may take are mechanical: passing `None` for `_INSERT_TILE`'s new `face_number` parameter, and calling `_accept` through its extracted bytes half.
- Do not add a new `AuditAction`. A Tile added by bulk is a Tile added; the vocabulary stays at sixteen and `details` keeps `catalogue_tile_added`'s exact shape.
- Do not add a job table, a queue, a background worker, a polling endpoint, SSE or WebSockets. One request, one stream.
- Do not add a soft-delete, a dry-run mode, a resume/retry-failed-rows verb, a per-row progress percentage, or a ZIP/folder upload.
- Do not build Story 2.5's catalogue list or substring search, Epic 3's scan endpoint, or a crop step (AD-11 resolved that as *no* for admin uploads).
- Do not implement `scripts/ingest` — it is pre-launch, out of scope, and stays a skeleton.
- Do not add a presigned or direct-to-storage URL (AD-9), a vector database, an ORM, a router or a form library. Do not enable OpenAPI/docs routes, add CORS, or introduce middleware.
- Do not parse the manifest, derive `face_number`, or classify a defect in TypeScript. The server owns every rule; the screen renders what the stream says.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| N valid pairs | Admin session; manifest of 3 rows + 3 images | `200`, `application/x-ndjson`; three `status: "created"` lines then a summary; three Tiles, three Reference Images, 48 embeddings, six objects | No error expected |
| Immediately searchable | After the stream ends, `find_candidates` with a perturbed copy of row 2's image | Row 2's Tile is among the Candidates; no re-index step was run | No error expected |
| Unknown Category | A row whose `category` cell is blank or absent | `status: "flagged"`, `flags: ["unknown_category"]`; the Tile is created against the `UNKNOWN` category row | Never a failure (AD-18) |
| No trailing number | A row whose Code is `RC-001-OHA-156-MA-J2` | `status: "flagged"`, `flags: ["unknown_face_number"]`; Tile created, `face_number` NULL | Never a failure, never a guess |
| Low-quality image | A row whose image comes back `featureless` | `status: "flagged"`, `flags: ["low_quality_image"]`; the Tile is created and its `reference_image.featureless` is true, so the existing tile-level flag applies unchanged | Never a failure |
| Several flags at once | Blank category *and* no trailing number | One `flagged` line carrying both flags, in a stable order | No error expected |
| Zero-byte file | A row whose image is 0 bytes | `status: "failed"`, `error.code: "unreadable_image"`; nothing written for that row; later rows proceed | Never indexed as a garbage embedding |
| Unreadable file | A row whose image is a renamed text file | `status: "failed"`, `error.code: "unreadable_image"` | Content-sniffed, never trusted by extension |
| Oversized file | A row whose image exceeds `MAX_IMAGE_BYTES` or `REFERENCE_MAX_PIXELS` | `status: "failed"`, `error.code: "image_too_large"` | Bounded read; the rest is never read |
| Duplicate Code in the catalogue | A row whose Code already names a Tile | `status: "failed"`, `error.code: "code_already_exists"`; the existing Tile is untouched and its objects survive | Decided by `tile_code_key`, pre-flight is only an optimisation |
| Duplicate Code inside one batch | Two rows carrying the same Code | The first is `created`; the second is `failed` with `code_already_exists` | Same constraint, same code |
| Shared Size and Category | Two rows, same `size` and `category`, different Codes | Both `created`; two distinct Tiles; one `tile_size` row and one `tile_category` row shared | Never merged, never a conflict (AD-18) |
| Blank or invalid Code/Size | A row with an empty `code`, or a `size` over its length bound | `status: "failed"`, `error.code: "invalid_code"` / `"invalid_size"` | `clean_code`/`clean_size` raise; the row is reported |
| Row names a missing image | Manifest names `x.jpg`; no upload matches it | `status: "failed"`, `error.code: "image_not_paired"` | Same code when two uploads share that name; the message says which |
| Image no row names | An upload matched by no manifest row | A trailing `failed` line keyed by that filename with `error.code: "image_unmatched"` | Reported, never silently ignored |
| A row raises unexpectedly | Any unhandled exception while processing one row | `status: "failed"`, `error.code: "row_failed"`, a fixed sentence that leaks nothing; the exception is logged; the batch continues | The stream is never torn down mid-flight |
| Missing or unparseable manifest | No `manifest` part, empty file, no header row, no data rows, or a required column absent | `422` `invalid_manifest` envelope; **no stream**, nothing written | Pre-stream, so a real envelope is still possible |
| Too many rows | Manifest with more than `MAX_BULK_ROWS` data rows | `422` `too_many_rows`; no stream | Counted before any image is read |
| Model artifact absent | `shared_vision.MODEL_PATH` does not exist | `503` `matching_unavailable`; no stream, nothing written | Pre-flighted, not discovered on row 1 |
| Stale generation | The active generation's stamp mismatches | `503` `pipeline_stamp_mismatch`; no stream | AD-14, pre-flighted |
| Staff caller | Valid non-admin session | `403` `administrator_required`; nothing written | Existing dependency |
| Signed-out caller | No session cookie | `401` `unauthorized` | Existing dependency |
| Audit | A batch of 5 with 1 failure | Exactly four `catalogue_tile_added` entries, one per created row, each inside that row's transaction with actor, timestamp, source IP and the `add_tile` `details` shape; none for the failed row | No update or delete ever reaches the log |
| Screen — a batch runs | Administrator picks a sheet and images and starts | Rows appear one at a time as they complete, each with its own navy/red/orange indicator **and a word**; a `role="status"` line reports progress; a summary closes it | No error expected |
| Screen — pre-stream refusal | The server answers `422 invalid_manifest` | The server's own sentence is rendered next to the sheet field; no report list appears | Rendered from the envelope |
| Screen — nothing chosen | Submit with no sheet or no images | The screen refuses before asking the server, naming what is missing | No request is made |

</intent-contract>

## Code Map

**API — the module being extended.** Everything below lands in `apps/api/api/catalogue.py`, not a new module: the helpers it must reuse are private to that file, `catalogue.router` is already registered (`main.py:189`), and `error-code-parity.test.ts:226` scrapes envelope codes from exactly four files of which this is one — a new module would put every new code outside that check.

- `apps/api/api/catalogue.py` -- reuse, do not re-derive: `_refusal` (:259), `_read_upload` (:712), `_accept` (:728), `_prepare` (:754), `_Prepared` (:678), `_source_key`/`_derivative_key` (:702/:707), `_discard` (:794) with `DISCARD_ROLLED_BACK` (:242), `_vector_literal` (:514), `active_generation` (:558), `ensure_active_generation` (:576), `_RESOLVE_SIZE` (:279), `_RESOLVE_CATEGORY` (:285), `_INSERT_TILE` (:293), `_INSERT_REFERENCE_IMAGE` (:299), `_INSERT_EMBEDDING` (:307), `_SELECT_CODE` (:316), `CODE_UNIQUE_INDEX` (:215), `NO_STORE`, `NO_SNIFF` (:256). `add_tile` (:834-1031) is the shape to follow end to end — its validation order, its `store.put`-before-`BEGIN` ordering, its `except BaseException: _discard(...)` belt (:1015) and its `UniqueViolation` narrowing (:950-960). **The module docstring's closing paragraph (:88-92) names "the bulk path (2.4)" as deliberately absent — that sentence is part of this change.**
- `apps/api/api/catalogue.py:293` `_INSERT_TILE` -- extend to `(id, code, size_id, category_id, face_number)`; `add_tile` passes `None`, bulk passes what `face_number()` recovered. One statement, not two.
- `apps/api/api/catalogue.py:728` `_accept` -- split into `_accept_bytes(data: bytes) -> IntakeResult` plus the existing `_accept(upload)` = `_accept_bytes(_read_upload(upload))`. Bulk calls `_accept_bytes`, which is what makes "the same intake path" literal rather than a claim.
- `apps/api/api/db.py:167` `get_connection`, `:155` `get_pool`, `POOL_MAX_SIZE` (:87) -- the bulk route declares `get_pool` and opens `with pool.connection() as conn:` **inside** the generator. A yielded `get_connection` is returned to the pool when the request function returns, which under a `StreamingResponse` is before the body has run.
- `apps/api/api/audit.py:230` `record(...)`, `:149` `source_ip` -- one call per created row, inside that row's transaction. `catalogue.py` must never name `audit_log` (`tests/test_source_guards.py:339`).
- `apps/api/api/dependencies.py:193` `require_administrator`, `:78` `NO_STORE` -- declared, never a line in the handler.
- `apps/api/api/main.py:33` `STATUS_CODES` -- already maps 401/403/422/503. `:189` includes `catalogue.router`; **no registration change**.
- `apps/api/api/storage.py` -- `ObjectStore.put`/`delete`, `get_object_store`.
- `shared/vision/shared_vision/` -- `intake_image`, `generate_views`, `embed_images`, `display_derivative`, `view_kind`, `MODEL_PATH`, `REFERENCE_MAX_PIXELS`. **Read-only: not one line of `shared/vision` changes, so no re-index and no eval run is owed by this story.**

**Contract**
- `shared/schema/shared_schema/tile.py` -- `clean_code` (:101), `clean_size` (:119), `clean_category` (:131), `UNKNOWN_CATEGORY` (:38), `MAX_IMAGE_BYTES` (:66), `MAX_IMAGES_PER_REQUEST` (:54). **Add** `MAX_BULK_ROWS = 100` and `face_number(code: str) -> str | None` — the Code-parsing rule belongs beside the other Code rules, where `scripts/ingest` will reach it too.
- `poc/tilematch/catalog.py:68` `FACE_PATTERNS`, `:76` `extract_face` -- **port verbatim in behaviour**: four patterns, most-specific-first (`^RP\.[A-Z]{3}\.(\d{3,4})[A-Z]{2}\.`, `_F(\d+)$`, `^(\d+)$`, `^(\d+)[A-Z]{1,3}\b`), first match wins, `.lstrip("0") or "0"`, `None` rather than a guess. `poc/tests/test_catalog.py` is the table of real examples to re-assert against. `poc/` is outside this workspace — copy the rule, do not import it.
- `shared/schema/shared_schema/ts/tile.ts` -- add `MAX_BULK_ROWS` only. `face_number` has no TypeScript twin: the client never derives it.
- `shared/schema/shared_schema/audit.py:130` `CATALOGUE_TILE_ADDED` -- reused as-is. **No new member, so `test_audit.py:133`, `audit-contract.test.ts:49` and `ts/audit.ts` are all untouched.**

**Schema (read-only evidence — no migration)**
- `infra/migrations/20260921T1500_create_catalogue.up.sql:96` -- `code text NOT NULL UNIQUE` (`tile_code_key`), on the Code alone. `:104` `face_number text` nullable. `:85` seeds the `UNKNOWN` category row. `:206` `UNIQUE (reference_image_id, generation_id, view_index)`. `:232-237` already grant `rocell_app` full DML on all six tables. Nothing here needs DDL.

**Web**
- `apps/web/src/screens/AddTileScreen.tsx` -- the screen to model on, not to extend: `UNEXPECTED` (:70), `SAVING`/`SAVED` (:86-87), the mirrored bound constants (:102-106), `Field`/`FormError` (:127-139), `fieldFor` (:142), `refuse` (:227), `chooseFiles` (:233), the single-`role="alert"`-in-one-of-N-slots discipline (:325-330, :362-459), the `role="status"` indicator that is in the document at rest (:477-482), the `.flag` treatment for `featureless` (:517). Its docstring (:66) says "No list, no edit, no removal, **no bulk upload.** Stories 2.2 to 2.5." — that sentence is part of this change.
- `apps/web/src/api/client.ts:466` `apiRequest` -- handles FormData (:472, :492-500) but always `await response.json()` (:511). **Add a sibling `apiStream(path, options, onLine)`** that shares `ApiRequestError`, `failed()` (:384), the `notifyUnauthorized()` 401 hook (:542) and the envelope parse for a non-`ok` response, then reads `response.body` line by line. Fall back to `await response.text()` split on newlines when `response.body` is absent, so the function works under jsdom. Its timeout is **idle**, not total — the abort timer resets on every chunk, or a long batch aborts itself.
- `apps/web/src/api/client.ts:184-293` -- the envelope-code exports. Add `INVALID_MANIFEST`, `TOO_MANY_ROWS`, `IMAGE_NOT_PAIRED`, `IMAGE_UNMATCHED`, `ROW_FAILED`, each with its doc block.
- `apps/web/src/App.tsx:43-51` `Section` (8 members, docstring :24-42 says "Eight values"), `:64-75` `Screen` (11 members, docstring :54 says "eleven screens"), `:88-100` `reachableBy`, `:102-140` `currentScreen`, the add-tile render branch at `:425-430`, and the admin door block at `:547-574` whose comment (:551-555) already anticipates a further entry. Import goes in the alphabetical block at `:9-17`.
- `apps/web/src/App.module.css` -- `.bulkUpload`, outlined exactly like `.addTile`: transparent background, `--color-primary` text and hairline border. **Never an accent fill** — `styling-wiring.test.ts:939` asserts this file holds zero `var(--color-accent)`.
- `apps/web/src/components/AppShell.tsx` -- wraps the screen; the screen renders **no `<main>`** of its own (`app-shell.test.tsx:61`).
- `apps/web/src/styles/tokens.css:24,26,30` -- `--color-primary` (navy, created), `--color-accent` (orange, flagged), `--color-destructive` (red, failed). There is no warning/success token and **none may be added** — `tokens.test.ts:115` asserts exactly eleven colours.

**Tests that fail unless they are extended**
- `apps/api/tests/test_admin_authorization.py:539` -- the route table is a literal 12-item list and the count is in the test name; `POST /admin/tiles/bulk` makes it **thirteen**, and the comment's story list gains this story. `:587` `test_the_lookup_segment_resolves_to_the_lookup_handler` -- extend the same registration-order claim to the `bulk` literal segment.
- `apps/api/tests/test_no_registration.py:238` -- compares the **set of paths**; `/admin/tiles/bulk` is a new path and must join the literal set.
- `apps/web/src/__tests__/error-code-parity.test.ts` -- the `PYTHON` map (~:140-176) gains the five new codes, `:199` requires each to be exported from `client.ts`, `:226` requires each Python constant to appear in the map. The `BOUNDS` table (ends :455) gains `MAX_BULK_ROWS`.
- `apps/web/src/__tests__/styling-wiring.test.ts:930` -- the admin-door list gains `'.bulkUpload'`. `:251` -- the rejection-colour matrix gains an entry for this screen. A new per-screen `describe` must assert: exactly one accent-**filled** control (the submit), and the accent's only other appearance is the flagged row indicator, citing DESIGN.md:221.
- `apps/web/src/__tests__/no-raw-values.test.ts:273` -- every `var(--x)` the new stylesheet writes must already exist in `tokens.css`.
- `apps/api/tests/test_source_guards.py:237,339,365` -- no SQL assembled from a value, no second module naming the audit table, nothing mutating it.
- `apps/api/tests/test_add_tile.py:47` -- the fixture vocabulary to reuse: `needs_model`, `a_tile_photograph`, `jpeg_bytes`, `stored_objects`, `count`, `sign_in`, `administrator`. `conftest.py` supplies `conn`, `client`, `make_user`, `audit_rows`, `storage_root`, `object_store`. `:213` explains why a test batch stays small — sixteen forward passes per image.
- `apps/api/tests/test_edited_tile_searchable.py` -- the pattern for "in the index now", asserted through `find_candidates` rather than a row count.
- `apps/web/src/__tests__/add-tile.test.tsx:579` -- `it('has exactly the controls it is meant to have')`; the new screen adopts the same control-count discipline.

**Read-only evidence**
- `_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md:144-149` -- `components.upload-report-row` tokens: `success-indicator: {colors.primary}`, `failure-indicator: {colors.destructive}`, `flagged-indicator: {colors.accent}`. `:221` -- "the only place all three brand colors appear as status indicators together". `:214` -- the flagged-activity-row precedent for orange-as-signal. `:215` -- Phosphor outline icons, 20-24px.
- `EXPERIENCE.md:37` (surface), `:73` (scrollable per-row list, not a pass/fail summary), `:94` ("Per-row status updates as they complete, not a single spinner until the whole batch finishes"), `:109-113` (accessibility floor: 44px targets, visible focus, never colour-only), `:103` (banned patterns).
- `scripts/ingest/ingest/__init__.py` -- a docstring-only skeleton ending "not implemented. Ingestion arrives with Epic 2." **It stays that way**; the spine (:26) scopes it to pre-launch Phase 0 under operator credentials, explicitly not this endpoint.
- `apps/api/pyproject.toml` -- no `openpyxl`, `pandas` or `xlrd`, and none is added. `csv` is stdlib.
- `shared/vision/shared_vision/pipeline.py:269` -- the only lock is over *session creation*; AD-16's inference serialization is Epic 3's. Sequential row processing here is this story's version of the same argument.

## Tasks & Acceptance

**Execution:**
- `shared/schema/shared_schema/tile.py` -- add `MAX_BULK_ROWS = 100` and `face_number(code) -> str | None` with the four ported patterns and their "first match wins, `None` rather than a guess" comment -- the trailing number is a display hint the Code alone yields, and the rule belongs beside `clean_code`, not in a route.
- `shared/schema/shared_schema/ts/tile.ts` -- mirror `MAX_BULK_ROWS` only -- the client enforces the row cap before uploading; it derives nothing.
- `shared/schema/tests/test_tile.py` -- test `face_number` against the five real naming conventions from `poc/tests/test_catalog.py`, including the dash-delimited name that must return `None`, and test the `MAX_BULK_ROWS` bound exists -- these patterns were verified against the real source tree and must not regress.
- `apps/api/api/catalogue.py` -- extend `_INSERT_TILE` with `face_number` (`add_tile` passes `None`); split `_accept` into `_accept_bytes` + the upload wrapper; add the five envelope codes `INVALID_MANIFEST`, `TOO_MANY_ROWS`, `IMAGE_NOT_PAIRED`, `IMAGE_UNMATCHED`, `ROW_FAILED` with their message constants; add the manifest reader (`csv.DictReader` over `utf-8-sig`-decoded bytes, required columns `file` and `code` and `size`, optional `category`, extra columns ignored, header match case- and whitespace-insensitive); add the upload spool; add `POST /admin/tiles/bulk` returning a `StreamingResponse` of NDJSON -- and rewrite the module docstring's route count and its "not here, deliberately" list, which names this story as absent.
- `apps/api/tests/test_bulk_upload.py` -- new; every row of the I/O matrix through the real route: N created, the three flag conditions singly and together, each failure classification, both duplicate-Code cases, shared Size/Category, an unpaired row, an unmatched upload, an unexpected row failure, and every pre-stream refusal proved to emit a real envelope with **no** stream and nothing written.
- `apps/api/tests/test_bulk_uploaded_tiles_searchable.py` -- new; after the stream closes, a perturbed copy of a created row's image returns that Tile from `find_candidates`, with no re-index step run, and a failed row's Code is absent from the catalogue entirely.
- `apps/api/tests/test_catalogue_audit.py` -- extend: a batch of N with one failure writes exactly N-1 `catalogue_tile_added` entries with the same `details` shape the single add writes, each carrying actor, timestamp and source IP, and none for the failed row.
- `apps/api/tests/test_catalogue_authorization.py` -- extend with the staff and signed-out refusals on `POST /admin/tiles/bulk`, each asserting no tile, image, embedding, object or audit entry was written.
- `apps/api/tests/test_admin_authorization.py` -- add `f"POST {BULK_UPLOAD}"`, rename the test to `thirteen`, extend its comment, and extend the lookup-segment ordering test to the `bulk` literal -- the number in the name may never drift from the list.
- `apps/api/tests/test_no_registration.py` -- add `/admin/tiles/bulk` to the path set.
- `apps/api/tests/test_source_guards.py` -- add a guard asserting the bulk handler reaches `shared_vision` only through `_accept_bytes`/`_prepare` -- "no shortcut for bulk" is the story's central invariant and it should fail loudly, not silently.
- `apps/web/src/api/client.ts` -- add `apiStream` beside `apiRequest`, sharing `ApiRequestError`, the 401 hook and the envelope parse, reading `response.body` line by line with a `response.text()` fallback and an **idle** abort timer; export the five new codes with doc blocks -- a streaming report cannot come through a function that awaits the whole body.
- `apps/web/src/screens/BulkUploadScreen.tsx` -- new; sheet picker, image picker, one accent-filled submit, client-side refusals for a missing sheet, missing images, more than `MAX_BULK_ROWS` images and an oversized image; a scrollable `<ol>` report whose rows stream in, each carrying an outline Phosphor icon **and a word** plus the file name, Code and message or flags; one `role="status"` progress line and a closing summary; the server's own sentence on a pre-stream refusal -- this is the surface FR-17 names and the report is the deliverable, not the spinner.
- `apps/web/src/screens/BulkUploadScreen.module.css` -- new; `AddTileScreen.module.css`'s flat single-class recipe, tokens only; `.created` uses `--color-primary`, `.failed` `--color-destructive`, `.flagged` `--color-accent`, per DESIGN.md:144-149 -- and the accent appears nowhere else but the submit fill.
- `apps/web/src/App.tsx` + `App.module.css` -- add the `bulk-upload` `Section` and `Screen`, its `reachableBy` admin arm, its `currentScreen` branch, its render branch inside `AppShell`, the outlined `.bulkUpload` door in the admin block, and correct the two docstring counts -- a screen with no door is unreachable, and the counts are load-bearing prose.
- `apps/web/src/__tests__/bulk-upload.test.tsx` -- new; a stubbed NDJSON stream paints rows one at a time in arrival order, each outcome gets its documented colour **and word**, progress is announced, the summary closes it, a pre-stream envelope renders the server's sentence with no report list, the client-side refusals ask nothing, and the screen has exactly the controls it is meant to have.
- `apps/web/src/__tests__/styling-wiring.test.ts` + `error-code-parity.test.ts` -- extend both as the Code Map itemises -- these are the suites that fail by design when a screen, a route or a code is added.

**Acceptance Criteria:**
- Given an authenticated Administrator and a manifest of N valid rows with their images, when the batch is submitted, then N Tiles exist, each with its Reference Image, its full set of embeddings and its stored source and derivative objects, and each is returned as a Candidate for a Scan submitted afterwards in the same session with no manual re-index step.
- Given one image submitted twice — once through `POST /admin/tiles` and once as a row of a bulk batch — when both are processed, then the stored source bytes, the stored derivative bytes and the resulting embeddings are identical, the bulk handler having reached `shared/vision` only through the single-add path's own helpers; and `shared/vision` itself is unchanged, so no re-index and no eval run is owed.
- Given a batch mixing valid rows with a zero-byte file, an unreadable file, a duplicate Code and a row naming an image that was not uploaded, when it is submitted, then each failure is reported on its own row with its own code and sentence, nothing is written for any of them, and every valid row in the same batch is still created.
- Given a row with no recoverable Category and a row whose Code yields no trailing number, when they are processed, then both are created — the first against the `UNKNOWN` category, the second with `face_number` NULL — and both are reported as flagged for follow-up rather than as errors.
- Given two rows sharing a Size and a Category but carrying different Codes, when they are processed, then both become distinct Tiles sharing one `tile_size` and one `tile_category` row, with no merge, no deduplication and no conflict reported.
- Given a successful batch, when it commits, then there is exactly one `catalogue_tile_added` entry per created row, written inside that row's own transaction with actor, timestamp and source IP, and no entry for any failed row; and no update or delete reaches the audit log.
- Given any non-Administrator or signed-out caller, when they call the bulk route, then the server refuses with `403` or `401` regardless of what the UI renders, and nothing is written to the database or to storage.
- Given a manifest that is missing, unparseable, empty or over the row cap, or a server with no model artifact or a stale generation stamp, when the request is made, then the response is a single `{"error": {...}}` envelope under a 4xx or 5xx status with no stream started and nothing written.
- Given the Bulk Upload screen and a running batch, when rows complete, then each appears as it completes rather than after the batch ends, carries the documented navy/red/orange indicator together with a word, progress is announced to a screen reader, and a summary closes the report.
- Given the Bulk Upload screen, when it is added, then it renders no `<main>` of its own, has exactly one accent-filled control, is reachable only by an Administrator through an outlined door, every interactive element is keyboard-reachable with a visible focus state and a 44px target, and no raw colour or dimension literal appears outside the token layer.
- Given `make lint` and `make test`, when run from a clean tree, then both pass, with the catalogue and bulk tests exercised (not skipped) when the model artifact is present.

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 1, medium 5, low 8)
- defer: 3: (high 0, medium 1, low 2)
- reject: 21: (high 0, medium 0, low 21)
- addressed_findings:
  - `[high]` `[patch]` No server-side cap on the number of uploaded image parts — `MAX_BULK_ROWS` bounded manifest rows only, so a one-row manifest with N parts spooled all N, ceilinged only by Starlette's `max_files=1000` at `MAX_IMAGE_BYTES` each, while the constant's own docstring claimed it bounded the spool. `bulk_upload` now refuses `TOO_MANY_ROWS` when either count exceeds the cap, before `_spool` runs; the docstring and the two comments that said the sides count different things were corrected, and three tests pin it.
  - `[medium]` `[patch]` `apiStream` never cancelled a body it abandoned: an early exit released the reader lock and cleared the idle timer without `reader.cancel()` or `controller.abort()`, leaving the server streaming a batch nobody read with its own timeout disarmed. Both are now called on any exit that is not the end of the stream.
  - `[medium]` `[patch]` The stream's idle clock was armed before `fetch`, putting the whole upload phase under a bound no chunk could restart, and the no-streams fallback restarted it only *after* `await response.text()`, turning the idle bound into a total one. The clock now restarts when the response headers arrive and is cleared before the text fallback; six fake-timer tests drive both directions.
  - `[medium]` `[patch]` Nothing verified that a `401` on the bulk stream reached `onUnauthorized` — every 401 test in the suite drove `apiRequest`, and the bulk screen's refusal cases were all 422. A test now asserts the shell drops to the login screen with the session-ended notice.
  - `[medium]` `[patch]` `_manifest_rows` did not guard `csv.Error`, so a cell past the field-size limit became a 500 rather than the documented `invalid_manifest` 422. The header read and the row iteration are both guarded and tested.
  - `[medium]` `[patch]` A failure raised outside a row — a pool timeout, say — escaped after the response had started, giving the client a 200 with a truncated body: no row, no summary, no error. `_bulk_stream` now guards its body, reports the failure as a final `row_failed` line and still closes with a summary (`GeneratorExit` passes through, since a client disconnect is not a batch failure); the screen says the report stopped early instead of blanking its progress line.
  - `[low]` `[patch]` Pairing was exact on the base name, so a sheet exported as `IMG_1.JPG` against an upload named `img_1.jpg` failed the row *and* reported the image unmatched. `_pairing_key` now folds both sides; a genuine case-only collision still refuses the row. Tested, with a path-qualified `file` cell alongside.
  - `[low]` `[patch]` The report line's `row` field disagreed across the two languages — the server always sent a number for an unmatched upload while the TypeScript contract documented `null` and its null branch was dead — and the screen parsed the field and never rendered it. Unmatched-upload and batch-stopped lines now carry `null`, and every line that has a number renders it.
  - `[low]` `[patch]` `_spool` silently dropped a part with no declared filename, so it could not even surface as `image_unmatched` — contradicting the stated reason that code exists. A part carrying bytes but no usable name is now reported; a genuinely empty picker part stays dropped.
  - `[low]` `[patch]` `deliver()` wrapped the caller's `onLine` callback in the same `try` as `JSON.parse`, relabelling any callback failure as a server protocol fault. The `try` is narrowed to the parse.
  - `[low]` `[patch]` Both file pickers stayed enabled while a batch streamed, so choosing a different sheet mid-run cleared the report and refilled it from the running stream; and the screen set state after unmount with the stream still running. Both pickers are now disabled while running, an `alive` ref guards every state write, and an `AbortController` stops the stream on unmount.
  - `[low]` `[patch]` The report `<ol>` carries `list-style: none`, and its comment claimed list semantics survived that — which Safari/VoiceOver strips. `role="list"` added and the comment corrected.
  - `[low]` `[patch]` Two comments claimed more than the code does, both because Starlette receives the whole body before the handler runs: the byte ceiling saves the second copy and everything downstream, not the transfer, and the row cap is checked before anything is spooled rather than before an image is read. Both reworded, and the test renamed to what it proves.
  - `[low]` `[patch]` Test gaps closed: a manifest over `MAX_MANIFEST_BYTES`, a UTF-8 BOM manifest (argued at length in `_manifest_rows` and never exercised), and the client-disconnect path `_bulk_stream`'s `finally` exists for — driven against the generator directly, one line consumed, closed, spool asserted gone.

### 2026-09-22 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 0, medium 3, low 13)
- defer: 0
- reject: 14: (high 0, medium 0, low 14)
- addressed_findings:
  - `[medium]` `[patch]` A pre-stream refusal marked no control. The matrix asks for the server's sentence "next to the sheet field", and `client.ts`'s own doc blocks for `INVALID_MANIFEST` and `TOO_MANY_ROWS` both said "Marks the **sheet** control" — while the screen sent every failure through `refuse(message, null)`, the belongs-to-neither slot. `fieldFor` added, `AddTileScreen`'s exactly: the two sheet refusals mark the sheet picker, and `matching_unavailable`, `pipeline_stamp_mismatch` and `administrator_required` still mark nothing, because nothing the Administrator chose is at fault for those. Focus is deferred until the run ends, since `focus()` on a control still `disabled` by the batch does nothing at all.
  - `[medium]` `[patch]` `asRow` ran *inside* the `setRows` updater, so the protocol refusal it exists to raise would throw during React's render rather than at the call site — past the screen's `catch`, past `apiStream`'s cancellation of the body, and into the app as an unhandled render failure. The narrowing now happens before the dispatch, with the arrival position on a per-batch local rather than read off the painted list.
  - `[medium]` `[patch]` `edit_tile` never re-derived `face_number`. This story is the first writer of that column, so a Tile the bulk path created as `RP.CMA.0008DJ.SM.0T` (hint `8`) and that was then renamed went on reporting `8` for a Code it no longer carried. `_UPDATE_TILE` writes the column, re-derived when the request sends a Code and written back untouched when it does not — the same "absent means unchanged" rule every other column there follows. Two tests.
  - `[low]` `[patch]` A batch the server reported as stopped early still closed with a summary — by design, since the status is committed at the first byte — and the screen read that summary as a clean finish, printing "Finished." above a row saying the upload stopped. The batch-stopped line now drives the same progress sentence a dropped connection does.
  - `[low]` `[patch]` `_pairing_key` folded `/` only, so a sheet maintained on Windows (`45X90\POLISH\a.jpg`) paired with nothing: the row failed *and* its image reported unmatched — the two-lines-for-one-invisible-difference the function's own docstring exists to prevent. Both separators are folded now. Tested.
  - `[low]` `[patch]` A `category` cell that literally spells `UNKNOWN` was filed under the sentinel and reported as a clean success, because the flag read the cell rather than the resolved Category. It reads the resolved value now: a blank cell and a cell spelling the sentinel are the same fact.
  - `[low]` `[patch]` `AddTileScreen`'s docstring still read "No list, no edit, no removal, **no bulk upload.** Stories 2.2 to 2.5." The Code Map named that sentence as part of this change and it was never made; it now denies nothing that ships.
  - `[low]` `[patch]` `_row_line`'s docstring claimed the row number is what an Administrator uses to find "the offending line in the sheet". With the header uncounted and blank lines skipped it is an ordinal among data rows, not a physical line. Reworded to what it is.
  - `[low]` `[patch]` A stale in-body comment read "No `needs_model`" directly beneath the `@needs_model` decorator, teaching the next reader the opposite of the pre-flight rule.
  - `[low]` `[patch]` A dead `explode()` helper in `test_an_abandoned_batch_still_removes_its_spool` described an assertion the test does not make.
  - `[low]` `[patch]` Test gap: `apiStream`'s line buffering — the one thing that function exists for — was never driven across a chunk boundary. Every existing stub handed the reader exactly one whole line per chunk, which is the one thing a network never promises. Two tests: a line split mid-object across three chunks, and a multi-byte character split across two.
  - `[low]` `[patch]` Test gap: the `csv.Error` guard on the *header* read. Only the row-iteration guard was exercised, so deleting the header one — which `_manifest_rows` argues at length for — would have turned an unreadable first line into a `500`.
  - `[low]` `[patch]` Test gap: a flag slug this build has no sentence for. The fallthrough is documented as deliberate ("a row silently missing one reads as a clean success") and nothing drove it.
  - `[low]` `[patch]` Test gap: two manifest rows naming one upload — two Tiles, no merge, no orphan line — which AD-18 decides and nothing asserted; and the `REFERENCE_MAX_PIXELS` half of the oversized row, which the matrix names and only the byte ceiling was driving.
  - `[low]` `[patch]` `test_the_rows_arrive_as_they_complete_rather_than_at_the_end` claimed in its comment to tell a body written line by line from one written whole. `TestClient` may produce the whole body before the first read returns, so it cannot: it holds the stream's shape, and `bulk-upload.test.tsx` holds its timing. Both comments now say which half they own.
  - `[low]` `[patch]` `test_the_report_uses_the_domains_own_words` checked one of the three retired words. It checks all three, with `face` checked as free prose so the permitted `face_number` survivor still passes.

### 2026-09-22 — Follow-up review pass

- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 2, low 5)
- defer: 1: (high 0, medium 0, low 1)
- reject: 19: (high 0, medium 0, low 19)
- addressed_findings:
  - `[medium]` `[patch]` Two tests drove the route past the model pre-flight and asserted `200` without `@needs_model` — `test_a_picker_with_nothing_chosen_counts_as_nothing` and `test_a_part_with_bytes_and_no_name_is_reported_rather_than_dropped`. `bulk_upload` pre-flights `shared_vision.MODEL_PATH` before the stream opens, so on a machine without the ONNX artifact both would have received `503 matching_unavailable` and **failed** where every sibling in the file skips. Both marked, with the reason stated as the file's other artifact-only test already states it.
  - `[medium]` `[patch]` `test_a_batch_that_stops_still_closes_its_report` asserted `created: 2` against one visible row and argued at length in a comment that "row 2 was written — the failure here is in *reporting* it" — then never looked at the database. That claim is the entire reason the summary is allowed to disagree with the list, and a regression that rolled row 2 back would have left the summary lying and the test green. The test now takes `conn` and asserts both Tiles are really in the catalogue, by Code.
  - `[low]` `[patch]` `_spool` took the base name with `Path(upload.filename).name` while `_pairing_key` folds `\` as well as `/`. A part declared `C:\shots\a.jpg` therefore paired correctly on `a.jpg` but was quoted back on an `image_unmatched` line — and sorted — as the whole Windows path: two spellings of one name in one report, the class of difference `_pairing_key` exists to erase. Folded before the base name is taken.
  - `[low]` `[patch]` `spool.cleanup()` sat unguarded in `_bulk_stream`'s `finally`, which runs *after* the summary has been written. An `OSError` there would have escaped as a torn-down response for the one reader who had already received every line of the report. Guarded and logged; a directory that will not go away is an operator's problem, not the client's.
  - `[low]` `[patch]` `_EDITABLE_FIELDS`' docstring still read "`face_number` is absent because nothing writes it". The same change made `edit_tile` write it, so the comment taught the next reader the opposite of the rule one function below. Corrected to the real reason it is absent — it is derived from the Code rather than sent, and the Code's own entry already records the move.
  - `[low]` `[patch]` The images hint named the image cap ("Up to 100 at a time") and the sheet hint named no bound at all, so a 150-row manifest uploaded in full before `too_many_rows` refused it. The screen cannot parse the manifest — the intent forbids it — so the hint is the only lever there is, and it now names the row cap and says the sheet is read on the server.
  - `[low]` `[patch]` The unmount test's comment claimed "React reports a set-after-unmount through `console.error`, and it is the only signal there is". React 19 removed that warning and a `setState` on a detached fiber is a silent no-op, so the assertion could not fail whether the `alive` guard was present or absent. The comment now states what the test can and cannot see rather than a premise this stack disproves.

## Design Notes

**Why NDJSON over one request, and not a job table.** EXPERIENCE.md:94 makes "rows as they complete" a requirement, and the product has no job table, no queue, no background worker and no polling endpoint — introducing all four for one screen is a bigger change than the story. A streamed body keeps the existing one-request shape, keeps the connection busy so no idle timeout fires on a batch that runs for minutes, and needs no state to garbage-collect. The cost is that the HTTP status is committed at the first byte, which is why every refusable condition is checked before the generator yields anything.

**Why the handler spools the uploads.** Under a `StreamingResponse` the endpoint function returns before the body runs, and FastAPI's dependency exit stack — which closes the multipart form — unwinds at that return. Reading an `UploadFile` from inside the generator is therefore reading a file that may already be closed. Copying each part to a handler-owned `TemporaryDirectory` first, with the same `MAX_IMAGE_BYTES` ceiling enforced during the copy, makes the lifetime explicit and keeps memory at one image at a time rather than the whole batch.

**Why one line per row and a summary line.** Two shapes, discriminated by `kind`:

```json
{"kind":"row","row":1,"file":"RP.CMA.0008DJ.SM.0T.jpg","code":"RP.CMA.0008DJ.SM.0T","status":"created","tile_id":"…","flags":[],"error":null}
{"kind":"row","row":2,"file":"broken.jpg","code":"1Jk","status":"failed","tile_id":null,"flags":[],"error":{"code":"unreadable_image","message":"…"}}
{"kind":"summary","created":1,"flagged":0,"failed":1}
```

`status` is exactly the three outcomes DESIGN.md:144-149 paints, so the screen maps one field to one token with nothing to infer. A `flagged` row *is* created and carries a `tile_id`; the flag is follow-up, not failure. `error` reuses the envelope's `{code, message}` shape so a per-row failure reads the same as any other refusal.

**Why no new audit action.** A Tile added through the bulk path is a Tile added: same actor, same `details`, same consequence for the catalogue. A second action naming the same fact is drift — the argument Story 2.3 used to refuse a second `tile_not_found`. The provenance that is genuinely lost (which batch a Tile came from) is not something FR-20 asks for, and inventing a `bulk` flag inside `details` would fork a shape three tests pin.

**Why CSV and not `.xlsx`.** Every spreadsheet tool exports CSV, `csv` is stdlib, and AGENTS.md asks for any new dependency to be flagged before it is added. The refusal sentence for a non-CSV manifest names the fix ("Export the sheet as CSV and upload that.") rather than describing the problem. If `.xlsx` is later required it is an additive change behind the same route and the same report.

**Why the row cap is 100.** The real source tree is 381 files across 76 category folders, and 96% of files sit in folders of 2-26 siblings — so 100 covers any real range several times over while bounding the spool, the report and the time one request can hold a pooled connection.

## Verification

**Commands:**
- `make lint` -- expected: ruff check, ruff format --check, oxlint and `tsc --noEmit` all clean.
- `make test` -- expected: the whole workspace green, with `test_bulk_upload.py` and `test_bulk_uploaded_tiles_searchable.py` **run** rather than skipped (the ONNX artifact is present at `shared/vision/shared_vision/models/model.onnx`).
- `uv run --project apps/api pytest apps/api/tests/test_bulk_upload.py apps/api/tests/test_bulk_uploaded_tiles_searchable.py apps/api/tests/test_catalogue_audit.py apps/api/tests/test_catalogue_authorization.py apps/api/tests/test_admin_authorization.py apps/api/tests/test_no_registration.py apps/api/tests/test_source_guards.py -q` -- expected: green, and no test reporting `skipped` for a missing model.
- `uv run --project shared/schema pytest shared/schema/tests/test_tile.py -q` -- expected: green, including the five naming conventions.
- `npm --prefix apps/web test -- --run bulk-upload add-tile styling-wiring error-code-parity no-raw-values tokens app-shell auth-gating` -- expected: green.

**Manual checks (if no CLI):**
- `git status --porcelain` is empty of stray artifacts after a run; no temporary spool directory survives a completed or abandoned batch; and no object is left under `OBJECT_STORAGE_ROOT` for a row the report called `failed`.

## Auto Run Result

Status: done

**Summary.** A follow-up review pass over the already-implemented Story 2.4 (bulk upload). No code was re-derived: the four review layers surfaced 27 findings, of which none reached `intent_gap` or `bad_spec`. Seven were patched, one deferred, nineteen rejected. The patches are two real verification gaps, one report-consistency defect, one response-teardown hole, one stale comment and one UI hint gap.

**Files changed in this pass**

- `apps/api/api/catalogue.py` -- `_spool` folds `\` before taking the base name (so the reported name matches the pairing key); `_bulk_stream`'s `finally` guards `spool.cleanup()`; `_EDITABLE_FIELDS`' docstring corrected where it claimed nothing writes `face_number`.
- `apps/api/tests/test_bulk_upload.py` -- `@needs_model` added to the two tests that drive the route past the artifact pre-flight; the batch-stopped test now asserts against the database the claim its own comment makes.
- `apps/web/src/screens/BulkUploadScreen.tsx` -- the sheet hint names the row cap and says the sheet is read on the server.
- `apps/web/src/__tests__/bulk-upload.test.tsx` -- the unmount test's false React-19 premise replaced with what the test can and cannot observe.
- `_bmad-output/implementation-artifacts/spec-2-4-bulk-upload.md` -- triage log entry, one deferred item, this section.

**Review findings breakdown**

- Patches applied: 7 (high 0, medium 2, low 5).
- Deferred: 1 -- `EditTileScreen`'s marker-less reference-image gallery has no `role="list"`, the same accessibility rule this story fixed on its own report list. Pre-existing since Story 2.2, recorded in frontmatter `deferred`.
- Rejected: 19, all low. The substantial ones and why: `add_tile` writing `face_number` NULL while bulk and edit derive it (the intent's Never clause mandates `None` there, and nothing reads the column -- it may not be keyed, grouped or matched); one pooled connection held for the whole batch (the Code Map mandates opening it inside the generator, and the scope is a handful of internal Administrators); no end-to-end test that the server flushes per row (a real limit, documented on both halves already, and not observable through `TestClient`); the `UniqueViolation` branch in `_bulk_row` being unreachable within one batch (defence in depth, mirroring `add_tile`); `BATCH_STOPPED_MESSAGE`'s wording (literally true, and a resend of an already-created Code is reported as `code_already_exists` rather than doing harm); no Stop control while a batch runs (documented choice -- each row is its own transaction, and unmount aborts the stream); the second `manifest` part being dropped (the screen sends one); `IMAGE_NOT_PAIRED`/`IMAGE_UNMATCHED` exported without a consumer (the parity contract requires the export; the screen renders the server's sentence rather than switching on the code). Orchestration-owned artifacts -- `sprint-status.yaml` and the deferred-work ledger -- were not touched.

**Follow-up review recommendation:** `true`. Patched this pass: high 0, medium 2, low 5. Score = 3x2 + 1x5 = 11, which is 5 or more.

**Verification performed**

- `make lint` -- green (ruff check, ruff format --check, oxlint, `tsc --noEmit`).
- `uv run --project apps/api pytest apps/api/tests/test_bulk_upload.py -q` -- 57 passed, 0 skipped.
- `uv run --project apps/api pytest` over the rest of the API suite (catalogue, audit, authorization, source guards, add/edit tile, and every remaining file) -- exit 0.
- `uv run --project shared/schema pytest shared/schema/tests/test_tile.py -q` -- exit 0.
- `npm --prefix apps/web test -- --run` -- 24 files, 1398 tests passed.
- `make test` was not used as one command: the full workspace suite runs past this session's 10-minute command ceiling, so it was run as the equivalent partitions above, together covering every test file in the workspace.

**Residual risks**

- The two medium patches were both verification gaps, not behaviour changes, so the shipped behaviour of the route is unchanged from the previous pass except for the spooled file's reported name and the guarded cleanup.
- `shared/vision/` is still untouched by this story, so no re-index and no eval run is owed.
- The four deferred items stand, the newest being an accessibility gap on Story 2.2's screen rather than anything in this route.
