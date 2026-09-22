---
title: 'Scan History'
type: 'feature'
created: '2026-09-22'
baseline_revision: '03f3a2a8a2672fefde8a91c81adc64b7a1f9935a'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      `HistoryScreen.module.css`'s `.back`/`.retry`/`.more` rules are
      byte-for-byte duplicates of each other (and of `AuditLogScreen.module.css`'s
      own copies of the same three).
    evidence: |-
      Verified by direct diff of the two files: all three classes carry the
      identical secondary-button rule set. This is a pre-existing convention
      `AuditLogScreen.module.css` already established before this story —
      HistoryScreen faithfully restated it rather than introducing it. No shared
      base class exists for a CSS-module screen to import from today.
    location: apps/web/src/screens/HistoryScreen.module.css
    severity: low
  - summary: >-
      No test pins a history card's reference-image `<img src>` to the
      `GET /tiles/{tile_id}/images/{image_id}` route pattern it is supposed to
      reuse.
    evidence: |-
      The boundary ("no new image route") is satisfied by inspection of
      `imageSrc()` in `HistoryScreen.tsx`, byte-identical to `ResultsScreen.tsx`'s
      own function, but neither screen's test suite asserts the rendered `src`
      resolves to that path pattern. Pre-existing test-coverage habit, not
      introduced by this story.
    location: apps/web/src/screens/HistoryScreen.tsx
    severity: low
---

<intent-contract>

## Intent

**Problem:** `POST /scans` (Story 3.4) computes and returns up to three ranked Candidates but persists nothing — `scan.py`'s own docstring already flags this as the known gap. A Staff or Administrator who scanned a tile has no way to revisit that result once they navigate away; it existed only in one response body.

**Approach:** Persist each submitted scan as a denormalized snapshot (AD-10) in a new `scan` table, inside the same `submit_scan` handler that already computes the response. Add a session-gated `GET /scans` read, keyset-paginated and scoped to the caller's own rows, mirroring `GET /admin/audit`'s exact shape. Add a Scan History screen (a home-panel door, like Scan/Users/Audit log/Catalogue) rendering each past scan's timestamp and its Candidate cards, reusing `ResultsScreen`'s card markup.

## Boundaries & Constraints

**Always:**
- `submit_scan` inserts one `scan` row (`user_id`, `candidates_snapshot`, `created_at`) after computing the same `list[ScanCandidate]` it already returns — including an empty array (no confident match) — and only once the crop/quality gates and matching have all succeeded. A refused submission (crop-rect, quality, oversized, unreadable, model-missing, stale-index) writes no row.
- `candidates_snapshot` is a JSON snapshot of the returned Candidates (AD-10) — never a foreign key to Tile or Reference Image. `scan.user_id` is the one real foreign key: `REFERENCES users (id) ON DELETE CASCADE`, `sessions.user_id`'s own precedent (`infra/migrations/20260917T1300_create_sessions.up.sql`), so a hard-deleted user's rows never dangle.
- `GET /scans` is `require_claimed_user`-gated, never `require_administrator` — every claimed Staff or Administrator account reaches it — and scoped with `WHERE user_id = %s` to the resolved caller's own id, never another user's.
- Pagination mirrors `GET /admin/audit` exactly: `ORDER BY created_at DESC, id DESC`, a published page-size constant in `shared_schema` (never a caller-supplied limit), a `before` cursor naming the oldest row already rendered, bare JSON array response, a cursor naming no row is `404`.
- A history entry's candidate image is fetched through the existing `GET /tiles/{tile_id}/images/{image_id}` route (Story 3.4) — no new image route, no new image-fetch logic.
- The new `scan` table gets full `GRANT SELECT, INSERT, UPDATE, DELETE` to `rocell_app`, matching every table except `audit_log` — `apps/api/tests/test_audit_immutability.py::test_every_other_table_is_fully_granted` fails the build otherwise, even though nothing in this story ever updates or deletes a row (see Design Notes).
- New migration under `infra/migrations/`, `IF NOT EXISTS` throughout, its own explicit `GRANT`, `.up.sql`/`.down.sql` pair — every existing migration's shape.

