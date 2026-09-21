---
title: 'Story 2.3 — Remove Tile'
type: 'feature'
created: '2026-09-22'
status: 'done'
baseline_revision: 'f5a907c22d17949d75fecb46d13acbb893e2bd3b'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-2-edit-product.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      No `FOR UPDATE` read anywhere in the API sets a `lock_timeout`, so one stuck
      transaction blocks every request that touches the same row indefinitely.
    evidence: |-
      `catalogue.remove_tile` and `catalogue.edit_tile` take `_SELECT_TILE_FOR_UPDATE`,
      and `users.delete_user`/`deactivate_user` take their own locking reads, none of
      them under a `SET LOCAL lock_timeout`. A transaction that acquires a row lock and
      then hangs holds a worker per waiting request until the pool is exhausted. Not
      caused by this story — the pattern predates it in three handlers — and a timeout
      value plus the refusal it maps to is a product decision rather than an edit.
    location: >-
      apps/api/api/catalogue.py remove_tile, edit_tile; apps/api/api/users.py delete_user
    severity: medium
  - summary: >-
      The `needs_model` skipif block is now written out verbatim in four test files
      rather than living in `conftest.py`.
    evidence: |-
      `pytest.mark.skipif(not pipeline.MODEL_PATH.exists(), ...)` appears identically in
      `test_add_tile.py`, `test_catalogue_audit.py`, `test_remove_tile.py` and — added by
      this story — `test_catalogue_authorization.py`, each with its own `shared_vision`
      imports. `conftest.py` already supplies every other shared fixture these files use.
      A fourth copy is the point at which the duplication is worth collapsing, but doing
      it touches three files this story does not otherwise own.
    location: >-
      apps/api/tests/conftest.py
    severity: low
  - summary: >-
      `session-expiry.test.tsx`'s sign-out assertion is flaky under the full
      suite's parallel load, failing roughly one run in four while passing every
      time the file is run alone.
    evidence: |-
      Observed during this pass: `make test` failed once at
      `session-expiry.test.tsx:165` (`findByLabelText(/password/i)` timing out
      after the sign-out click, with the signed-in home panel still rendered),
      then passed on two consecutive full runs and on an isolated run of that
      file. Nothing in this story touches session handling or that screen — the
      only edits near it are comment-only lines in `App.tsx` and
      `api/client.ts` — so the flake predates this change and is a property of
      the test's waiting strategy under 23 parallel workers, not of the diff.
    location: >-
      apps/web/src/__tests__/session-expiry.test.tsx:165
    severity: low
---

<intent-contract>

## Intent

**Problem:** A Tile can be added and corrected but never withdrawn. A discontinued range, a duplicate Code, a range catalogued in error — all of them stay in the embedding index forever and keep coming back as Candidates for every Scan, and the only current remedy is to edit a Tile into something it is not. Story 2.2 built removal for a *Reference Image* and stopped one level short: `LAST_REFERENCE_IMAGE`'s own sentence tells an Administrator to "remove the tile instead", and there is nothing to press.

**Approach:** One admin-only `DELETE /admin/tiles/{tile_id}` that hard-deletes the Tile so `reference_image` and `reference_embedding` cascade out of the searchable graph with it, records one `catalogue_tile_removed` audit entry in the same transaction, and deletes the stored objects after the commit — plus a destructive **Remove tile** action on the Edit tile screen, which is the only door that reaches a Tile until Story 2.5's Catalogue list ships.

## Boundaries & Constraints

**Always:**
- **Removal is real removal** (AD-5, FR-16). `DELETE FROM tile` and let the migration's two `ON DELETE CASCADE`s carry `reference_image` and then `reference_embedding` out of the HNSW graph. No soft-delete column, no `deleted_at`, no query-time predicate — a predicate is a thing exactly one call site has to remember, and Epic 3's scan is the call site that must not forget.
- The Tile row is locked `FOR UPDATE OF t` by `_SELECT_TILE_FOR_UPDATE` before anything is deleted, so a concurrent `PATCH` on the same Tile serializes against it rather than adding an image into a row that is going.
- **Database first, storage second — the inverse of the add's ordering, and for the same reason** `edit_tile` gives: the objects belonging to a removed Tile are deleted only **after** the commit, best effort and logged through `_discard(store, keys, DISCARD_REMOVED)`. A row pointing at absent bytes is unrecoverable; an orphaned object is a file an operator deletes.
- The delete and its audit entry share one `with conn.transaction():`, and the entry is written **after** the `DELETE` inside it — so the entry exists exactly when the removal committed. The `details` snapshot is taken from the locked read, because there is no row left to read it from (AD-10).
- `require_administrator` on the new route; it lives under `/admin/`. `NO_STORE` on the response.
- Domain vocabulary only: `Tile`, `Code`, `Size`, `Category`, `Reference image`. `Product`, `Face` and `Design` appear nowhere as a type, column, class, label or sentence.
- The web removal is confirmed in a `ConfirmDialog` that names the Code and the consequence, with a destructive-filled confirm carrying a *word* — red is never the only signal.

**Block If:**
- The removal cannot be expressed without a schema change — a missing cascade or a foreign key from `audit_log` into `tile` would make this a migration story and a data-integrity decision, not an endpoint. (Read-only evidence below says both are already right; this fires only if that evidence turns out false.)

