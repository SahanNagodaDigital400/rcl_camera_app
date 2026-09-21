---
title: 'Story 2.2 — Edit Tile'
type: 'feature'
created: '2026-09-21'
status: 'done'
baseline_revision: 'c789ef378bc147a1d97feab2a8be933dc3a0c532'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-1-add-product.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A second successful Find silently discards the Administrator's unsaved edits, removal
      marks and chosen files.
    evidence: |-
      `handleLookup` routes a hit straight through `adopt()`, which resets `code`, `size`,
      `category`, `marked`, `files` and the file input with no confirmation. The suite pins
      only the miss case (`clears a loaded tile when a later lookup misses`). The epic's UX
      obligation is "never drop an in-progress catalogue edit silently", and this screen
      confirms every other destructive step. Not patched here because the fix is a third
      dialog state and a dirty-tracking rule, which is a screen-pattern decision rather than
      an edit.
    location: >-
      apps/web/src/screens/EditTileScreen.tsx handleLookup
    severity: medium
  - summary: >-
      Nothing bounds a Tile's total Reference Images across edits, and the same asset can be
      stored twice with sixteen more vectors behind it.
    evidence: |-
      `MAX_IMAGES_PER_REQUEST` bounds one request, and the screen's own hint invites
      repetition ("Save, then add the rest"), so a Tile grows without limit over successive
      edits. `reference_image` carries `sha256` but has no unique index over
      `(tile_id, sha256)`, so re-saving an asset already on the Tile stores a second copy,
      a second derivative and sixteen more `reference_embedding` rows that all score the
      same Tile. Story 2.1 was careful to bound the add at 1-8; the cumulative bound was
      never decided.
    location: >-
      apps/api/api/catalogue.py edit_tile
    severity: low
  - summary: >-
      `_SELECT_TILE_IMAGES` is documented as chronological but sorts effectively by uuid, and
      can disagree with the order the add response showed.
    evidence: |-
      `reference_image.created_at` defaults to `now()`, which in PostgreSQL is the
      *transaction* timestamp, and `add_tile` inserts every image of one request in one
      transaction. Every image of a multi-image add therefore ties on `created_at` and the
      tiebreak is `gen_random_uuid()`. The order is stable, which is what the screen needs,
      but it is arbitrary rather than chronological and differs from `add_tile`'s own
      response, which is built in upload order. `clock_timestamp()` as the default, or an
      explicit ordinal column, would make the documented intent true.
    location: >-
      infra/migrations/20260921T1500_create_catalogue.up.sql reference_image.created_at
    severity: low
  - summary: >-
      `GET /admin/tiles/lookup` writes no audit entry and has no throttle, on a route that
      confirms a Code one guess at a time.
    evidence: |-
      The handler's docstring declines to record a read because "an entry per lookup would
      bury the entries that matter", which is the argument `read_reference_image` makes and
      is reasonable on its own. It does not engage the other half: catalogue exfiltration
      through a compromised account is this product's stated primary commercial threat, and
      this is the first route that answers "does this exact Code exist" in one cheap request.
      `api/throttle.py` already exists. Either the trade-off belongs in the docstring or a
      coarse record or limit does.
    location: >-
      apps/api/api/catalogue.py lookup_tile
    severity: low
  - summary: >-
      A save that times out after the server has already committed leaves the screen holding
      removal marks and files it has in fact already sent.
    evidence: |-
      `save()`'s catch clears neither `marked` nor `files`, so a retry after an
      `UPLOAD_TIMEOUT_MS` abort re-sends ids the server has already deleted (`404
      image_not_found`) and re-uploads files it has already stored. Same shape as the add
      path's timeout-after-commit entry recorded against Story 2.1: there is no idempotency
      key and no server-side deadline matching the client's, so the screen cannot tell
      "timed out, the edit landed" from "timed out, nothing changed". Re-running the lookup
      on a timeout would recover the screen; an idempotency key would fix the class.
    location: >-
      apps/web/src/screens/EditTileScreen.tsx save
    severity: low
  - summary: >-
      `session-expiry.test.tsx` failed once again under a full `make test` run and passed on
      every run since - a second sighting of the flake recorded against Story 2.1.
    evidence: |-
      One `make test` invocation during this story failed at
      `src/__tests__/session-expiry.test.tsx:476` waiting for the second call of a failing
      revalidation; the same suite passed on the next three full runs. Story 2.1 recorded the
      same file failing at `:321` and passing on every rerun. The file is untouched by this
      story, and the only change to anything it imports is two added exported constants in
      `client.ts`. Two sightings at two different lines is a pattern rather than noise, and a
      test that fails under load and passes alone is a real defect in the test.
    location: >-
      apps/web/src/__tests__/session-expiry.test.tsx:476
    severity: low
  - summary: >-
      Two Administrators editing one Tile silently overwrite each other - the row lock
      serializes the writes but detects no staleness.
    evidence: |-
      `edit_tile` locks the Tile `FOR UPDATE`, which orders the two transactions but does not
      notice that the second one read its values before the first committed: the later save
      writes its own Code, Size and Category over the earlier one with no refusal and nothing
      on either screen. `updated_at` is already on the row and already returned by both the
      lookup and the save, so the material for an `If-Match` round-trip exists; what is
      missing is the contract for it - a new envelope code, the header or part that carries
      the stamp, and the screen's answer when it is stale. That is a concurrency contract for
      the catalogue rather than an edit, and it is not decidable from this story's intent,
      which is silent on simultaneous editors. Distinct from the already-recorded ledger item
      about a second Find discarding one Administrator's own unsaved work.
    location: >-
      apps/api/api/catalogue.py edit_tile
    severity: medium
  - summary: >-
      The audit entry for an edit records image counts only, so a hard-deleted Reference
      Image leaves no identifying trace anywhere.
    evidence: |-
      `details` carries `images_added` and `images_removed` as integers, and
      `_EDITABLE_FIELDS`' docstring argues image ids are "not something a reader of the log
      can do anything with". But removal here is a real `DELETE` plus a post-commit object
      delete - the row, its sixteen embeddings and both stored objects are gone - so the
      audit entry is the only remaining trace of what was destroyed, and it records none of
      it. FR-20/AD-4 attributability is weakest exactly where the action is irreversible.
      Deferred rather than patched because what the entry should carry (the id, the
      dimensions, the storage keys) changes what an Administrator reads in the log and is a
      log-contract decision, not an edit.
    location: >-
      apps/api/api/catalogue.py edit_tile audit details
    severity: medium
  - summary: >-
      `remove_image_ids` has no ceiling, unlike `images`, so one request can name an
      unbounded number of ids.
    evidence: |-
      `MAX_IMAGES_PER_REQUEST` bounds the uploads; nothing bounds the removal list. The
      per-id work is linear now that `_removals` is set-based, so this is no longer a
      quadratic burn, but an authenticated caller can still make the handler parse a hundred
      thousand UUIDs before answering `404`. A bound needs its own envelope code, a refusal
      sentence, rows in `error-code-parity.test.ts` in both directions and a mirror on the
      screen - the same shape as `too_many_images` - which is a contract addition rather
      than a patch.
    location: >-
      apps/api/api/catalogue.py edit_tile requested_removals
    severity: low
  - summary: >-
      A refusal stays painted on a field while the Administrator is correcting the very field
      it blames.
    evidence: |-
      `typed()` clears only `saved`, while `chooseFiles` and `toggleMarked` clear `error` as
      well. After a `409 code_already_exists`, typing a new Code leaves `aria-invalid="true"`
      and the stale sentence under the field until the next Save answers. `AddTileScreen` has
      the same asymmetry, so this is a copied screen pattern rather than something this story
      introduced - but the edit screen has five slots instead of four and the stale alert is
      now bound to a control the Administrator is actively fixing. Worth deciding once for
      both screens rather than diverging them.
    location: >-
      apps/web/src/screens/EditTileScreen.tsx typed
    severity: low
  - summary: >-
      Every edit re-resolves the Size through `ON CONFLICT DO UPDATE`, taking a write lock on
      the shared `tile_size` row even when the request sent no Size at all.
    evidence: |-
      `_SELECT_TILE_FOR_UPDATE` returns the Size *name* rather than its id, so the handler
      runs `_RESOLVE_SIZE` unconditionally inside the transaction and writes the row back to
      itself. That takes a row lock held until commit, so two edits of two unrelated Tiles
      that happen to share a Size serialize behind each other for the length of an upload —
      and a pure rename, which touches no Size, pays it too. The intent requires both to be
      "resolved through the same normalized create-if-missing lookup the add uses", and the
      add genuinely does need the row; the edit needs it only when a Size was actually sent.
      Not patched because the fix is a column added to the locked read and a branch on
      `new_size`, which changes what the transaction holds and wants its own concurrency test
      rather than an edit.
    location: >-
      apps/api/api/catalogue.py edit_tile
    severity: low
  - summary: >-
      The edit form's fields, Remove checkboxes and file input stay live during an in-flight
      save, and `adopt()` discards whatever was changed there when it lands.
    evidence: |-
      Only the Save, Find and Back buttons carry `disabled={submitting || looking}`. Every
      input stays editable while `Saving…` is showing, and the successful response routes
      through `adopt()`, which resets `code`, `size`, `category`, `marked`, `files` and the
      file input — so a mark ticked or a character typed during the wait vanishes under
      "Saved." with nothing said. Same root as the already-recorded entry about a second Find
      discarding unsaved work: `adopt()` is unconditional. The fix is the dirty-tracking rule
      that entry is waiting on, applied to a second trigger, so it belongs with it rather
      than ahead of it.
    location: >-
      apps/web/src/screens/EditTileScreen.tsx
    severity: low
  - summary: >-
      A Reference Image whose stored derivative is missing renders as the browser's broken
      image glyph, beside a live Remove control and no explanation.
    evidence: |-
      The gallery's `<img>` has no `onError`, so a `404` from
      `GET /admin/tiles/{id}/images/{imageId}` — an object an operator deleted, or one a
      failed `_discard` left half-removed — shows as a broken icon with the alt text behind
      it. The Administrator is then asked to decide whether to remove an image they cannot
      see, on the one screen whose whole justification is that "staff can verify a picture
      instantly". `AddTileScreen` renders no images at all, so there is no established
      treatment to copy: a placeholder, its sentence and whether Remove stays enabled are a
      screen-pattern decision.
    location: >-
      apps/web/src/screens/EditTileScreen.tsx gallery
    severity: low
  - summary: >-
      `edit-user.test.tsx` failed once under a full `make test` run and passed alone and on
      the next full run - a third sighting of the web suite's under-load flake, in a new file.
    evidence: |-
      One `make test` invocation during this pass failed at
      `apps/web/src/__tests__/edit-user.test.tsx:506` asserting focus had returned to the
      email box; the same file passed alone (44/44) immediately afterwards and the next full
      `make test` was green at 1277/1277. Two prior sightings are already recorded against
      `session-expiry.test.tsx` at `:321` (Story 2.1) and `:476` (this story). Neither file is
      touched by this story. Three sightings across two files, all of them focus- or
      timing-dependent assertions that pass in isolation, is a suite-level defect rather than
      three separate flaky tests.
    location: >-
      apps/web/src/__tests__/edit-user.test.tsx:506
    severity: low