**Block If:** None identified — no human-only action (external account, domain, credential) is needed; this story is fully buildable and verifiable inside the repo.

**Never:**
- Never build the bottom tab bar EXPERIENCE.md:42 describes (Scan/History). No real nav shell exists anywhere in `apps/web` yet — every section reachable today (Scan, Users, Audit log, Catalogue) is a plain home-panel door. History gets the same door, not a new nav component.
- Never special-case a candidate image that 404s because its Tile/Reference Image was later deleted — no image-consuming screen in this codebase does that today (`ResultsScreen`, `CatalogueScreen`); Story 3.4's own review confirmed this is the established convention, not a regression to fix here.
- Never let a caller choose the page size, exactly as `GET /admin/audit` never does.
- Never add a TypeScript twin or `error-code-parity.test.ts` entry for the cursor-not-found code — `AUDIT_ENTRY_NOT_FOUND` has none either; the client never invents a cursor, so the 404 is not a case any screen branches on.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Signed-in caller with scans | `GET /scans`, no cursor | `200`, own scans newest-first, up to the page size | No error |
| Caller has never scanned | `GET /scans` | `200`, `[]`; screen renders "No scans yet." | No error |
| Another user's scans exist | `GET /scans` | `200`, only the caller's own rows, never another user's | No error |
| More history than one page | `GET /scans?before=<oldest rendered id>` | `200`, the next oldest page | No error |
| Cursor names no row | `GET /scans?before=<invented uuid>` | `404`, names no entry | `404` |
| Signed out | `GET /scans` | `401` | `401` |
| A candidate's Tile is later removed | History entry rendered after the removal | Code/Size/Category still render from the snapshot; the image request `404`s | `404` on the image fetch only, no special screen handling |

</intent-contract>

## Code Map