**Never:**
- Do not touch `shared/vision`, do not add a migration, and do not re-embed or re-index anything. A removal takes rows out of the active generation; it does not cut a new one.
- Do not make the route idempotent. An unknown id is `404 tile_not_found`, exactly as `delete_user` refuses an unknown account — a silent `204` for a Tile that was never there tells an Administrator they removed something they did not.
- Do not add a new envelope code. `TILE_NOT_FOUND` already exists and is already exported and mirrored; a second code for the same fact is drift.
- Do not build Story 2.5's catalogue list or substring search, Story 2.4's bulk path, Epic 3's scan endpoint, or a bulk-remove verb. One Tile per request.
- Do not add a restore, an undo, a trash state or a grace period. The confirmation is the safeguard.
- Do not delete, update or cascade into `audit_log` — the entries naming this Tile stay, which is the whole point of recording the removal (AD-4, AD-10).
- Do not add a presigned or direct-to-storage URL (AD-9), a vector database, an ORM, a router or a form library. Do not enable OpenAPI/docs routes, add CORS, or introduce middleware.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Remove a Tile | Admin session; `DELETE /admin/tiles/{id}` for a Tile with two Reference Images | `204` with no body; the `tile` row, both `reference_image` rows and all 32 `reference_embedding` rows are gone; all four stored objects are deleted | No error expected |
| Removed Tile is unfindable at once | Remove a Tile, then query `find_candidates` with a perturbed copy of one of its reference images | That Tile is absent from the candidates, however close the image; no re-index step was run | No error expected |
| Other Tiles are untouched | Two Tiles indexed; one removed | The survivor keeps its rows, its embeddings and its objects, and still returns as a Candidate | No error expected |
| Shared Size and Category | Two Tiles under one Size and one Category; one removed | `204`; the `tile_size` and `tile_category` rows survive — they are shared lookups, not the Tile's property | No error expected |
| Audit entry | A successful removal | Exactly one `catalogue_tile_removed` entry, in the same transaction, carrying actor, timestamp, source IP and `details` = `{tile_id, code, size, category, images_removed}`; `target_user_id`/`target_email` are null | No error expected |
| Entries naming the Tile survive | A Tile with an earlier `catalogue_tile_added` entry is removed | Both entries remain readable and unchanged; no `DELETE` and no `UPDATE` reaches `audit_log` | The removal never cascades into the log |
| Audit write fails | `audit.record` raises inside the transaction | The removal is rolled back: the Tile, its images and its embeddings are all still there, and no object was deleted | Transaction rolled back before any object is touched |
| Unknown Tile | `DELETE /admin/tiles/{unknown uuid}` | `404` `tile_not_found`; nothing deleted, no audit entry | Decided by the locking read, never by a zero-row `DELETE` |
| Malformed id | `DELETE /admin/tiles/not-a-uuid` | `422` from the path-parameter parse; nothing deleted | FastAPI's own, as on the edit |
| Object deletion fails | Storage refuses one key after the commit | Still `204` — the rows are gone; a warning is logged naming the key and `DISCARD_REMOVED` | Best effort, never a `500` over a successful removal |
| Concurrent edit | A `PATCH` on the same Tile arrives while the removal holds the lock | Whichever commits second sees the other: the edit answers `404 tile_not_found` and discards every object it wrote | Serialized by `FOR UPDATE OF t` |
| Staff caller | Valid non-admin session | `403` `administrator_required`; nothing deleted from database or storage | Existing dependency |
| Signed-out caller | No session cookie | `401` `unauthorized` | Existing dependency |
| Screen — confirm then remove | Administrator finds a Tile, presses **Remove tile**, confirms | The sheet names the Code and the consequence; on success the form closes, the lookup stage returns with `<code> removed.` announced, and focus moves to the lookup field | No error expected |
| Screen — cancel | The sheet is dismissed by Cancel, `Escape` or the scrim | Nothing is requested and the form is exactly as it was | No write |
| Screen — Tile already gone | The Tile was removed elsewhere between the lookup and the confirm | The server's `404` sentence is rendered on the screen and the form closes to the lookup, as a failed save already does | `TILE_NOT_FOUND` |

</intent-contract>

## Code Map

**API — the module being extended**
- `apps/api/api/catalogue.py` -- the whole write path. Reuse, do not re-derive: `_refusal` (:244), `TILE_NOT_FOUND` (:146) and `NO_SUCH_TILE` (:191), `_tile_not_found()` (:1014), `_SELECT_TILE_FOR_UPDATE` (:331 — locks `FOR UPDATE OF t`, and the comment there explains why it must name the table), `_SELECT_TILE_IMAGES` (:359), `_discard` (:736) with `DISCARD_REMOVED` (:237), `active_generation` (:505). `edit_tile` (:1158) is the shape to follow for the transaction and the post-commit `_discard`; `delete_user` is the shape to follow for the verb. **The module docstring (:1) opens "Four routes and one function that is not a route" and closes with "Not here, deliberately: the Tile removal (2.3)…" — both sentences are now false and are part of this change.**
- `apps/api/api/users.py:1450` `delete_user` -- the `DELETE` idiom to copy verbatim in shape: `status_code=status.HTTP_204_NO_CONTENT`, `-> None`, the locking `SELECT` that distinguishes the `404` rather than a zero-row `DELETE`, the audit entry written *after* the delete and inside its transaction, and the AD-10 snapshot taken from `current` because there is no row left to read.
- `apps/api/api/audit.py:230` `record(...)`, `:149` `source_ip` -- the only INSERT against the audit table. `catalogue.py` must never name `audit_log` (`tests/test_source_guards.py`).
- `apps/api/api/dependencies.py:193` `require_administrator`, `NO_STORE` -- authorization and the actor in one; declared, never a line in the handler.
- `apps/api/api/db.py` -- autocommit pool, `dict_row`, `get_connection`, `with conn.transaction():`. Handlers are `def`, never `async def`.
- `apps/api/api/storage.py` -- `ObjectStore.delete`, `get_object_store`.
- `apps/api/api/main.py:186` -- `catalogue.router` is already included; **no registration change**. `STATUS_CODES` already maps 404.