---

<intent-contract>

## Intent

**Problem:** A Tile can be added and never corrected. A mistyped Code, a Size or Category filed wrong, a reference image that turned out to be the wrong asset or too poor to retrieve — all of them are permanent today, and the only remedy is a second Tile under a second Code, which puts a wrong answer in the catalogue forever. There is also no way to reach a Tile at all once the add response has scrolled away.

**Approach:** One admin-only `PATCH /admin/tiles/{tile_id}` that changes a Tile's Code, Size and Category and adds or removes Reference Images in the same unit of work — new images through Story 2.1's intake/embed/derivative path verbatim, removed images hard-deleted so their embeddings cascade out of the index — plus a narrow exact-Code lookup and an Edit tile screen that reaches a Tile by its Code until Story 2.5's Catalogue list exists.

## Boundaries & Constraints

**Always:**
- Every new image byte goes through the **same** `shared_vision.intake_image` → `generate_views` → `embed_images` → `display_derivative` path the add uses, by calling `catalogue._accept` and `catalogue._prepare` — not a second copy of them (AD-1, AD-7, AD-13, AD-15, AD-17).
- Removal is **real removal**: `DELETE FROM reference_image` so `reference_embedding` cascades. No soft-delete flag, no query-time predicate, no orphaned embedding row.
- New embeddings are written into the **single active generation** resolved by `ensure_active_generation`, and the AD-14 stamp is verified before any image is embedded.
- **A Tile always keeps at least one Reference Image.** An edit whose net effect is zero images is refused; the Tile is otherwise a catalogue row no member of staff can verify (FR-7).
- Storage writes first, database second, and every object this request wrote is discarded if the transaction fails — `add_tile`'s ordering and `_discard`, reused. Objects belonging to *removed* images are deleted only **after** the commit, best-effort and logged: an orphaned object is recoverable, a row pointing at absent bytes is not.
- The Tile row is locked `FOR UPDATE` inside the transaction, and `updated_at` is set by hand — this schema has no BEFORE UPDATE trigger.
- The edit and its audit entry share one `with conn.transaction():`. A refused edit writes no entry and leaves no object behind.
- `require_administrator` on every new route; every new route lives under `/admin/`.
- Domain vocabulary only: `Tile`, `Code`, `Size`, `Category`, `Reference image`. `Product`, `Face` and `Design` appear nowhere as a type, column, class, label or sentence.
- Every new envelope code is exported from `apps/web/src/api/client.ts` with a row in `error-code-parity.test.ts`, in both directions.

**Block If:**
- Reusing `_accept`/`_prepare` turns out to be impossible without changing `shared/vision` — a change there invalidates the index and binds an eval run plus a re-index (CLAUDE.md), which is not this story's to take unattended.