- `infra/migrations/20260922T1900_create_scan.up.sql` (new) -- `CREATE TABLE IF NOT EXISTS scan (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE, candidates_snapshot jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())`; `CREATE INDEX IF NOT EXISTS scan_user_id_created_at_idx ON scan (user_id, created_at DESC, id DESC)` (the keyset-pagination index, `audit_log_created_at_idx`'s twin, scoped per-user); `GRANT SELECT, INSERT, UPDATE, DELETE ON scan TO rocell_app` (full DML — see Design Notes).
- `infra/migrations/20260922T1900_create_scan.down.sql` (new) -- `20260921T1500_create_catalogue.down.sql`'s shape: a role-existence-guarded `REVOKE ALL PRIVILEGES ON scan FROM rocell_app`, `DROP INDEX IF EXISTS scan_user_id_created_at_idx`, `DROP TABLE IF EXISTS scan`.
- `shared/schema/shared_schema/scan.py` -- add `ScanHistoryEntry(BaseModel)`: `id: UUID`, `created_at: AwareDatetime` (with `AuditLogEntry`'s own `@field_serializer("created_at", when_used="json")` UTC coercion), `candidates: list[ScanCandidate]`; `model_config = ConfigDict(extra="forbid")`. Add `HISTORY_PAGE_SIZE = 50` and `HISTORY_CURSOR_PARAM = "before"`, restated rather than imported from `audit.py` (`tile.py`'s own cross-import reasoning) — this module's own two published constants.
- `shared/schema/shared_schema/ts/scan.ts` -- add the `ScanHistoryEntry` interface, `isScanHistoryEntry` (validates `id`/`created_at` the way `audit.ts`'s `isAuditLogEntry` does, and the `candidates` array via `Array.isArray(value.candidates) && value.candidates.every(isScanCandidate)`), `SCAN_HISTORY_ENTRY_KEYS`, `HISTORY_PAGE_SIZE`, `HISTORY_CURSOR_PARAM` (`audit.ts`'s `AUDIT_PAGE_SIZE`/`AUDIT_CURSOR_PARAM` twins).
- `shared/schema/tests/test_scan.py` -- extend with `ScanHistoryEntry` coverage in `test_audit.py`'s shape: round-trip, closed-shape rejection, a wrong-typed `candidates` element refused, TS-interface-declares-every-field, narrowing-covers-every-field, and the two published constants pinned against their TS spellings.
- `apps/api/api/scan.py` -- add `from psycopg.types.json import Jsonb`; add `ScanHistoryEntry, HISTORY_PAGE_SIZE` to the `shared_schema.scan` import. Add `_INSERT_SCAN` (`INSERT INTO scan (user_id, candidates_snapshot) VALUES (%s, %s)`) and, inside `submit_scan`, execute it with `(user.id, Jsonb([c.model_dump(mode="json") for c in candidates]))` immediately before the existing `return [...]` — after the list comprehension is built, so the persisted snapshot is byte-identical to the response. Add `_SELECT_LATEST_SCANS`/`_SELECT_SCANS_BEFORE`/`_SELECT_SCAN_EXISTS` and `SCAN_ENTRY_NOT_FOUND`/`NO_SUCH_SCAN_ENTRY`, `audit.py`'s three statements and two constants, scoped by an added `user_id = %s` predicate. Add `@router.get("/scans", response_model=list[ScanHistoryEntry])` `def read_scan_history(response, user: Annotated[User, Depends(require_claimed_user)], conn, before: UUID | None = None)` -- `read_audit_log`'s exact shape and cursor-exists-check, scoped to `user.id`. **Row-to-model mapping differs from `audit.py`**: the column is `candidates_snapshot`, the field is `candidates`, so each row builds `ScanHistoryEntry(id=row["id"], created_at=row["created_at"], candidates=[ScanCandidate(**c) for c in row["candidates_snapshot"]])` rather than a bare `model_validate(row)` (psycopg decodes `jsonb` to a Python list automatically, `details`'s existing decode path).
- `apps/api/tests/test_scan_submission.py` -- extend with `test_a_successful_submission_persists_a_scan_row` (submit, then `conn.execute("SELECT user_id, candidates_snapshot FROM scan")` and assert one row landed matching the response body) and `test_an_empty_match_result_still_persists_a_row` (empty-catalogue case, asserts `candidates_snapshot = []`); extend an existing refusal test (e.g. the quality-gate one) with an assertion that no row was written.
- `apps/api/tests/test_scan_history.py` (new) -- `test_audit_read.py`'s shape: happy path (own entries, newest first), empty history (`[]`), cross-user isolation (two `make_user` sessions, each submits, each's `GET /scans` shows only its own), keyset pagination (seed past `HISTORY_PAGE_SIZE`, `before` walks older pages), a cursor naming no row is `404` (`scan_entry_not_found`), signed-out is `401`, and AD-10 survival: seed a scan, hard-delete its Tile via `DELETE /admin/tiles/{tile_id}`, assert the history entry's snapshot fields render unchanged.
- `apps/web/src/screens/HistoryScreen.tsx` (new) -- `AuditLogScreen`'s state machine (`Listing` union, generation counter, `inFlight` ref, Load more) calling `apiRequest('/scans')` / `apiRequest('/scans?' + HISTORY_CURSOR_PARAM + '=' + id)` directly (not a `client.ts` wrapper -- `AuditLogScreen`/`CatalogueScreen`'s own precedent for a plain list read); `asHistoryEntries` narrows the body with `isScanHistoryEntry` (`asEntries`'s shape). Each entry renders its timestamp (`AuditLogScreen.WHEN_FORMATTER`'s exact options) above its Candidates, reusing `ResultsScreen`'s card markup/styling **and its `ImageViewer` tap-to-fullscreen behavior** (extract a small shared component if that stays clean, or restate the ~15-line map if extraction adds more indirection than it saves) -- the verification moment applies here exactly as it does on Results, since a history entry's whole point is confirming a past match. No row-end actions, no image-error special-casing, `ResultsScreen`'s own precedent otherwise. Empty history renders the verbatim "No scans yet." (EXPERIENCE.md:86). Props: `onBack: () => void`.
- `apps/web/src/screens/HistoryScreen.module.css` (new) -- reuses `ResultsScreen.module.css`'s card/pill/meta tokens and `AuditLogScreen.module.css`'s pending/failure/Load-more classes.
- `apps/web/src/App.tsx` -- add `'history'` to `Section` and `Screen`; leave it out of `reachableBy`'s admin-only list (defaults to `true`, `'scan'`'s own precedent -- reachable by every role); add `if (section === 'history') return 'history';` in `currentScreen` (no captured-state precondition -- simpler than `'audit'`/`'catalogue'`, which fall back to `'shell'` only because they are admin-gated); add a `screen === 'history'` render branch (`'audit'`'s shape: `<AppShell>` + `<HistoryScreen onBack={() => showSection('home')} />`); add a "History" door on the home panel beside "Scan", outside the `user.role === 'admin'` fragment (EXPERIENCE.md:31 -- Staff and Administrator both reach it).

## Tasks & Acceptance

**Execution:**
- `infra/migrations/20260922T1900_create_scan.{up,down}.sql` -- the `scan` table, its keyset index, its full grant -- the persistence target for every snapshot.
- `shared/schema/shared_schema/scan.py` + `ts/scan.ts` + `tests/test_scan.py` -- the `ScanHistoryEntry` contract, both languages, parity-tested.
- `apps/api/api/scan.py` -- persist on submit; `GET /scans`, keyset-paginated, scoped to the caller.
- `apps/api/tests/test_scan_submission.py` + `test_scan_history.py` -- persistence coverage and read-path coverage (isolation, pagination, snapshot survival).
- `apps/web/src/screens/HistoryScreen.tsx` + `.module.css` -- the History surface.
- `apps/web/src/App.tsx` -- History wiring (section/screen/home-panel door).

**Acceptance Criteria:**
- Given I am signed in and have submitted at least one scan, when I open History, then I see my own past scans, each showing the result exactly as it was returned at scan time -- the same Candidates, in the same order, with working reference images where the underlying Tile still exists.
- Given another user has also submitted scans, when I open History, then I see only my own scans, never theirs.
- Given I have never submitted a scan, when I open History, then I see the verbatim "No scans yet." message, never a blank screen.
- Given a scan I made earlier matched a Tile an Administrator has since removed, when I view that history entry, then its Code/Size/Category still render from the stored snapshot, unaffected by the deletion (AD-10).
- Given more history exists than one page holds, when I reach the end of a page, then a Load more control fetches the next oldest page, exactly as the Audit log's own pagination behaves.
- Given I tap a Candidate card on a past scan, when the tap registers, then its reference image opens full-screen, dismissible exactly as it is on Results.

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 0, medium 2, low 2)
- defer: 2: (high 0, medium 0, low 2)
- reject: 11: (high 0, medium 0, low 11)
- addressed_findings:
  - `[low]` `[patch]` `apps/api/api/scan.py`'s `_scan_entry_not_found` docstring claimed `SCAN_ENTRY_NOT_FOUND`/`NO_SUCH_SCAN_ENTRY` were "deliberately local to this function," but the function body only assigned generic `code`/`message` locals — the named identifiers didn't exist. Fixed by renaming the two locals to match the docstring's own claim.
  - `[medium]` `[patch]` No test proved `scan.user_id ON DELETE CASCADE` actually cascades, breaking this codebase's own established convention of testing every such FK (`test_delete_user.py`'s `sessions.user_id` equivalent). Added `test_a_deleted_users_scans_cascade` to `test_scan_history.py`.
  - `[low]` `[patch]` A test in `history.test.tsx` titled "...closes on Escape, a scrim click and Close..." only exercised the Escape path in its body. Rewritten as an `it.each` covering all three dismissal gestures.
  - `[medium]` `[patch]` The AD-10 "survives Tile removal" acceptance criterion is phrased at the screen surface ("when I view that history entry") but was only covered by an API-level test (`test_a_removed_tiles_history_entry_still_renders_its_snapshot`). Added a `history.test.tsx` case stubbing a scan entry naming a nonexistent tile/image and asserting its Code/Size/Category still render.