**Contract**
- `shared/schema/shared_schema/audit.py:130` -- `CATALOGUE_TILE_EDITED` is the last member; add `CATALOGUE_TILE_REMOVED` after it. The `CATALOGUE_TILE_ADDED` comment at :125 already anticipates this story by name.
- `shared/schema/shared_schema/ts/audit.ts:57,63` -- the `AuditAction` union and the `AUDIT_ACTIONS` list. Two places here plus the two tests below, or the suite fails.
- `shared/schema/tests/test_audit.py:133` `test_the_vocabulary_is_the_fifteen_actions_the_product_writes` -- the count is in the name; rename to `sixteen` and add the value at :153.
- `apps/web/src/__tests__/audit-contract.test.ts:49` ("is the fifteen actions…"), `:54` (`toHaveLength(15)`), `:71` (the list), `:80` (the membership table) -- the same count in the twin.
- No new envelope code, so `apps/web/src/api/client.ts` and `error-code-parity.test.ts` need **no** change — `TILE_NOT_FOUND` is already exported and already mirrored in both directions.

**Schema (read-only evidence — no migration)**
- `infra/migrations/20260921T1500_create_catalogue.up.sql:126` -- `reference_image.tile_id ... REFERENCES tile (id) ON DELETE CASCADE`, with the comment naming AD-5 as the reason; `:192` -- `reference_embedding.reference_image_id ... ON DELETE CASCADE`. So one `DELETE FROM tile` clears all three levels.
- `:234-236` -- `rocell_app` already holds `DELETE` on `tile`, `reference_image` and `reference_embedding`. Nothing in this story needs DDL or a GRANT.
- `audit_log` carries no foreign key into `tile`; `details.tile_id` is an AD-10 snapshot. `tile_size` and `tile_category` are referenced *by* `tile`, not the other way, so a removal cannot cascade into them.

**Web**
- `apps/web/src/screens/EditTileScreen.tsx` -- the surface this action joins. `sheet` (:256) is a three-state union that needs a fourth; `adopt` (:288), `refuse` (:277), `focus` (:263), `lookupRef` (:257), `submitting`/`looking` guards (:380, :478), the `TILE_NOT_FOUND` branch in `save` (:426) which already models "the tile went while the form was open". **Its docstring at :89 says "No tile removal. Story 2.3's." — that sentence is part of this change.**
- `apps/web/src/screens/EditTileScreen.module.css` -- `.submit` is the only `var(--color-accent)` rule and `styling-wiring.test.ts:851` counts accents over the whole file, so the new control must be `.destructive` (destructive fill, `--color-destructive-foreground`), never a second accent.
- `apps/web/src/screens/UserListScreen.module.css:301` `.destructive` -- DESIGN.md's `button-destructive`, already written once; copy its treatment rather than inventing a second one.
- `apps/web/src/components/ConfirmDialog.tsx` -- `kind: 'confirm'` with `heading`, `body`, `confirmLabel`, `onConfirm`, `onClose`, `busy`. Already carries the focus trap, `Escape` and the scrim; nothing here needs a new dialog.
- `apps/web/src/api/client.ts:465` `apiRequest` -- `:506` already answers `null` for a `204` without parsing a body, and takes any `method`. No client change.
- `apps/web/src/screens/AuditLogScreen.tsx:97` -- `ACTION_LABELS` needs `catalogue_tile_removed: 'Tile removed'` or the viewer renders a raw enum value.
- `apps/web/src/App.tsx` -- **no change.** The action lives on a screen that already exists and is already role-guarded; no new `Section`, `Screen` or door.

**Tests that fail unless they are extended**
- `apps/api/tests/test_admin_authorization.py:539` `test_the_admin_route_table_is_the_eleven_routes_the_product_serves` -- the table compares `f"{method} {path}"`, so `DELETE {EDIT_TILE}` is a **twelfth** entry; the count is in the name and must move to `twelve`, with the comment's story list extended.
- `apps/api/tests/test_no_registration.py:250-253` -- compares **paths**, not methods, and `/admin/tiles/{tile_id}` is already listed. **No change.**
- `apps/api/tests/test_catalogue_audit.py:236` `EDIT_ACTION` and its `edit()` helper (:243) -- the pattern for a third action block: one entry, the target columns null, no storage key or file name in `details`, and a refusal writing no entry.
- `apps/api/tests/test_catalogue_authorization.py:134,227` -- the staff and signed-out refusals per route, each asserting nothing was written.
- `apps/api/tests/test_add_tile.py:47` -- the fixture vocabulary to reuse: `needs_model`, `a_tile_photograph`, `jpeg_bytes`, `stored_objects`, `count`, `sign_in`, the `administrator` fixture. `conftest.py` supplies `conn`, `client`, `make_user`, `audit_rows`, `storage_root`, `object_store`.
- `apps/api/tests/test_edited_tile_searchable.py` -- the pattern for "gone from the index", through `find_candidates` rather than through a row count.
- `apps/web/src/__tests__/edit-tile.test.tsx` -- `stubFetch` and the existing lookup/save flows to model the removal flow on.
- `apps/web/src/__tests__/styling-wiring.test.ts:763-855` -- the `saving is the one action on the edit tile screen` describe; the accent count at :851 is what a wrongly-styled new control breaks.
- `apps/web/src/__tests__/no-raw-values.test.ts` -- no dimension literal outside `tokens.css`, comments stripped first.
- `apps/api/tests/test_source_guards.py` -- no value interpolated into SQL, no second file naming the audit table, no `async def` handler.