**Never:**
- Do not re-embed an image that was not uploaded in this request. Changing a Code changes no pixels, and a rebuild of untouched embeddings is a re-index by another name.
- Do not implement Story 2.3's Tile removal, Story 2.4's bulk path, Story 2.5's catalogue **list or substring search**, Epic 3's scan endpoint, or any crop step. The lookup added here is an **exact** Code match returning one Tile and nothing else.
- Do not add a `size + category → code` map, do not deduplicate or group Tiles by `size + category`.
- Do not surface a similarity score, bar or derived word anywhere in the UI (AD-20).
- Do not add a presigned or direct-to-storage URL in either direction (AD-9), a vector database, an ORM, a router or a form library.
- Do not add a migration — the shipped schema already carries `tile.updated_at` and both cascades. Do not touch `shared/vision`.
- Do not enable the OpenAPI/docs routes, add CORS, or introduce middleware.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Rename a Code | Admin session; `PATCH /admin/tiles/{id}` with `code=RP.CMA.0002DJ.SM.0T` | `200` with the whole Tile; `tile.code` and `updated_at` moved; **no** embedding row touched; one `catalogue_tile_edited` entry whose `details.changed` is `{"code": {"from": …, "to": …}}` | No error expected |
| Renamed Code is live at once | Rename, then a vector query matching that Tile | The candidate carries the **new** Code with no re-index step | No error expected |
| Change Size and Category | `size=" 60x60 "`, `category="Astoria"` | `200`; both resolved through the same normalized create-if-missing lookup the add uses — one row each, never a near-duplicate | No error expected |
| Category blanked | `category=""` | `200`; resolves to the `UNKNOWN` sentinel, never dropped (AD-18) | No error expected |
| Add a Reference Image | `images` carries one new JPEG | `200`; one new `reference_image` row, 16 new `reference_embedding` rows in the active generation, source + derivative objects written | No error expected |
| Added image is findable at once | Add image Z to a Tile, then query with a perturbed copy of Z | That Tile is among the candidates with no re-index step run | No error expected |
| Remove a Reference Image | Tile has two images; `remove_image_ids` names one | `200`; that `reference_image` row is gone, its 16 embeddings are gone with it, and both its stored objects are deleted; the Tile's score for a perturbed copy of the removed image drops to its score from the remaining image alone | No error expected |
| Remove and add in one request | `remove_image_ids` names the only image, `images` carries a replacement | `200`; net one image; the old embeddings are gone and the new 16 are present | No error expected |
| Edit that changes nothing | Every field identical to what is stored, no images | `200` with the Tile; one entry whose `details.changed` is `{}` — the honest record of an accepted edit that moved nothing | No error expected |
| Removing the last image | `remove_image_ids` names every image and `images` is empty | `409` `last_reference_image`; nothing written, no audit entry | Transaction rolled back |
| Removing another Tile's image | An image id that belongs to a different Tile, or to none | `404` `image_not_found`; nothing written | Refusal names neither Tile |
| Unknown Tile | `PATCH /admin/tiles/{unknown uuid}` | `404` `tile_not_found`; nothing written, no object stored | Refused before any decode |
| Rename onto a taken Code | Another Tile already holds that Code | `409` `code_already_exists`; nothing written, every object this request wrote removed | `UniqueViolation` on `tile_code_key` is the decider; the pre-flight `SELECT` is only the fast path |
| Blank or overlong Code | `code=""` or > 200 chars | `422` `invalid_code` | Refusal names the field |
| Blank Size | `size=""` | `422` `invalid_size` | Refusal names the field |
| Zero-byte / corrupt / non-image bytes | A new image whose bytes are text, or 0 bytes | `422` `unreadable_image`; nothing stored, nothing removed, no partial edit | Transaction rolled back; objects written before the failure removed |
| Extension lies about content | A PNG named `.jpg`, an `.exe` renamed `.jpg` | Decided by content only: the PNG is accepted, the non-image is `422` `unreadable_image` | Never trust the extension or the client `content-type` |
| Oversized new image | File > 128MB, or decoded pixels > 400,000,000 | `413` `image_too_large`, refused before a full decode | Header-only pixel gate before decode |
| Too many new images | More than 8 files in one request | `422` `too_many_images` | Refusal names the limit |
| Model artifact absent, images sent | `shared/vision` model file not present | `503` `matching_unavailable`; message names the setup step; nothing written | Tests that need the model skip rather than fail |
| Model artifact absent, no images sent | Metadata-only edit | `200` — a rename embeds nothing, so it must not need the model | No error expected |
| Look up by Code | `GET /admin/tiles/lookup?code=RP.CMA.0001DJ.SM.0T` as admin | `200` with the whole Tile, its reference images included | `404` `tile_not_found` for a Code no Tile holds; blank Code is `422` `invalid_code` |
| Lookup is exact, never a search | `?code=RP.CMA` where `RP.CMA.0001DJ.SM.0T` exists | `404` `tile_not_found` — substring matching is Story 2.5's | No partial match, ever |
| Staff caller | Valid non-admin session, either new route | `403` `administrator_required`; nothing written to database or storage | Existing dependency |
| Signed-out caller | No session cookie | `401` `unauthorized` | Existing dependency |

</intent-contract>

## Code Map

**API — the module being extended**
- `apps/api/api/catalogue.py` -- the whole write path. Reuse, do not re-derive: `_refusal` (:~190), the envelope-code block (`INVALID_CODE` … `PIPELINE_STAMP_MISMATCH`), `_RESOLVE_SIZE`/`_RESOLVE_CATEGORY`, `_INSERT_REFERENCE_IMAGE`, `_INSERT_EMBEDDING`, `_SELECT_CODE`, `CODE_UNIQUE_INDEX = "tile_code_key"`, `_vector_literal`, `active_generation`/`ensure_active_generation`/`_verify_stamp`, `find_candidates`, `_Prepared`, `_source_key`/`_derivative_key`, `_read_upload`, `_accept`, `_prepare`, `_discard`, and `read_reference_image`. `add_tile` (:~620) is the shape to follow: cheap refusals → stamp → duplicate pre-flight → `_accept` all → `_prepare` all → `store.put` recording keys → one `conn.transaction()` → `audit.record` → `except BaseException: _discard(...); raise`.
- `apps/api/api/users.py:928` `_changed_fields`, `:961` `edit_user` -- the PATCH idiom to copy: `_EDITABLE_COLUMNS` named explicitly rather than derived from the request model, `{field: {from, to}}` compared between the locked read and the `UPDATE`'s own `RETURNING`, a `404` distinguished by a locking `SELECT ... FOR UPDATE` rather than by a zero-row update, `_user_not_found`'s error-factory shape.
- `apps/api/api/audit.py:230` `record(...)`, `:149` `source_ip` -- the only INSERT against the audit table. `catalogue.py` must never name `audit_log` (`tests/test_source_guards.py`).
- `apps/api/api/dependencies.py:193` `require_administrator`, `NO_STORE` -- authorization and the actor in one; declared, never a line in the handler.
- `apps/api/api/db.py` -- autocommit pool, `dict_row`, `get_connection`, `with conn.transaction():`. Handlers are `def`, never `async def`.
- `apps/api/api/storage.py` -- `ObjectStore.put/get/delete`, `ObjectNotFound`, `get_object_store`.
- `apps/api/api/main.py:186` -- `catalogue.router` is already included; **no registration change**. `STATUS_CODES` already maps 404/409/413/422.