Rejected (verified false, matching an established codebase precedent this story correctly followed, or explicitly out of scope by the spec's own stated boundaries): candidate-card markup duplicated between `ResultsScreen` and `HistoryScreen` rather than extracted was flagged, but the spec's own Boundaries explicitly licensed either choice ("extract... or restate... if extraction adds more indirection than it saves") — not a deviation; no error handling was proposed around the `scan` INSERT inside `submit_scan`, but `api.audit.record`'s own documented rule is to let `psycopg.Error` propagate rather than swallow a write that matters, and this INSERT is the same shape of write; `_history_entries` raising an unhandled `ValidationError` on a hypothetically malformed `candidates_snapshot` row was flagged, but no schema change exists today that could produce one, and this codebase's own convention (AGENTS.md, this file's own Boundaries) is not to guard against scenarios that cannot happen; only one refusal path (quality gate) was tested for "persists no row" out of five named refusal cases, but the spec's own Code Map asked for exactly one representative test ("extend an existing refusal test (e.g. the quality-gate one)"), which is what was delivered; `test_scan_history.py`'s own local `submit_scan` helper having a different signature from `test_scan_submission.py`'s was flagged as confusing, but the two are file-scoped with no actual collision, an ordinary test-file convention throughout this suite; the `NO_MATCH` comment calling `'No confident match.'` a "past-tense twin" of `ResultsScreen.NO_MATCH` was flagged as inaccurate, but the string itself is clear and correct — a pedantic reading of "twin," not a defect; the spec's own `warnings: ['oversized']` was flagged as scope creep, but this is the same flag Story 3.4's spec carried for a comparably cohesive DB+BE+UI story, expected process signal rather than a code defect; the claim that `GET /scans` needs no route-table test update was flagged as unverified, but the verification-gap review pass independently confirmed `test_the_route_table_is_the_eighteen_routes_the_product_serves` counts paths, not methods; the two-query cursor-existence check in `read_scan_history` was flagged as lacking transactional consistency, but it is the same shape `api.audit.read_audit_log` already uses, accepted architecture this story extends rather than invents; a user hard-deleted mid-request between `require_claimed_user` resolving and the `scan` INSERT landing (an unhandled FK violation) was flagged, but this is a general TOCTOU race latent in every route that reads `user.id` after that dependency resolves, not specific to this story, and no source document asks for it to be closed here; `HistoryScreen` not special-casing a candidate image that 404s was flagged, but the spec's own Boundaries explicitly forbid adding that special-casing (`ResultsScreen`'s own established convention).

## Design Notes

**Why full DML grant on a table nothing here ever updates or deletes.** `test_audit_immutability.py::test_every_other_table_is_fully_granted` treats `audit_log` as the one exception, enforcing full `SELECT, INSERT, UPDATE, DELETE` on every other table in `public` so a forgotten grant fails loudly rather than silently. `scan`'s append-only behavior is this story's own design choice, not a PostgreSQL-enforced invariant the way AD-4 makes audit immutability -- nothing in FR-8 or this story's ACs asks for delete/update protection at the database level. Granting only `SELECT, INSERT` would be the locally "correct" grant and would fail an existing, unrelated test for a reason a reviewer would have to go looking for. Following the established "full DML unless the audit invariant applies" pattern is the correct call here, not a workaround.

**Why `GET /scans`, not a new path.** `POST /scans` already owns the concept "a Scan"; a same-path `GET` is a second verb on one resource. `DELETE /admin/users/{user_id}` (Story 1.11) already established that a method added to an existing path is not a new registration surface, and `test_the_route_table_is_the_eighteen_routes_the_product_serves` asserts on the set of paths, not methods -- so this needs no change to that assertion, though its narrative comment block is worth a short paragraph for the same reason every other route addition got one.

**Row-to-model mapping is the one place this read diverges from `read_audit_log`.** `AuditLogEntry.model_validate(row)` works directly because every column name matches a model field name. `scan`'s `candidates_snapshot` column and `ScanHistoryEntry.candidates` field do not share a name, so the route builds the model explicitly rather than reusing the bare `model_validate(row)` one-liner.

## Verification

**Commands:**
- `uv run --project shared/schema pytest shared/schema/tests/test_scan.py` -- expected: pass.
- `uv run --project apps/api pytest apps/api/tests/test_scan_submission.py apps/api/tests/test_scan_history.py apps/api/tests/test_audit_immutability.py apps/api/tests/test_no_registration.py` -- expected: pass (the last two confirm the new table's grant and the route table's path set are both still correct).
- `npm --prefix apps/web test -- --run history scan error-code-parity` -- expected: pass.
- `make migrate` -- expected: applies the new migration cleanly against a fresh database.
- `make lint` -- expected: clean (ruff + oxlint + tsc --noEmit).
- `make test` -- expected: full suite green.

## Auto Run Result

**Summary of implemented change:** Extended `submit_scan` (Story 3.4's `POST /scans`) to persist each successful match as one `scan` row — `user_id`, a `candidates_snapshot` JSON array byte-identical to the response body (including an empty array for "no confident match"), and a database-clock `created_at` — never for a refused submission. Added `GET /scans`, `require_claimed_user`-gated and keyset-paginated exactly like `GET /admin/audit`, but scoped to `WHERE user_id = %s` throughout (including the cursor-existence subquery) so a caller only ever sees their own history; a cursor naming no row of the caller's own answers `404`. Added the `ScanHistoryEntry` contract (Python + TS twin, parity-tested) and a new `scan` table (`user_id` FK `ON DELETE CASCADE`, full DML grant per this codebase's audit-immutability test convention). Added a `HistoryScreen` — a home-panel door beside Scan, reachable by every role — rendering each past scan's timestamp above its Candidate cards (reusing `ResultsScreen`'s card markup and `ImageViewer` tap-to-fullscreen behavior), with a verbatim "No scans yet." empty state and no special-casing for an image whose Tile was later removed.

**Files changed:**
- `infra/migrations/20260922T1900_create_scan.{up,down}.sql` (new) — the `scan` table, its `(user_id, created_at DESC, id DESC)` keyset index, and its full grant.
- `shared/schema/shared_schema/scan.py`, `ts/scan.ts` — `ScanHistoryEntry`, `HISTORY_PAGE_SIZE`, `HISTORY_CURSOR_PARAM`, both languages.
- `shared/schema/tests/test_scan.py` — `ScanHistoryEntry` round-trip, closed-shape, and parity coverage.
- `apps/api/api/scan.py` — persistence inside `submit_scan`; new `GET /scans` (`read_scan_history`), its three keyset statements, and the locally-scoped `SCAN_ENTRY_NOT_FOUND`/`NO_SUCH_SCAN_ENTRY` 404.
- `apps/api/tests/test_scan_submission.py` — persistence assertions (successful match, empty match, a refusal writes nothing).
- `apps/api/tests/test_scan_history.py` (new) — ordering, cross-user isolation, pagination, cursor-404 cases (including a cursor naming another user's own scan), auth, role coverage, AD-10 survival after a Tile removal, and the `ON DELETE CASCADE` cascade itself.
- `apps/web/src/screens/HistoryScreen.tsx`, `.module.css` (new) — the History surface.
- `apps/web/src/App.tsx`, `App.module.css` — the `'history'` section/screen and home-panel door.
- `apps/web/src/__tests__/history.test.tsx` (new) — the screen's full state machine, pagination, empty state, tap-to-fullscreen across all three dismissal gestures, and the AD-10 survival case rendered from stubbed data.
- `infra/tests/test_migrate.py`, `test_runner_unit.py` — updated for the eighth migration in the ledger (unplanned but required: adding a migration shifts these files' hard-coded step sequences and version list).

**Review findings breakdown:** 4 patched (0 high, 2 medium, 2 low — all fixed and re-verified: a docstring naming identifiers the code didn't actually define, a missing test for the `scan.user_id` cascade delete, a test title overstating its own coverage, and the AD-10 acceptance criterion's screen-surface reading left untested at that surface), 2 deferred (both low — CSS rule duplication inherited from `AuditLogScreen.module.css`'s own pre-existing pattern, and no test pinning a history card's image `src` to the reused route pattern, itself a pre-existing habit), 11 rejected (verified false, matching an established codebase precedent this story correctly followed, or explicitly out of scope by the spec's own stated Boundaries — see Review Triage Log for the full list).

**Follow-up review recommendation:** `true` — 2 medium + 2 low patched findings score `3×2 + 1×2 = 8`, at or above the 5-point bar.

**Verification performed:**
- `uv run --project shared/schema pytest shared/schema/tests/test_scan.py` — 27/27 pass, independently re-run and confirmed.
- `uv run --project apps/api pytest apps/api/tests/test_scan_submission.py apps/api/tests/test_scan_history.py apps/api/tests/test_audit_immutability.py apps/api/tests/test_no_registration.py` — all pass (`test_scan_history.py` now 22 tests), independently re-run and confirmed against a real ONNX model.
- `npm --prefix apps/web test -- --run history scan error-code-parity` — 134/134 pass, independently re-run and confirmed.
- `make migrate` — independently re-run against a fresh scratch PostgreSQL database (not reused from the implementation pass): applies cleanly; `scan` table schema, index and grants (`rocell_app=arwd`) verified by direct `\d`/`\dp` inspection to match the spec exactly.
- `make lint` — clean (ruff check, ruff format --check, oxlint, tsc --noEmit), independently re-run and confirmed.
- `make test` — full suite green: `uv run pytest` (apps/api + shared/schema + infra + scripts/ingest, real Postgres + real ONNX CPU inference) 1610/1610 pass; `apps/web`'s full vitest suite 1732/1732 pass across 29 files — both independently re-run to completion with no failures, before the patch pass added 3 more API tests and 3 more web tests, all confirmed passing afterward.
- I/O & Edge-Case Matrix audit: all seven rows covered by tests that ran and passed — the happy path, empty history, cross-user isolation, pagination, cursor-not-found, unauthenticated, and Tile-removal-survival rows are each named in `test_scan_history.py`, including the one `needs_model`-marked case, confirmed not skipped in the full suite run.

**Residual risks:**
- A user hard-deleted mid-request, between `require_claimed_user` resolving and the `scan` INSERT landing, would surface an unhandled foreign-key violation as a raw `500` — a narrow TOCTOU race shared by every route that reads `user.id` after that dependency resolves, not specific to this story and not asked for by any source document; worth closing product-wide if it is ever prioritized, not here.
- `HistoryScreen.module.css` restates `AuditLogScreen.module.css`'s own `.back`/`.retry`/`.more` duplication rather than introducing a shared base class — pre-existing CSS-module convention, deferred rather than fixed in this pass (see frontmatter `deferred`).
- No test pins a history card's image `src` to the `GET /tiles/{tile_id}/images/{image_id}` pattern directly; the boundary holds by code inspection (byte-identical to `ResultsScreen`'s own `imageSrc`), the same test-coverage habit `ResultsScreen` itself carries — deferred rather than fixed in this pass.