**Read-only evidence**
- `README.md:62` names the routes that need the model artifact. A removal embeds nothing, so it is **not** one of them and the line stays as it is.
- `_SELECT_CANDIDATES` (`catalogue.py:428`) joins `reference_embedding → reference_image → tile`, so a removed Tile leaves the result set by the cascade alone — no query change, and no filter to forget.

## Tasks & Acceptance

**Execution:**
- `shared/schema/shared_schema/audit.py` -- add `CATALOGUE_TILE_REMOVED = "catalogue_tile_removed"` after `CATALOGUE_TILE_EDITED`, with the comment stating why it is a member rather than an `catalogue_tile_edited` with a flag -- the log has to name what happened, and a removal is the one event whose subject no longer exists.
- `shared/schema/shared_schema/ts/audit.ts` -- add the member to the `AuditAction` union and to `AUDIT_ACTIONS` -- the twin is the same contract in the other language.
- `shared/schema/tests/test_audit.py` + `apps/web/src/__tests__/audit-contract.test.ts` -- add the value and move both counts from fifteen to sixteen, in the test *names* as well as the assertions -- this repo treats counts-in-names as load-bearing.
- `apps/api/api/catalogue.py` -- add `_SELECT_TILE_IMAGE_KEYS` (both storage keys for a Tile's images) and `_DELETE_TILE` (`DELETE FROM tile WHERE id = %s`), then `DELETE /admin/tiles/{tile_id}` → `remove_tile`, answering `204`: `NO_STORE`, one transaction holding `_SELECT_TILE_FOR_UPDATE` (404), the key read, the `DELETE`, and `audit.record`; `_discard(store, keys, DISCARD_REMOVED)` after the commit -- and update the module docstring's route count and its "not here, deliberately" list, which both name this story as absent.
- `apps/api/tests/test_remove_tile.py` -- new; every row of the I/O matrix through the real route: the `204` and the three levels of rows gone, the objects gone, an unknown id, a malformed id, a survivor Tile untouched, shared Size/Category rows surviving, a storage failure after the commit still answering `204` with a warning logged, and an `audit.record` failure leaving everything in place.
- `apps/api/tests/test_removed_tile_unsearchable.py` -- new; a perturbed copy of a removed Tile's own reference image no longer returns it from `find_candidates`, with no re-index step run, while a second Tile indexed alongside it still does.
- `apps/api/tests/test_catalogue_audit.py` -- extend with the removal's entry: exactly one, `details` = `{tile_id, code, size, category, images_removed}`, the account target columns null, no storage key or file name anywhere in it, the earlier `catalogue_tile_added` entry for that Tile still present and unchanged, and no entry at all for a refused removal.
- `apps/api/tests/test_catalogue_authorization.py` -- extend with the staff and signed-out refusals on `DELETE /admin/tiles/{tile_id}`, each asserting the Tile, its images, its embeddings and its objects are all still there.
- `apps/api/tests/test_admin_authorization.py` -- add `f"DELETE {EDIT_TILE}"` to the route table and rename the test to `twelve`, extending its comment with this story -- the number in the name may never drift from the list.
- `apps/web/src/screens/EditTileScreen.tsx` -- add the destructive **Remove tile** control below the form (rendered only once a tile is loaded), a `'remove'` member on the `sheet` union, the `ConfirmDialog` naming the Code and the consequence with `confirmLabel="Remove tile"`, the `DELETE` request, and the return to the lookup stage announcing `<code> removed.` with focus moved to the lookup field -- and correct the docstring line that says this screen has no tile removal.
- `apps/web/src/screens/EditTileScreen.module.css` -- add `.destructive` with DESIGN.md's `button-destructive` treatment and a `.removal` section wrapper, tokens only -- an accent fill here would give the screen two primary actions and break the accent count the styling suite holds.
- `apps/web/src/screens/AuditLogScreen.tsx` -- add `catalogue_tile_removed: 'Tile removed'` -- the viewer must not render a raw enum value.
- `apps/web/src/__tests__/edit-tile.test.tsx` -- extend; the Remove tile control appears only with a tile loaded, the sheet names the Code and the consequence before anything is requested, Cancel requests nothing, a confirmed removal issues `DELETE /admin/tiles/{id}` and returns to the lookup stage with the removal announced, a `404` renders the server's sentence and closes the form, and the control is disabled under an in-flight lookup or save.
- `apps/web/src/__tests__/styling-wiring.test.ts` -- extend the edit-tile describe: the removal control carries the destructive fill and its own foreground, the screen still holds exactly one accent, and the control meets the touch-target floor.

**Acceptance Criteria:**
- Given an authenticated Administrator and a Tile in the catalogue, when they remove it, then the Tile row, every one of its Reference Images and every embedding those images produced are hard-deleted — with no soft-delete column, no `deleted_at` and no query-time filter anywhere in the codebase — and its stored objects are deleted after the commit.
- Given a Tile that has been removed, when a Scan is submitted afterwards with an image that previously matched it, then that Tile is not among the Candidates however visually similar the image is, and no re-index step was run to make that true.
- Given a Tile removed from a catalogue holding other Tiles, when the removal commits, then every other Tile keeps its rows, its embeddings and its objects and still returns as a Candidate, and the shared Size and Category rows survive.
- Given a successful removal, when the transaction commits, then exactly one `catalogue_tile_removed` entry records actor, timestamp, source IP and a snapshot of the Code, Size, Category and image count, written in the same transaction; and given a refused removal, then no entry exists and nothing was deleted from the database or from storage.
- Given audit entries that already name the removed Tile, when it is removed, then those entries remain readable and unchanged — the removal neither cascades into the log nor is blocked by it.
- Given any non-Administrator or signed-out caller, when they call the removal, then the server refuses with `403` or `401` regardless of what the UI renders, and nothing is deleted.
- Given the Edit tile screen with a Tile loaded, when an Administrator presses Remove tile, then a sheet names the Code and states that the tile and everything the catalogue indexed from it are deleted permanently, its confirm control carries a word as well as the destructive fill, dismissing it requests nothing, and confirming returns the screen to its lookup stage with the removal announced and focus on the lookup field.
- Given the Edit tile screen, when the removal control is added, then the screen still has exactly one accent-filled control, every interactive element is keyboard-reachable with a visible focus state, and no similarity value and no retired word appears anywhere on it.
- Given `make lint` and `make test`, when run from a clean tree, then both pass, with the catalogue tests exercised (not skipped) when the model artifact is present.

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 0, medium 2, low 11)
- defer: 2: (high 0, medium 1, low 1)
- reject: 7: (high 0, medium 0, low 7)
- addressed_findings:
  - `[medium]` `[patch]` Nothing rendered the new audit label. `audit-log.test.tsx`'s
    `writes each action in words` pins `Tile added` and `Tile edited` **by row**, precisely
    so a label swap between catalogue actions is caught, and it was not extended —
    `Record<AuditAction, string>` forces the key but never the value, and
    `audit-contract.test.ts` never reads the map, so `catalogue_tile_removed` could have
    rendered `Tile edited` with the whole suite green. A `TILE_REMOVED` fixture was added
    and its own row now asserts `Tile removed`.
  - `[medium]` `[patch]` The row-lock test passed whether or not `remove_tile`'s read took
    the lock: the blocker holds a lock that `_DELETE_TILE` must acquire anyway, so a
    non-locking read would still block and still answer `204`. Two removals of one Tile
    that actually overlap had no test at all, which is the interleaving `FOR UPDATE OF t`
    exists for. `test_two_overlapping_removals_of_one_tile_answer_204_and_404` arranges the
    overlap rather than hoping for it — the winner sleeps inside its transaction with the
    row lock held — and asserts `{204, 404}`, the loser's code as `tile_not_found` rather
    than an `AssertionError` from `assert deleted == 1`, exactly one audit entry, and no
    Tile left. The timing-based test is kept, with its docstring now stating what it
    cannot claim.
  - `[low]` `[patch]` `DISCARD_REMOVED` read "the reference image was removed" and
    `remove_tile` passes it for a whole-Tile withdrawal, so an operator reading the
    orphaned-object warning after a removal was told a *reference image* went. Widened to
    "the rows pointing at it were removed", which is true of both call sites; the constant
    is named in the intent contract, so it was widened rather than twinned.
  - `[low]` `[patch]` The storage-failure test asserted the warning count and the `why`
    substring but never that each orphaned key was named — and the key is the operator's
    only route back to bytes no row points at. All four keys are now asserted.
  - `[low]` `[patch]` An exception raised inside a worker thread was swallowed, so a
    handler that raised surfaced as `[] == [204]` with the real error unreported. Both
    threaded tests now capture `BaseException` and assert the failure list is empty first.
  - `[low]` `[patch]` No test removed a Tile whose Category is NULL — the one entry whose
    subject cannot be re-read, never exercised in its degenerate shape, though
    `_SELECT_TILE_FOR_UPDATE` LEFT JOINs the Category and `details["category"]` can be
    JSON `null`. Added, asserting the key is *present and null* rather than dropped.
  - `[low]` `[patch]` `test_removed_tile_unsearchable.py` indexed the pre-removal candidate
    list without checking it, so an empty search raised `IndexError` instead of an
    assertion naming the empty candidate set. Named, asserted non-empty, then indexed.
  - `[low]` `[patch]` `test_a_signed_out_caller_is_refused_the_removal` checked only the
    status and the envelope code, while its staff twin and all nine pre-existing refusal
    tests in that file also assert the caller touched neither the database nor the store —
    which the file's own docstring calls the one thing the route-table guard cannot see.
    Brought into line.
  - `[low]` `[patch]` `storage_root: Any` in the new audit test where the sibling file
    types it `Path`; and a bare embedding count with no note of where sixteen comes from.
    Typed, and AD-13 named beside the count.
  - `[low]` `[patch]` `removeTile`'s `TILE_NOT_FOUND` branch cleared `tile` and `marked`
    but not `files` or the file input's value, while the success path cleared all four —
    staged files outliving a form that is gone, for a Tile that is gone. Both branches now
    clear all four.
  - `[low]` `[patch]` The lookup indicator's comment claimed "starting a lookup clears the
    announcement" and `handleLookup` never called `setRemoved('')`: pressing Find after a
    removal without retyping rendered `Finding…` in the navy `saved` class. The code now
    does what the comment says, pinned by a regression test.
  - `[low]` `[patch]` The removal sheet's dismissal was tested through Cancel only, where
    the matrix names Cancel, `Escape` and the scrim. The test is now an `it.each` over all
    three, each asserting nothing was requested and the form is untouched.
  - `[low]` `[patch]` Nothing pinned `removeTile`'s `submitting || looking` guard — the
    belt behind `ConfirmDialog`'s `busy` braces — so it could have been deleted with the
    suite green. A test now presses the confirm twice against a never-answered `DELETE`
    and asserts exactly one request.