**Contract**
- `shared/schema/shared_schema/tile.py` -- `clean_code`, `clean_size`, `clean_category`, `normalize_label`, `UNKNOWN_CATEGORY`, `MAX_IMAGES_PER_REQUEST`, `MAX_IMAGE_BYTES`, `Tile`, `ReferenceImage`. Already sufficient; do not widen it.
- `shared/schema/shared_schema/audit.py:130` -- `CATALOGUE_TILE_ADDED` is the last member; add `CATALOGUE_TILE_EDITED` after it.
- `shared/schema/shared_schema/ts/audit.ts:57,63,77` -- the union, `AUDIT_ACTIONS`, and the member list. Four places in total with the two tests below, or the suite fails.
- `shared/schema/tests/test_audit.py:133` `test_the_vocabulary_is_the_fourteen_actions_the_product_writes` -- the count is in the name; rename to `fifteen` and add the value at `:151`.
- `apps/web/src/__tests__/audit-contract.test.ts:49,53,69,77` -- the same count in the twin's test (`toHaveLength(14)` → `15`) plus the membership row.

**Schema (read-only evidence — no migration)**
- `infra/migrations/20260921T1500_create_catalogue.up.sql` -- `tile.updated_at` exists and is written by hand (no trigger); `reference_image.tile_id ... ON DELETE CASCADE`; `reference_embedding.reference_image_id ... ON DELETE CASCADE`; `tile.code` UNIQUE as `tile_code_key`; `rocell_app` already holds `UPDATE`/`DELETE` on all six tables. Nothing in this story needs DDL.

**Web**
- `apps/web/src/screens/AddTileScreen.tsx` + `.module.css` -- the template for the new screen: `useId` per field, the `Field` union and `fieldFor`, one `role="alert"` node rendered in exactly one of N slots, `submitting` guard, `UPLOAD_TIMEOUT_MS` on the multipart request, the `Saving…`/`Saved.` indicator as the single `role="status"`, the result panel as a heading-labelled region (**not** a second live region), one accent Save beside a navy-outline Back, mirrored bounds as local `const`s.
- `apps/web/src/components/ConfirmDialog.tsx` -- `kind: 'confirm'` with `heading`, `body`, `confirmLabel`, `onConfirm`, `onClose`, `busy`. The destructive confirmation for removing reference images.
- `apps/web/src/api/client.ts:184-267` -- where the catalogue codes are exported; `apiRequest` already passes a `FormData` through unstringified with no `content-type` and takes any `method` and a `timeoutMs`.
- `apps/web/src/App.tsx` -- `Section`/`Screen` unions, `reachableBy`, `currentScreen`, `showSection`, the `screen === 'add-tile'` branch, and the role-guarded door group in the home panel. Six mechanical edits, one place each — and the `Section`/`Screen` doc comments state their own counts, so update the prose too.
- `apps/web/src/screens/AuditLogScreen.tsx:90` -- `ACTION_LABELS` needs the new action or the viewer renders a raw enum value.
- `apps/web/src/styles/tokens.css` -- the only file allowed a dimension literal (`no-raw-values.test.ts`); the thumbnail size must become a token here.

**Tests that fail unless they are extended**
- `apps/api/tests/test_admin_authorization.py:93` `ADD_TILE`/`TILE_IMAGE`, `:529` `test_the_admin_route_table_is_the_nine_routes_the_product_serves` -- the count is in the name; two new routes make it **eleven**.
- `apps/web/src/__tests__/error-code-parity.test.ts:119` `PYTHON`, `:146` `TYPESCRIPT`, `:219` "compares every code the API can emit", `:330` `BOUNDS` -- both directions plus the new screen's mirrored bounds.
- `apps/web/src/__tests__/styling-wiring.test.ts:154` (every module class referenced, both directions) and `:664` (the Add tile `describe` to model the new one on).
- `apps/web/src/__tests__/no-raw-values.test.ts` -- no dimension literal outside `tokens.css`, comments stripped first.
- `apps/api/tests/test_source_guards.py` -- no value interpolated into SQL, no second file naming the audit table, no `async def` handler.
- `apps/api/tests/test_add_tile.py:47` `needs_model`, `a_tile_photograph`, `jpeg_bytes`, `png_bytes`, `a_png_header_claiming`, `stored_objects`, `count`, `sign_in`, the `administrator` fixture -- the fixture vocabulary to reuse. `conftest.py` supplies `conn`, `client`, `make_user`, `audit_rows`, `storage_root`, `object_store`.
- `apps/api/tests/test_tile_searchable.py` -- the pattern for "findable with no re-index", through `find_candidates`.

**Read-only evidence**
- There is no `GET /admin/tiles/{tile_id}`, so `GET /admin/tiles/lookup` cannot collide with a typed-UUID sibling; `GET /admin/tiles/{tile_id}/images/{image_id}` is a different depth.
- `apps/web` has no router and no catalogue list; the home panel's door group is how every admin surface is reached today.
- `README.md:62` names `POST /admin/tiles` as the route that answers `503 matching_unavailable`.

## Tasks & Acceptance