### 2026-09-22 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 6: (high 0, medium 0, low 6)
- defer: 0
- reject: 14: (high 0, medium 0, low 14)
- addressed_findings:
  - `[low]` `[patch]` `_discard`'s docstring still opened "Two call sites, and they are
    mirror images of each other" while the bullet list beneath it carried three — this
    story added the third. In a module whose docstring this same change moved from four
    routes to five, and a suite that renames counts in test names, the one count left
    stale was the one right above the function. Rewritten as three call sites in two
    shapes, which is what `why` actually distinguishes.
  - `[low]` `[patch]` `find_candidates`'s docstring claimed "an empty catalogue has no
    active generation", and this story is the first thing that can empty one. A removal
    takes vectors out of the graph; it does not retire the generation they were cut into
    (and retiring one would be re-indexing, which the contract forbids). So an emptied
    catalogue keeps an active generation, skips the cheap early return, and pays a full
    embed to answer `[]` — which `test_removing_the_last_tile_leaves_a_search_that_answers_nothing`
    walks straight through without noticing. The docstring now names both shapes of
    "none" and which route each takes; the behaviour is correct and unchanged.
  - `[low]` `[patch]` `images_removed` is the only part of the snapshot that is computed
    rather than copied, and every assertion on it in the suite read `== 1`. A hardcoded
    `1`, or the length of the wrong list, was green everywhere. A removal of a Tile
    holding three images now asserts three.
  - `[low]` `[patch]` `test_no_table_the_removal_touches_carries_a_soft_delete_marker`
    promised "a later migration that adds one fails here" while matching only
    `%deleted%`, `%removed%` and `%archived%` — `is_active`, `hidden`, `visible`,
    `withdrawn` and `retired` all passed it silently. The spellings are widened and the
    docstring now says what a name test can and cannot claim, naming the behavioural
    assertions that are the rest of AD-5's guard.
  - `[low]` `[patch]` The form stays mounted behind the confirmation sheet's 55%-opacity
    scrim while the `DELETE` is out, and `removeTile` borrows `submitting` — which drives
    the save indicator. So the most destructive action on the screen spent its entire
    duration reading `Saving…`. The indicator now says `Removing…` for the one in-flight
    request that is not a save (told apart by the open removal sheet, which is set before
    the request and cleared only once the answer is in), pinned by its own test.
  - `[low]` `[patch]` `styling-wiring.test.ts`'s `saving is the one action on the edit
    tile screen` is where this story put three tile-removal tests, so the name had become
    false — the screen has two actions now, one of them accented. Renamed to `saving is
    the one accented action on the edit tile screen`, which is the claim the block's own
    comment makes and the one its assertions check.

### 2026-09-22 — Review pass (second follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 9: (high 0, medium 1, low 8)
- defer: 1: (high 0, medium 0, low 1)
- reject: 16: (high 0, medium 0, low 16)
- addressed_findings:
  - `[medium]` `[patch]` The matrix's **Concurrent edit** row had no test at the
    surface it names. `test_an_edit_arriving_after_the_removal_is_told_the_tile_is_gone`
    runs the two strictly in sequence, so the `PATCH` refuses at `edit_tile`'s *cheap*
    pre-flight `_SELECT_TILE` — before any decode, any embed and any `store.put`. Its
    `stored_objects(...) == []` therefore asserted that nothing was ever written, not
    that anything written was discarded, which is the half of the row that matters: the
    loser is the caller holding bytes. `test_an_edit_already_in_flight_when_the_removal_commits_is_refused_and_leaves_no_object`
    arranges the overlap instead of hoping for it — the edit is held at its last
    `store.put`, the statement immediately before `BEGIN`, with both of its objects on
    disk, and released only once the removal has answered `204` — then asserts the `404`
    came from the locking read, that all four objects are gone, and that one entry exists.
  - `[low]` `[patch]` `client.ts`'s `TILE_NOT_FOUND` doc named `GET /admin/tiles/lookup`
    and `PATCH /admin/tiles/{id}` as the code's two producers. This story adds a third
    with the same reasoning ("the id came from this app rather than from them"), and the
    Code Map's correct conclusion that the *code* needs no change carried the prose beside
    it past the sweep. Extended.
  - `[low]` `[patch]` `App.tsx`'s comment enumerating where "the server refuses a Staff
    caller" listed five routes and missed the new `DELETE /admin/tiles/{id}`. Exhaustiveness
    is that comment's whole job — it is the argument that the role check in the UI is a
    convenience and never the decision. Extended.
  - `[low]` `[patch]` Two comments — `EditTileScreen.tsx`'s beside the per-image checkboxes
    and its twin in `edit-tile.test.tsx` — still called those checkboxes "the one
    destructive control of the screen". This story adds a second and more destructive one.
    The previous pass renamed `styling-wiring.test.ts`'s describe block for exactly this
    reason and did not sweep for the sibling sentences. Both now say "the one destructive
    control *inside the form*", and name what sits below it.
  - `[low]` `[patch]` The `#:` paragraph added for `DISCARD_REMOVED` sat above
    `DISCARD_ROLLED_BACK`, so the doc block explaining why one constant is worded about
    rows attached to the other one. Split: the shared two-cases header stays above
    `DISCARD_ROLLED_BACK`, the `DISCARD_REMOVED` argument moved directly above the
    constant it is about.
  - `[low]` `[patch]` `test_the_removal_waits_on_a_concurrent_holder_of_the_tiles_row_lock`'s
    docstring claimed it was "the only honest way to assert the lock" and that a
    non-locking read "would pass every other test in this file" — both false, and flatly
    contradicted by the sibling `test_two_overlapping_removals_of_one_tile_answer_204_and_404`
    four lines below, whose own docstring says "The lock test above cannot make this
    claim". The previous pass's triage log records this as already fixed; the fix never
    landed. The docstring now states what the test does assert, what it cannot, and which
    test carries the claim instead.
  - `[low]` `[patch]` The **Remove tile** hint — the only statement anywhere on the screen
    that the deletion is permanent and stops scans returning the tile — carried no `id`
    and the button no `aria-describedby`, while every other hint on the screen is bound
    and `binds every hint to the control it is about` pins that convention for four of
    them. The one control whose press cannot be taken back announced only its two words.
    Bound, and the test extended to it.
  - `[low]` `[patch]` `nothing_was_removed` in `test_catalogue_authorization.py` asserted a
    bare `16`, and `test_remove_tile.py` three bare `16`/`32`s, with no note of where the
    number comes from — the previous pass added exactly that AD-13 annotation to the
    sibling assertion in `test_catalogue_audit.py` and stopped there. Both files now name
    AD-13 beside the count.
  - `[low]` `[patch]` The spec's **Verification** commands omitted
    `test_catalogue_authorization.py`, which this story extends with five tests, and the
    `audit-log` vitest file, where the previous pass added the `Tile removed` row
    assertion. Both targeted commands would have passed over a regression in a file this
    story owns. Added.

## Design Notes

**Why `DELETE FROM tile` and not three deletes.** The migration already carries both cascades and says AD-5 is why. Deleting the children by hand would be a second statement of a rule the schema already makes, and the two would drift the first time a table is added below `reference_image`. The handler deletes one row; the database carries the rest out of the HNSW graph.

**Why the storage keys are read before the delete.** After the `DELETE` there is no row to read them from, and they are the only way to reach the bytes. So: lock, read the keys, delete, record, commit — then the objects.

```
NO_STORE
BEGIN
  SELECT ... FOR UPDATE OF t        -> None => 404 tile_not_found
  SELECT source_key, derivative_key FROM reference_image WHERE tile_id = %s
  DELETE FROM tile WHERE id = %s    -- reference_image, reference_embedding cascade
  audit.record(CATALOGUE_TILE_REMOVED, details=<snapshot from the locked read>)
COMMIT
_discard(store, keys, DISCARD_REMOVED)   -- best effort, logged, never a 500
return 204
```

**Why the ordering is the inverse of the add's.** `add_tile` writes storage first so a failed request leaves an orphaned object rather than a row pointing at nothing. A removal has the same asymmetry read backwards: deleting the bytes before the commit would leave a live row pointing at nothing if the transaction then rolled back, so the bytes go last. Both rules are the same rule — a row must never outlive its bytes.