**Execution:**
- `shared/schema/shared_schema/audit.py` -- add `CATALOGUE_TILE_EDITED = "catalogue_tile_edited"` to `AuditAction` -- the log has to name what happened, and a catalogue edit is not an add.
- `shared/schema/shared_schema/ts/audit.ts` -- add the member to the union and to `AUDIT_ACTIONS` -- the twin is the same contract in the other language.
- `shared/schema/tests/test_audit.py` + `apps/web/src/__tests__/audit-contract.test.ts` -- add the value and move both counts from fourteen to fifteen, in the test *names* as well as the assertions -- this repo treats counts-in-names as load-bearing.
- `apps/api/api/catalogue.py` -- add `TILE_NOT_FOUND`/`LAST_REFERENCE_IMAGE` codes with their sentences; `_SELECT_TILE_FOR_UPDATE` (locking read of the Tile with its resolved Size and Category), `_SELECT_TILE_IMAGES`, `_SELECT_TILE_BY_CODE`, `_UPDATE_TILE`, `_DELETE_REFERENCE_IMAGE` (returning both storage keys), and `_changed_fields` over `("code", "size", "category")`; then `GET /admin/tiles/lookup` and `PATCH /admin/tiles/{tile_id}` -- the edit reuses `_accept`, `_prepare`, `_discard`, `ensure_active_generation` and `_vector_literal` verbatim; a second copy of any of them is the AD-1 asymmetry one level up.
- `apps/api/tests/test_edit_tile.py` -- new; every row of the I/O matrix through the real route, including the extension-lies row, the concurrent-rename `UniqueViolation` window (hook `catalogue._prepare` the way `test_add_tile.py` does), and that a refused edit removes nothing, adds nothing and leaves no object behind.
- `apps/api/tests/test_tile_lookup.py` -- new; exact match, substring miss, unknown Code, blank Code, and that the body is the same closed `Tile` shape the add returns.
- `apps/api/tests/test_edited_tile_searchable.py` -- new; a renamed Code reaches `find_candidates` immediately; an added image makes the Tile findable from that image with no re-index; a removed image's embeddings are gone and the Tile's score for a perturbed copy of it falls to its score from the remaining image alone.
- `apps/api/tests/test_catalogue_audit.py` + `test_catalogue_authorization.py` + `test_admin_authorization.py` -- extend with the edit's entry (`details.changed`, `images_added`, `images_removed`, the Code snapshot), the staff/signed-out refusals on both new routes, and the route-table list renamed to eleven.
- `apps/web/src/api/client.ts` -- export `TILE_NOT_FOUND` and `LAST_REFERENCE_IMAGE` -- the parity guard runs in both directions, so a code with no twin fails the suite.
- `apps/web/src/screens/EditTileScreen.tsx` + `.module.css` -- new; a Code lookup, then the edit form: Code/Size/Category prefilled, each stored Reference Image as a thumbnail proxied from `GET /admin/tiles/{id}/images/{imageId}` with its FR-19 quality flag and a Remove toggle, a file input for new images, one accent Save, navy-outline Back, the shared `Saving…`/`Saved.` indicator, and a `ConfirmDialog` naming the Tile and the consequence before a save that removes anything.
- `apps/web/src/App.tsx` + `App.module.css` -- add the `edit-tile` section/screen, the admin reachability entry, the render branch and the home-panel door, and update the counts the two union doc comments state.
- `apps/web/src/screens/AuditLogScreen.tsx` -- add `catalogue_tile_edited: 'Tile edited'` -- the viewer must not render a raw enum value.
- `apps/web/src/styles/tokens.css` -- add the reference-thumbnail size token -- `no-raw-values` forbids a dimension literal anywhere else.
- `apps/web/src/__tests__/edit-tile.test.tsx` -- new; the lookup and its miss, the prefilled form, the submit shape (a `FormData` carrying exactly the named parts, with one `remove_image_ids` part per marked image), the confirmation before a destructive save, the saved indicator, the last-image refusal rendered from the server's sentence, and the door's role-conditionality -- following `add-tile.test.tsx`'s local `stubFetch`.
- `apps/web/src/__tests__/styling-wiring.test.ts` + `error-code-parity.test.ts` -- add the Edit tile `describe` (one accent control, destructive-coloured errors and the destructive Remove treatment, primary-coloured saved indicator, no similarity word, no retired word) and the new codes and mirrored bounds.
- `README.md` -- name `PATCH /admin/tiles/{tile_id}` alongside the add wherever the model prerequisite is stated -- an edit that uploads an image needs the artifact too.

**Acceptance Criteria:**
- Given an authenticated Administrator and a Tile that exists, when they change its Code, Size or Category, then the stored Tile carries the new values, `updated_at` has moved, no embedding row has been rewritten, and a vector query run immediately afterwards returns the Tile under its new Code with no re-index step.
- Given an edit that uploads a new Reference Image, when it succeeds, then that image passed content sniffing, ICC→sRGB relative-colorimetric colour management, the EXIF strip and the re-encode through the same `shared/vision` entry points the add calls, and it has 16 embedding rows in the active generation and a capped display derivative — with neither the extension nor the client-declared content type consulted at any point.
- Given an edit that removes a Reference Image, when it succeeds, then that image's row, its 16 embeddings and both its stored objects are gone, and a scan submitted afterwards can no longer match the Tile through it.
- Given an edit that would leave a Tile with no Reference Image at all, when it is submitted, then it is refused, nothing is written, no object is stored or deleted, and no audit entry exists.
- Given any non-Administrator or signed-out caller, when they call the edit or the lookup, then the server refuses with `403` or `401` regardless of what the UI renders, and nothing is written to the database or object storage.
- Given a successful edit, when the transaction commits, then exactly one `catalogue_tile_edited` entry records actor, timestamp, source IP, the Code and what changed, written in the same transaction; given a refused edit, then no entry and no orphaned row or stored object remain.
- Given the Edit tile screen, when an Administrator saves, then the inline indicator cycles `Saving…` → `Saved.` near the action that triggered it, a save that removes an image is confirmed first in a sheet that names the Tile and the consequence, there is exactly one accent control on the screen, no similarity value anywhere, and every interactive element is keyboard-reachable with a visible focus state.
- Given `make lint` and `make test`, when run from a clean tree, then both pass, with the catalogue tests exercised (not skipped) when the model artifact is present.

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Second follow-up review pass