**`details` on the entry**, following `delete_user`'s snapshot argument: `{"tile_id": str(...), "code", "size", "category", "images_removed": n}`. Taken from the locked read, because after the `DELETE` there is nothing to take it from, and written *after* the `DELETE` inside the same transaction so the entry exists exactly when the removal did. No `target_user_id`/`target_email` — those columns are an account's, and `test_catalogue_audit.py` already asserts a Tile never fills them.

**Why the screen does not get a surface of its own.** EXPERIENCE.md puts destructive catalogue actions in a labelled row-end menu on the Catalogue list, and that list is Story 2.5's. Until it exists, the Edit tile screen is the only thing that reaches a Tile — and its own `LAST_REFERENCE_IMAGE` refusal already tells the Administrator to "remove the tile instead". Putting the control there closes that sentence's loop without building a screen 2.5 will replace. The confirm sheet is `ConfirmDialog`'s existing `confirm` shape; no stacked sheets, and no second dialog component.

## Verification

**Commands:**
- `make lint` -- expected: ruff check, ruff format --check, oxlint and `tsc --noEmit` all clean.
- `make test` -- expected: the whole workspace green, with `test_remove_tile.py` and `test_removed_tile_unsearchable.py` **run** rather than skipped (the ONNX artifact is present at `shared/vision/shared_vision/models/model.onnx`).
- `uv run --project apps/api pytest apps/api/tests/test_remove_tile.py apps/api/tests/test_removed_tile_unsearchable.py apps/api/tests/test_catalogue_audit.py apps/api/tests/test_catalogue_authorization.py apps/api/tests/test_admin_authorization.py -q` -- expected: green, and no test reporting `skipped` for a missing model.
- `npm --prefix apps/web test -- --run edit-tile styling-wiring audit-contract audit-log error-code-parity` -- expected: green.

**Manual checks (if no CLI):**
- `git status --porcelain` is empty of stray artifacts after a run, and no file is left under `OBJECT_STORAGE_ROOT` for a Tile that was removed.



## Auto Run Result

Status: done

### Summary of implemented change

A second follow-up review pass over an already-implemented and already-reviewed story
(`followup_review_recommended: true` carried in from the previous pass). The endpoint is
unchanged: `DELETE /admin/tiles/{tile_id}` still locks the Tile with `FOR UPDATE OF t`,
reads its images' storage keys, issues one `DELETE FROM tile` so `reference_image` and
then `reference_embedding` cascade out, records one `catalogue_tile_removed` entry from an
AD-10 snapshot inside the same transaction, and discards the objects only after the
commit. Four review layers ran over the full diff since `f5a907c`; twenty-six findings
survived deduplication — nine patched, one deferred, sixteen rejected.

Eight of the nine patches are documentation and verification corrections. The ninth is the
substantive one: the I/O matrix's **Concurrent edit** row — a `PATCH` arriving while the
removal holds the lock, answering `404` and discarding every object it wrote — had no test
that reached the surface it names. The existing test ran the two in sequence, so the edit
refused at `edit_tile`'s cheap pre-flight before writing anything, and its
"no objects left behind" assertion was vacuous. A new test arranges the real interleaving.

No behaviour changed in any shipped code path. The only executable changes are one
`aria-describedby` binding on the Remove tile control and its hint's `id`.

### Files changed

- `apps/api/api/catalogue.py` — the `DISCARD_REMOVED` doc paragraph moved from above
  `DISCARD_ROLLED_BACK` to above the constant it explains. No executable change.
- `apps/api/tests/test_remove_tile.py` — new
  `test_an_edit_already_in_flight_when_the_removal_commits_is_refused_and_leaves_no_object`,
  which holds the edit at its last `store.put` with both objects written, runs the removal
  to `204`, then releases it; the row-lock test's docstring corrected to what it can
  actually claim; `VIEWS_PER_IMAGE` added to source the embedding counts to AD-13.
- `apps/api/tests/test_catalogue_authorization.py` — `nothing_was_removed`'s docstring now
  names AD-13 and the source/derivative pair behind its `(1, 1, 16)` and its two objects.
- `apps/web/src/api/client.ts` — `TILE_NOT_FOUND`'s doc extended with the removal, its
  third producer.
- `apps/web/src/App.tsx` — the staff-refusal route list extended with
  `DELETE /admin/tiles/{id}`.
- `apps/web/src/screens/EditTileScreen.tsx` — the removal hint given an `id` and bound to
  the Remove tile button; the per-image checkbox comment's "one destructive control of the
  screen" narrowed to "inside the form".
- `apps/web/src/__tests__/edit-tile.test.tsx` — `binds every hint to the control it is
  about` extended to the Remove tile control; the same stale comment corrected.
- `_bmad-output/implementation-artifacts/spec-2-3-remove-product.md` — Verification
  commands extended with `test_catalogue_authorization.py` and `audit-log`; triage log and
  this result appended; one deferred entry added.

### Review findings breakdown

- **Patches applied: 9** — 0 high, 1 medium, 8 low. Itemised in the Review Triage Log
  entry above.
- **Items deferred: 1** — a pre-existing flake in `session-expiry.test.tsx` under the full
  suite's parallel load, observed once this pass and not reproducible in isolation or on
  two subsequent full runs. The two pre-existing issues raised again this pass (no
  `lock_timeout` on any `FOR UPDATE` read; the `needs_model` skipif duplicated across test
  files) are already in this spec's `deferred` list and were not duplicated.
- **Items rejected: 16** — all low. The largest group is scope: `images_removed` as the
  snapshot's key, the absence of `face_number` from it, and the whole shape of `details`
  are fixed verbatim in the intent contract, so they are out of scope on the intent's own
  authority. `assert deleted == 1` being elided under `python -O` was rejected in both
  previous passes for the same reason. The in-flight indicator selecting `Removing…` from
  the open removal sheet is the design the previous pass deliberately chose and pinned
  with a test; replacing it with a dedicated flag to serve Story 2.5's catalogue list is
  building for a story the contract forbids building. The refusal sheet remaining a dead
  end rather than growing a removal control is an EXPERIENCE.md-cited decision recorded in
  the code. `DISCARD_REMOVED`'s wording change being asserted by symbol rather than by
  literal string is correct — the constant is named in the intent contract precisely so it
  can be reworded. The claim that removed vectors "leave the HNSW graph" being asserted at
  the row and query-result surfaces rather than at the index structure is the only
  observable surface a test has. `cursor: progress` on the disabled removal control, the
  consequence sentence appearing in both the hint and the dialog body, the unreachable
  `submitting || looking` belt behind `ConfirmDialog`'s `busy`, and the 0.25s overlap
  margin (which degrades to a pass, not a flake) are all defensible as written.

### Follow-up review recommendation

`true`. Patched counts: 0 high, 1 medium, 8 low → score `3 × 1 + 1 × 8 = 11`, which is 5 or
more. Note that no patched finding this pass changed shipped behaviour, so the score is
driven by volume of documentation and verification corrections rather than by risk.

### Verification performed

- `make lint` — clean: ruff check, ruff format --check (after `make format` reflowed the
  new test's argument list), oxlint and `tsc --noEmit` all pass.
- `make test` — green: **1345 pytest passed** with 0 skipped (the ONNX artifact is present,
  so every catalogue test ran) and **1300 vitest passed** across 23 files.
- `uv run --project apps/api pytest apps/api/tests/test_remove_tile.py -q` — 16 passed,
  0 skipped, including the new overlap test.
- `npm --prefix apps/web test -- --run edit-tile styling-wiring audit-contract audit-log
  error-code-parity` — 366 passed across 5 files.
- One `make test` run failed at `session-expiry.test.tsx:165` and then passed on two
  consecutive full runs and on an isolated run of that file. Recorded as a deferred flake;
  nothing in this story touches session handling, and the only edits near it are
  comment-only.

### Residual risks

- **The new overlap test is timing-arranged, not timing-free.** It is deterministic in the
  direction that matters — the edit cannot proceed past its last `store.put` until the
  removal has answered, because it waits on an explicit event rather than on a sleep — but
  it does depend on `edit_tile` continuing to write both objects immediately before
  `BEGIN`. If that ordering is ever changed, the test's own
  `len(stored_objects(...)) == 4` gate fails loudly rather than passing vacuously, which
  is the failure mode to want.
- **No `lock_timeout` anywhere in the API** (deferred, medium). A transaction that takes a
  Tile's row lock and then hangs will block every request touching that row until the pool
  is exhausted. The removal inherits this from three pre-existing handlers; the timeout
  value and the refusal it maps to are a product decision.
- **The `session-expiry` flake** (deferred, low) can fail a CI run on this branch for
  reasons unrelated to it.