- intent_gap: 0
- bad_spec: 0
- patch: 8: (high 0, medium 1, low 7)
- defer: 4: (high 0, medium 0, low 4)
- reject: 14: (high 0, medium 2, low 12)
- addressed_findings:
  - `[medium]` `[patch]` `handleLookup` guarded only `looking`, never `submitting` — the
    mirror of the race `handleSave` already documents and guards. The Find *button* is
    `disabled={looking || submitting}`, but the lookup field is not, and pressing Enter in a
    text field submits its form directly without consulting the button: a lookup started
    that way runs under an in-flight save and its `adopt()` resets code, size, category,
    marks and files out from under the request the Administrator is waiting on. Guard widened
    to `looking || submitting`, and `save()`'s own guard widened to include `looking` because
    the confirmation sheet calls it directly rather than through `handleSave` and so does not
    inherit that handler's guard. Pinned by `does not start a lookup underneath an in-flight
    save`, which fails against the previous guard.
  - `[low]` `[patch]` `handleSave` read `remaining` and `removing`, which were declared some
    forty lines below it. A `const` is not hoisted, so this worked only because nothing calls
    the handler during the render pass that defines it — a TDZ `ReferenceError` waiting on a
    refactor that moves the check into render or a `useMemo`. Both declarations moved above
    their first reader, with the reason recorded on them.
  - `[low]` `[patch]` `requested_removals`' comment explained the strip-and-drop as "a file
    input's empty part". `remove_image_ids` is a text `Form()` part; the sentence was carried
    over from the `uploads` filter above it and described the wrong mechanism. Reworded to
    what is actually true: a text part that is nothing but padding carries no id, and is
    dropped rather than answered with a `404` about the empty string.
  - `[low]` `[patch]` `--thumbnail-size`'s comment justified 96px as "small enough that eight
    of them fit a tablet row without scrolling". The gallery is inside
    `.screen { max-width: var(--measure-form) }` — 22rem — so with `--space-4` gaps three fit,
    on every viewport. Corrected to the bound that actually applies.
  - `[low]` `[patch]` Nothing drove the **in-transaction** `404 tile_not_found`. The only
    `tile_not_found` test on the edit route sends an unknown id and is answered by the
    pre-flight; the two concurrency tests both leave the Tile row in place. Dropping the
    locked read's branch — the "simplify to a zero-row `UPDATE`" refactor its own comment
    argues against — turns that documented `404` into an `assert` failure and a `500`, and
    the whole suite still passes. On the screen that is the difference between the edit form
    being torn down with focus handed back to the lookup and a dead form repeating a generic
    failure. Added `test_a_tile_removed_under_the_lock_is_a_404_and_not_a_500`, driving the
    delete through the same `_prepare` hook the rename-clash test uses, and asserting the
    rollback took the already-written objects back out.
  - `[low]` `[patch]` `_discard`'s `why` argument had no assertion anywhere. Its module
    docstring calls it "the whole reason `why` exists" and the post-commit test asserted only
    that `delete` was attempted twice — so swapping `DISCARD_REMOVED` for
    `DISCARD_ROLLED_BACK`, or dropping the third argument at the post-commit call site, was
    invisible while telling an operator a committed removal was a write that rolled back. The
    test now reads the emitted warnings.
  - `[low]` `[patch]` No test sent a Code containing a space through the lookup, on either
    side — though `handleLookup`'s only justification for `URLSearchParams` over a template
    literal names the real catalogue file `6LD.MA Quarry Stone Natural`, and the route matches
    exactly, so a Code that arrives mangled reads as "no such tile". Added
    `test_a_code_carrying_a_space_is_found_through_it` (exact match plus the trim, interior
    space preserved) and a web test asserting the escaped query string.
  - `[low]` `[patch]` `test_a_new_image_is_intaken_embedded_and_stored_like_any_other`
    asserted the embedding count only. The rename test compares `embedding_ids()` precisely
    because a delete-and-reinsert of the same sixteen vectors keeps the count identical — the
    same guard was absent on the add-an-image path, which is where a re-embed-everything
    change would actually land. Now asserts the prior ids are a strict subset of the ids
    after.

### 2026-09-22 — Follow-up review pass

- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 1, medium 7, low 6)
- defer: 4: (high 0, medium 2, low 2)
- reject: 11
- addressed_findings:
  - `[high]` `[patch]` `test_edited_tile_searchable.py` reintroduced the retired **Face**
    identity model in new prose and test Codes — `TWO-FACED`, `LOSES-A-FACE`, "Two visibly
    different faces of one Tile", "the removed face". The intent's Always list puts `Face`
    nowhere as "a type, column, class, label or sentence", and CLAUDE.md records the model as
    confirmed wrong against the source tree with a standing "do not reintroduce it" — a test
    file is where the wrong model gets taught to the next reader. Renamed to
    `TWO-IMAGES`/`LOSES-AN-IMAGE` and image-based prose; the `face` local in the shared
    fixture became `surface`. (The identical local in `test_tile_searchable.py` is baseline
    and untouched — see reject list.)
  - `[medium]` `[patch]` The previous pass's route-resolution pin could not detect the
    regression its own comment described. `_api_routes` returns `route.path`, the *declared*
    path, so a dict keyed by it still holds `("GET", "/admin/tiles/lookup") -> lookup_tile`
    after Story 2.5 registers a shadowing `GET /admin/tiles/{tile_id}` above it, while
    Starlette matches in registration order and `lookup` becomes a tile id. Rewritten to
    assert registration **order**: no earlier `GET` under `/admin/tiles/` may take a path
    parameter.
  - `[medium]` `[patch]` `invalid_category` was emitted by `edit_tile` and by `add_tile` and
    driven by nothing — `error-code-parity.test.ts` pins the constant across languages but
    issues no request, and neither refusal table sent a Category. Deleting the
    `except ValueError` around `clean_category` degraded the route to a `500` with no field
    marked and left the suite green. Added an overlong-category row (and an overlong-size row)
    to `test_edit_tile.py`'s refusal table.
  - `[medium]` `[patch]` No test asserted either catalogue audit label, and this story
    reworded Story 2.1's from `'Tile added to catalogue'` to `'Tile added'`. Swapping the two
    values — labelling every catalogue edit as an add — failed nothing:
    `Record<AuditAction, string>` compiler-enforces the key and not the value, and
    `audit-contract.test.ts` pins only vocabulary membership. `writes each action in words`
    now carries both entries and asserts each label in its own row.
  - `[medium]` `[patch]` A `404 image_not_found` on save left the dead id in `marked`, so every
    further Save carried it again and was refused identically, with nothing on screen naming
    the bad mark — the same dead end the screen already handles for `tile_not_found` one level
    up. The marks are cleared and the tile is kept, so the next Save can succeed.
  - `[medium]` `[patch]` Every Remove checkbox carried the accessible name `Remove`, so a
    screen-reader user met three identically named controls on the one destructive control of
    the screen, while the thumbnail beside each already names its image. Each now names the
    image it removes, and the test asserts the names are distinct.
  - `[medium]` `[patch]` The post-commit `_discard` — the entire reason the previous pass added
    the `why` parameter — had no test. Both the docstring and the module header claim a failing
    `store.delete` there must not turn a committed edit into a `500`, and deleting the
    `try/except` or the `why` argument left the suite green. A store whose `delete` raises now
    drives it, asserting the edit stands and that the call was really attempted.
  - `[medium]` `[patch]` The Edit screen defeated the server-side NULL-Category fix the
    previous pass made. `save()` appended `category` unconditionally and `adopt()` renders a
    null Category as `''`, so a tile with `category_id IS NULL` was refiled under the UNKNOWN
    sentinel by any save — including one that only fixed a Code — with a
    `category: null -> UNKNOWN` line in the audit log. `test_a_tile_with_no_category_keeps_none_when_the_part_is_absent`
    held only for an *absent* part, which the screen never sent. The part is now withheld when
    it would introduce a Category the tile never had; clearing a Category the tile *has* still
    sends the blank part, and both directions are tested.
  - `[low]` `[patch]` Three of the four hints were not programmatically associated with their
    inputs — only the file input had `aria-describedby`. The AD-18 rule that a cleared Category
    is filed under the sentinel rather than dropped is stated in that hint and nowhere else, so
    a screen-reader user never met it. All four are bound and asserted.
  - `[low]` `[patch]` `handleSave` guarded on `submitting` but not `looking`, while the submit
    button is disabled on both. Enter in a text field submits the form directly and never
    consults the button, so a save could still start under an in-flight lookup — the state the
    previous pass's fix was written to prevent. Both guarded.
  - `[low]` `[patch]` `tile_not_found` on save unmounts the form holding the focused control,
    and `fieldFor(..., 'edit')` faults no field, so `refuse` moved focus nowhere and it fell to
    `<body>` — outside the alert explaining why. Focus goes to the lookup input, and only in
    that branch, so `matching_unavailable` still leaves the form's focus alone.
  - `[low]` `[patch]` The lookup's `Finding…` live region had no test: replacing it with `''`
    left a press on a slow connection looking ignored, and nothing failed, because no test held
    the lookup promise open. Added, in the same shape as the save indicator's test.
  - `[low]` `[patch]` `_removals` deduplicated with `in` over a list and checked membership with
    `any(... not in held ...)` on a `remove_image_ids` list with no ceiling — quadratic in
    something an authenticated caller chooses, burned before the `404`. Both are set-based now.
    (A ceiling on the list itself is deferred: it needs a new envelope code and parity rows.)
  - `[low]` `[patch]` `test_tile_lookup.py` never sent an overlong Code, so `clean_code`'s
    ceiling branch was driven only on the edit path and this route's could have reached the
    generic handler unnoticed. Added to the existing parametrised refusal.

### 2026-09-22 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 15: (high 0, medium 3, low 12)
- defer: 6: (high 0, medium 1, low 5)
- reject: 6
- addressed_findings:
  - `[medium]` `[patch]` A lookup failure with no field at fault rendered **no alert at all** —
    the only null-field slot lived inside the `tile !== null` edit form, so a network error, a
    timeout, a `403` or a malformed body made Find look like it had been ignored, and
    `LOOKUP_FAILED` was unreachable. The lookup form got its own slot, bounded on
    `tile === null` so exactly one alert is still ever rendered, with three tests.
  - `[medium]` `[patch]` The confirmation sheet could promise "<code> keeps 0 reference
    images." and then be refused `409 last_reference_image`. `confirming` became a three-state
    `sheet`, and `remaining < 1` now opens `ConfirmDialog kind="refusal"` with no destructive
    control at all — EXPERIENCE.md:148's refusal-replaces-confirmation pattern, as the Users
    list already does — with the copy pinned to the Python sentence by a `SENTENCES` row.
  - `[medium]` `[patch]` The re-check of the removal set under the row lock had no test:
    collapsing it into the pre-flight left the whole suite green while two concurrent edits of
    a two-image tile, each removing one image, both committed and left the Tile with none —
    the state FR-7's floor exists to prevent. A driven concurrency test was added and
    mutation-checked.
  - `[low]` `[patch]` A Tile whose `category_id` is NULL was silently refiled under the
    UNKNOWN sentinel by an edit that sent no `category` part, because the fallback ran the
    stored NULL through `clean_category`. The column is now left alone when the part is
    absent, so "an absent part means unchanged" holds for it too.
  - `[low]` `[patch]` `remove_image_ids` values were filtered on `.strip()` but kept
    untrimmed, so a padded uuid was a `404 image_not_found` on a request whose Code the same
    handler trims. Stripped.
  - `[low]` `[patch]` Save was pressable while a lookup was in flight, so a late lookup could
    adopt over a just-saved tile and both live regions could speak at once. Disabled on
    `looking` as well.
  - `[low]` `[patch]` A `tile_not_found` from the `PATCH` left the stale form loaded, so every
    further Save failed identically. The tile is cleared, as the lookup path already did.
  - `[low]` `[patch]` `adopt()`'s clearing of `marked` and `files` after a successful save was
    unverified — no test saved twice, so dropping it left the suite green while a second save
    re-sent an already-removed id and re-uploaded stored files. Two-save test added and
    mutation-checked.
  - `[low]` `[patch]` `_SELECT_TILE_IMAGES`'s `ORDER BY` was unverified: deleting it failed
    nothing, because no test read more than one image id out of a response. A stable-order
    test over a three-image tile was added.
  - `[low]` `[patch]` `test_an_oversized_image_is_refused_before_it_is_decoded` asserted only
    the status and hand-rolled its own skip. Marked `@needs_model`, and both `intake_image`
    and `embed_images` now raise if reached, so the test finally checks the "before".
  - `[low]` `[patch]` `renders exactly one alert, however many things are wrong` constructed
    exactly one fault. Replaced with a parametrised test over four different faults that also
    asserts the alert is bound to the right control.
  - `[low]` `[patch]` A `PATCH` carrying no parts at all was untested, on an endpoint whose
    whole contract is "an absent part means unchanged". Added.
  - `[low]` `[patch]` `_discard`'s log line still read "after a failed add" though the edit now
    also calls it after a successful commit, so an operator could not tell a rolled-back
    orphan from a post-commit one. It takes a reason and logs it.
  - `[low]` `[patch]` `'Tile added to catalogue'` sat beside `'Tile edited'` in the audit
    viewer's label map. Made symmetric.
  - `[low]` `[patch]` Nothing pinned that `GET /admin/tiles/lookup` resolves to `lookup_tile`,
    so Story 2.5 registering `GET /admin/tiles/{tile_id}` above it would silently turn
    `lookup` into a tile id. The resolution is asserted.

## Design Notes

**Why the lookup exists, and why it is not Story 2.5.** EXPERIENCE.md reaches Edit Tile from a Catalogue row, and that list is Story 2.5's. Without some door this story ships a screen nothing can open. `GET /admin/tiles/lookup?code=` is an **exact** match returning one Tile — no listing, no substring, no filtering, no pagination — which is the smallest thing that makes the story usable and leaves 2.5's surface entirely unbuilt. When the list arrives it opens the same screen by id and this route can stay or go.

**Why `PATCH` is multipart and why an absent part means "unchanged".** The request carries files, so the body is multipart and there is no `null` on the wire. An absent part is therefore "leave it alone"; a present-but-blank `code` or `size` is a refusal, exactly as on the add, and a present-but-blank `category` resolves to `UNKNOWN`, also exactly as on the add. The screen sends all three because its form is prefilled, so the two readings never both apply to one request.

**The order, and why removal's objects go last.**

```
cheap refusals → active_generation (stamp) → SELECT tile FOR UPDATE (404)
  → validate remove ids ⊆ this tile's images → net image count >= 1 (409)
  → duplicate-Code pre-flight (409, fast path only)
  → _accept every new upload → _prepare every accepted one
  → store.put new objects, recording each key
  → BEGIN: UPDATE tile (UniqueViolation -> 409) ; DELETE removed images
           (embeddings cascade) ; INSERT new images + 16 embeddings each ;
           audit.record  COMMIT
  → delete the removed images' objects, best effort, logged
except BaseException: _discard(new keys); raise
```

Deleting a removed image's bytes before the commit would leave a live row pointing at nothing if anything after it failed — the one state the module docstring says must never happen. After the commit the row is gone, so the worst case is a file an operator can delete.

**`details` on the entry**, following `users._changed_fields`: `{"tile_id", "code" (as it now stands), "changed": {field: {"from", "to"}}, "images_added": n, "images_removed": n}`. Compared between the locked read and the `UPDATE`'s `RETURNING`, so it describes what landed rather than what was asked for; an edit that moved nothing records `changed: {}` rather than claiming a change.

## Verification

**Commands:**
- `make lint` -- expected: ruff check, ruff format --check, oxlint and `tsc --noEmit` all clean.
- `make test` -- expected: the whole workspace green, with `test_edit_tile.py`, `test_tile_lookup.py` and `test_edited_tile_searchable.py` **run** rather than skipped (the ONNX artifact is present at `shared/vision/shared_vision/models/model.onnx`).
- `uv run --project apps/api pytest apps/api/tests/test_edit_tile.py apps/api/tests/test_tile_lookup.py apps/api/tests/test_edited_tile_searchable.py -q` -- expected: green, and no test reporting `skipped` for a missing model.
- `npm --prefix apps/web test -- --run edit-tile styling-wiring error-code-parity audit-contract` -- expected: green.

**Manual checks (if no CLI):**
- `git status --porcelain` is empty of stray artifacts after a run: an edit that was refused must leave no file under `OBJECT_STORAGE_ROOT`.


## Auto Run Result

Status: done

### Summary of implemented change

Story 2.2 ships `PATCH /admin/tiles/{tile_id}` — one admin-only endpoint that changes a Tile's Code, Size and Category and adds or removes Reference Images in a single unit of work — alongside the exact-Code lookup `GET /admin/tiles/lookup` and the Edit tile screen that reaches a Tile by its Code until Story 2.5's catalogue list exists. New image bytes go through Story 2.1's `_accept`/`_prepare` path verbatim; removals are real `DELETE`s so `reference_embedding` cascades out of the index; the Tile keeps at least one Reference Image; storage writes precede the database and every object a failed request wrote is discarded, while a removed image's objects are deleted only after the commit, best effort and logged.

This run was the **second follow-up review pass** over the already-committed implementation (`5ffd19a`, hardened by `b633bf6`), triggered by `followup_review_recommended: true` on the previous pass. No code was re-derived: four review layers ran over the full diff since `c789ef3`, and the findings that survived triage were applied as patches.

### Files changed in this pass

- `apps/web/src/screens/EditTileScreen.tsx` — `handleLookup` guards `submitting` as well as `looking`, `save()` guards `looking` as well, and the two derived counts moved above the handler that reads them.
- `apps/api/api/catalogue.py` — the `requested_removals` comment corrected to describe a text part rather than a file input's empty one.
- `apps/web/src/styles/tokens.css` — `--thumbnail-size`'s rationale corrected to the `--measure-form` bound the gallery actually sits inside.
- `apps/api/tests/test_edit_tile.py` — a test driving the in-transaction `404 tile_not_found`; the post-commit `_discard` test now reads the warnings and asserts `why`; the add-an-image test compares embedding ids, not only the count.
- `apps/api/tests/test_tile_lookup.py` — a Code carrying a space, found through the route, trimmed at the ends only.
- `apps/web/src/__tests__/edit-tile.test.tsx` — a lookup refused under an in-flight save, and the escaped query string for a Code with a space.
- `_bmad-output/implementation-artifacts/spec-2-2-edit-product.md` — triage log entry, four deferred items, this section.

### Review findings breakdown

- **Patches applied: 8** — 1 medium, 7 low. Itemised in the Review Triage Log entry above.
- **Items deferred: 4** — the Size row lock taken on every edit (low), the edit form's controls staying live under an in-flight save that then discards them (low), a missing derivative rendering as a broken-image glyph (low), and a third sighting of the web suite's under-load flake, this time in `edit-user.test.tsx` (low). Appended to the spec's `deferred` frontmatter list, which now holds 14 items with every prior one preserved.
- **Items rejected: 14** — six were restatements of entries already on the deferred list (`remove_image_ids` having no ceiling, no cumulative image bound per Tile, `typed()` leaving a stale refusal painted, the lost update between two Administrators, the audit entry not identifying a destroyed image, and the second-Find clobber); the rest: `LOOKUP_FAILED`/`UNEXPECTED` called dead code (defensive fallbacks copied verbatim from `AddTileScreen`, not introduced here); `assert` statements being stripped under `python -O` (four such asserts predate this story in the same module, and none guards a reachable state); the response composing `size`/`category` in Python while `reference_images` is read back (both are values this transaction just wrote); no path returning a Category to NULL (AD-18 is explicit that a Category is never dropped); `lookup_tile` declaring `code: str = ""` rather than a required parameter (the blank refusal is the documented behaviour and is pinned by name); `AuditLogScreen` shortening the shipped `catalogue_tile_added` label for symmetry with the new one (a deliberate choice inside the label map this story must edit anyway); the module docstring's refusal list not enumerating the edit's new codes; two test-local `edit()` helpers differing on `None` handling; and `test_edited_tile_searchable.py` selecting `images[1]` by position (the test's own `after_kept == before_kept` assertion fails if the wrong image is removed, so it is self-checking).

### Follow-up review recommendation

`true`. Patched findings this pass: **high 0, medium 1, low 7**. No high-severity patch, so the score decides: `3 × 1 + 1 × 7 = 10`, over the threshold of 5. The trend is down sharply from the previous pass (14 patches, `high 1, medium 7, low 6`, score 27): every finding this pass was a comment, a guard or a missing assertion, and none touched the endpoint's behaviour.

### Verification performed

- `make lint` — **pass**. `ruff check` clean, `ruff format --check` clean over 84 files, `oxlint --deny-warnings` clean, `tsc --noEmit` clean. (First run failed on one `E501` in the new `_discard` assertion; the line was wrapped and the rerun is the result above.)
- `make test` — **pass**: `1313 passed` (API, pytest) and `1277 passed / 23 files` (web, vitest). An earlier invocation failed once at `apps/web/src/__tests__/edit-user.test.tsx:506` — a file this story does not touch — and passed alone (44/44) and on the next full run; recorded as a deferred item rather than treated as a result of this change.
- `uv run --project apps/api pytest apps/api/tests/test_edit_tile.py apps/api/tests/test_tile_lookup.py apps/api/tests/test_edited_tile_searchable.py -q -k "removed_under_the_lock or carrying_a_space or refusing_to_delete or intaken_embedded"` — **4 passed, 0 skipped**: the new and changed API tests run against the real model artifact rather than skipping.
- The medium finding's test was checked against the unpatched guard: with `handleLookup` restored to `if (looking) return;`, `does not start a lookup underneath an in-flight save` fails (1 failed / 55 passed) and passes with the guard in place.
- `git status --porcelain` carries no stray artifact — no file left under `OBJECT_STORAGE_ROOT` by a refused edit.

### Residual risks

- **The edit's contract with the screen is still unjoined.** `edit-tile.test.tsx` drives the screen against a hand-written `fetch` stub, and three of the server's refusal sentences are retyped as literals in the test file. `error-code-parity.test.ts` pins the codes and the numeric bounds in both directions, but nothing pins the sentences or the multipart part names across languages, so the two halves can drift without a red test.
- **Concurrency is ordered but not detected.** The row lock serializes two edits of one Tile; it does not notice the second read a stale copy. Recorded on the deferred list, and it needs a catalogue-wide `If-Match` contract rather than an edit.
- **A Tile's image count is bounded per request, not cumulatively**, and re-saving an asset already on the Tile stores a second copy with sixteen more vectors behind it. Also on the deferred list.
- **The web suite has failed once per full run in three of the last several runs**, in two different files, always on a focus- or timing-dependent assertion, always passing alone. Until that is chased down, a green `make test` is slightly weaker evidence than it reads as.

