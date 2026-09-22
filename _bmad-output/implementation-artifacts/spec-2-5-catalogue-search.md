---
title: 'Story 2.5 — Catalogue Search'
type: 'feature'
created: '2026-09-22'
baseline_revision: '87d032c74169146906de0059b26a4b5cf34cdada'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-4-bulk-upload.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Every Catalogue row downloads a full 1280px display derivative to fill a
      96px thumbnail, so browsing the whole catalogue is tens of megabytes.
    evidence: |-
      AD-17 generates one capped derivative (~1280px, ~300KB) at write time and
      forbids rendering anything on demand, and the list is deliberately
      uncapped, so a browse of a few hundred Tiles fetches a few hundred
      full-size derivatives. `loading="lazy"` defers the offscreen ones and
      nothing more. The size of that one derivative was chosen by Story 2.1 for
      the Edit Tile gallery; this story is the first surface that shows hundreds
      of them at 96px. A list-sized variant or a `?size=` parameter on the image
      route is an AD-17 decision, not a patch this story could make.
    location: >-
      apps/web/src/screens/CatalogueScreen.tsx thumbnails; shared/vision display_derivative
    severity: medium
  - summary: >-
      The one route that can export the whole catalogue in a single request is
      neither rate-limited nor recorded.
    evidence: |-
      `GET /admin/tiles` with a blank `q` answers every Tile's Code, Size and
      Category in one body. AGENTS.md names catalogue exfiltration through a
      compromised account as the primary commercial threat and mandates
      throttling on login and on scanning, but says nothing about admin reads,
      and FR-20 covers changes rather than reads -- which is why this story
      deliberately records nothing. Whether an Administrator's catalogue reads
      deserve the scan throttle, or an audit entry of their own, is a product
      and security decision worth settling before the pen test that gates
      rollout.
    location: >-
      apps/api/api/catalogue.py search_tiles
    severity: medium
  - summary: >-
      Two Administrators editing the same Tile silently overwrite each other --
      the edit path carries no optimistic-concurrency check.
    evidence: |-
      A Tile handed over by a Catalogue row is as old as the listing, and
      `PATCH /admin/tiles/{tile_id}` writes every column unconditionally with no
      `updated_at` precondition, so the second save wins and the first is lost
      with no warning. Pre-existing since Story 2.2 -- the lookup stage had the
      same staleness -- and surfaced here only because a row makes the gap
      between reading and saving longer and more ordinary.
    location: >-
      apps/api/api/catalogue.py edit_tile
    severity: medium
  - summary: >-
      Edit Tile's code-entry form can replace an in-progress edit without
      warning, dropping typed changes, queued files and pending removals.
    evidence: |-
      The lookup form is rendered above the edit form at all times, and a
      successful Find replaces the adopted Tile and every field with no
      confirmation. EXPERIENCE.md:90 says never to drop an in-progress
      catalogue edit silently. Pre-existing since Story 2.2, when the stage was
      the only entry point; this story did not change that behaviour.
    location: >-
      apps/web/src/screens/EditTileScreen.tsx lookup form
    severity: medium
  - summary: >-
      `session-expiry.test.tsx`'s 401 tests flake under CPU contention because
      they rely on the default 1000ms `findBy` timeout.
    evidence: |-
      Reproduced by running two full web suites concurrently: one of the two
      tests in `describe('a 401 from any request drops the app to the login
      screen')` times out at ~1015ms waiting for the login screen's password
      label. The same failure, in the same file, reproduces at baseline
      revision 87d032c74169146906de0059b26a4b5cf34cdada in a worktree built
      from that commit, so it predates this story. Fifteen consecutive
      standalone runs of that file pass, as do eight consecutive runs of the
      whole suite when nothing competes with it.
    location: >-
      apps/web/src/__tests__/session-expiry.test.tsx
    severity: low
---

<intent-contract>

## Intent

**Problem:** The catalogue has four write doors and no read door. Nothing in the product can list Tiles, and the only way to reach one is `GET /admin/tiles/lookup?code=` — an **exact** Code, one Tile or a `404`, which is why Edit Tile still opens with a code-entry stage and why `+ Add tile`, `Edit tile` and `Bulk upload` each stand as their own button on the home panel. An Administrator who remembers `CMA` but not `RP.CMA.0008DJ.SM.0T` cannot find the tile at all, and FR-18 asks for exactly that: search by Code with partial matches included.

**Approach:** One admin-only `GET /admin/tiles?q=` that matches substrings of the Code case-insensitively and answers a bare array of the same `Tile` contract the writes already return, images included; plus the Catalogue screen EXPERIENCE.md:35-37 names — a search box over the dense data-table row treatment the user list established, each row carrying its reference image, Code, Size and Category, and opening Edit Tile for that row. The three tile doors move off the home panel onto that surface, as `App.module.css:95-174` and `App.tsx:38-44` have said they would since Story 2.1.

## Boundaries & Constraints

**Always:**
- **Substrings of the Code, and nothing else** (FR-18, epic context). `q` matches `tile.code` case-insensitively and anywhere in the string. Size and Category are **displayed**, never searched, never filtered on, never grouped by — a `size + category` filter is the one query shape CLAUDE.md forbids outright.
- **A blank `q` browses the whole catalogue.** EXPERIENCE.md:35 is "Search/**browse** Tiles"; the screen opens on the full list and narrows from there.
- **The pattern is built on the parameter, never in the statement.** The statement text is a constant carrying `t.code ILIKE %s`; the `%`-wrapping and the escaping of `\`, `%` and `_` happen on the Python value. `tests/test_source_guards.py:237` fails on any SQL verb sharing a line with an f-string or a `+`.
- **The read is the `Tile` contract, unchanged** — `shared_schema.tile.Tile` with `reference_images`, serialized by `Tile`'s own model, in a **bare JSON array** with no cursor, total or page wrapper (`api/users.py:672-680`). No storage key and no URL ever crosses the wire (AD-9): a row's image is `GET /admin/tiles/{tile_id}/images/{image_id}`, which already exists.
- `require_administrator` on the route; it lives under `/admin/`. `NO_STORE` on the response. Parameterized SQL only; `catalogue.py` never names the audit table.
- **A read is not a catalogue change**, so nothing is recorded — `lookup_tile`'s own argument (`catalogue.py:2117-2119`): an entry per search would bury the entries FR-20 exists for.
- Domain vocabulary only: `Tile`, `Code`, `Size`, `Category`, `Reference image`. `Product`, `Face` and `Design` appear nowhere as a type, column, class, label or sentence. Two Tiles sharing a Size and Category are two rows, listed separately, never merged or deduplicated.
- **The Catalogue is the surface the tile doors live on** (EXPERIENCE.md:36-37, `App.module.css:102-104,123-131,147-160`): `+ Add Tile` takes the one accent fill on the screen, `Bulk upload` stands beside it outlined, and a row opens Edit Tile. The home panel keeps three admin doors — Users, Audit log, Catalogue.
- **Row click opens the tile** (EXPERIENCE.md:71) *and* a labelled row-end `Edit` control gives it a keyboard path — a row that can only be reached with a mouse fails the accessibility floor (EXPERIENCE.md:109-113).
- Empty search reads exactly `No tiles match — try a different code.` with no suggested alternatives (EXPERIENCE.md:91).

**Block If:**
- The substring search cannot be served by a sequential scan — i.e. something in the repo or the intent requires a trigram index, which needs a new `pg_trgm` extension and a migration. Read-only evidence below says it does not: the catalogue is 381 rows, `users.py:635-642` already set the "measure before reaching for pagination" precedent, and CLAUDE.md says measure before swapping storage.

**Never:**
- Do not delete or change `GET /admin/tiles/lookup`, `PATCH`/`DELETE /admin/tiles/{tile_id}`, `POST /admin/tiles`, `POST /admin/tiles/bulk` or the image route. Story 2.2's authorization AC names the lookup, and its own docstring's "this route can stay or go" is not a licence to remove a tested route inside a search story.
- Do not add a `LIMIT`, an `OFFSET`, a cursor, a page size, a sort parameter or a result cap. No new numeric bound means no new `BOUNDS` parity row; `q` is bounded by `MAX_CODE_LENGTH`, which already exists.
- Do not filter, facet or group by Size or Category, and do not add a Size or Category picker. Epic 3's proposed scan-side Size pre-filter is `[PROPOSED, PRD OQ-15]` and not adopted.
- Do not touch `shared/vision/`. This story reads metadata: no embedding, no preprocessing, no generation stamp check, no model pre-flight. **No re-index and no eval run is owed.**
- Do not add a `GET /admin/tiles/{tile_id}` detail route — the list already carries the whole `Tile`, and the row hands it to Edit Tile the way `App.tsx:473-508` hands a `User` to Edit User.
- Do not add removal to a catalogue row, a low-quality flag column, a face-number column, bulk selection, a sort control, an ORM, a router, a form library, a search library, a debounce utility or a new colour token.
- Do not weaken `EditTileScreen`'s existing code-entry stage, its refusals or its save path; the only change it takes is accepting a Tile it was handed.
- Do not implement `scripts/ingest`, Epic 3's scan endpoint, or a staff-facing lookup — FR-18 is Administrator-only as written and the staff question is open in `SPEC.md:94`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Substring match | Admin session; tiles `RP.CMA.0008DJ.SM.0T`, `RP.CMA.0011DJ.SM.0T`, `61M`; `?q=CMA` | `200`, a two-element array, both CMA Tiles, each with its `reference_images`, Size and Category | No error expected |
| Case-insensitive | `?q=cma` | The same two Tiles — matching folds case even though `clean_code` does not | No error expected |
| Blank query browses | `?q=` or no `q` at all | Every Tile in the catalogue, ordered by Code | No error expected |
| No match | `?q=ZZZZ` | `200` and an empty array — never a `404` | An empty result is not a refusal |
| Two tiles, one range | Two Codes differing only in their numeric segment, same Size and Category | Both rows returned, distinct `id`s, neither merged nor deduplicated | Never a conflict (AD-18) |
| Pattern metacharacters | `?q=%` or `?q=_` or `?q=\` | Treated as literal characters: an empty array unless a Code really contains them | Escaped on the parameter, never a wildcard |
| Unknown category | A Tile indexed against the `UNKNOWN` category row | Returned with `category: "UNKNOWN"`; the screen shows it as written | Never hidden from the list |
| Tile with several images | A Tile with three reference images | All three in `reference_images`, ordered `created_at, id`; the screen renders the first as the row's thumbnail | No error expected |
| Immediately listed | A Tile added or edited in the same session | Present in the next search, under its current Code, with no re-index step | No error expected |
| Removed tile | A Tile removed by `DELETE /admin/tiles/{id}` | Absent from every later search, whatever `q` is | Hard delete, no soft-delete filter to forget |
| Over-long query | `q` longer than `MAX_CODE_LENGTH` | `422` `invalid_query` envelope | Refused, not truncated |
| Control character in query | `q` containing `\x00` | `422` `invalid_query` envelope | Refused before psycopg can raise a `500` |
| Staff caller | Valid non-admin session | `403` `administrator_required`; no rows disclosed | Existing dependency |
| Signed-out caller | No session cookie | `401` `unauthorized` | Existing dependency |
| Uncacheable | Any answer, refusal or success | `cache-control: no-store` | Catalogue rows are not cached by a shared proxy |
| Audit | Any number of searches | No new audit entries at all | A read changes nothing (FR-20) |
| Screen — browse | Administrator opens Catalogue | The full list paints; each row shows thumbnail, Code, Size, Category and an `Edit` control | No error expected |
| Screen — search | Types `cma`, submits | Only matching rows remain; the request carried `q=cma` | No error expected |
| Screen — nothing matches | Search with no matches | `No tiles match — try a different code.` and no table | No suggestions offered |
| Screen — empty catalogue | Blank query, no tiles at all | `No tiles yet.` in the user list's register | Distinct from the no-match sentence |
| Screen — failed load | The server refuses or the network fails | The server's own sentence in one `role="alert"` element, plus a `Try again` control | `ApiRequestError.message`, else the unexpected sentence |
| Screen — stale answer | A second search resolves before the first | Only the latest answer is rendered | Generation guard, as on the user list |
| Screen — row opens the tile | Clicks a row, or its `Edit` control, or reaches it by keyboard | Edit Tile opens already showing that Tile, with no code to type; `Back` returns to the Catalogue | No error expected |
| Screen — staff user | A Staff session reaches the home panel | No Catalogue door, and forcing the section lands back on the panel | Server refuses regardless |

</intent-contract>

## Code Map

**API — the module being extended.** `apps/api/api/catalogue.py`, not a new module: the read helpers are private to it, `catalogue.router` is already registered (`main.py:189`), and `error-code-parity.test.ts:251-272` scrapes envelope codes from exactly four files of which this is one.

- `apps/api/api/catalogue.py:2092` `lookup_tile` -- the shape to follow end to end: `NO_STORE` first (`:2120`), `clean_code` then `_refusal(..., 422)` (`:2123-2127`), one statement, `Tile(...)` assembled from the row plus `_reference_images` (`:2133-2142`). Its docstring (`:2099-2109`) says the list "opens the same screen by id, and this route can stay or go" -- **that paragraph is part of this change, and the route is not.**
- `apps/api/api/catalogue.py:522` `_SELECT_TILE_BY_CODE` -- the exact-match twin, whose docstring (`:518-521`) names `LIKE`/`ILIKE`/`%` as this story's. **Do not widen it**; add a sibling `_SEARCH_TILES` with the same join shape (`JOIN tile_size s`, `LEFT JOIN tile_category c`, `s.name AS size`, `c.name AS category`), `WHERE t.code ILIKE %s`, `ORDER BY t.code`, and no `LIMIT`.
- `apps/api/api/catalogue.py:534` `_SELECT_TILE_IMAGES` + `:2030` `_reference_images` -- one Tile's images. A list of Tiles needs **one** statement, not one per row: add `_SEARCH_TILE_IMAGES` selecting `tile_id` alongside the `ReferenceImage` columns with `WHERE tile_id = ANY(%s) ORDER BY tile_id, created_at, id`, and group in Python. `ReferenceImage` is `extra="forbid"` (`shared/schema/shared_schema/tile.py:239`), so `tile_id` must be taken off the row before `model_validate`.
- `apps/api/api/catalogue.py:411` `_refusal`, `:408` `NO_SNIFF` (image route only), `api/dependencies.py:78` `NO_STORE`, `:193` `require_administrator` -- reuse as they stand.
- `apps/api/api/catalogue.py:171-203` -- the envelope-code block. **Add** `INVALID_QUERY = "invalid_query"` with its own comment, and its message constant beside the others (`:209-359`).
- `apps/api/api/catalogue.py:3-29` -- the module docstring's "Six routes and one function that is not a route" inventory, and `:111-117` "Not here, deliberately: the catalogue **list and substring search** (2.5)". **Both are part of this change.**
- `apps/api/api/db.py:167` `get_connection` -- declared as a dependency, as every non-streaming route does. `db.py:36,129` -- `row_factory=dict_row`, so rows are dicts.
- `apps/api/api/users.py:652-706` `list_users` -- the list precedent: only `response`, the role dependency and `conn`; `NO_STORE` at `:701`; a bare array built per row at `:706`; `:672-680` explains why there is no envelope and `:635-642` why there is no pagination. Follow it.
- `apps/api/api/audit.py:374-444` -- the *paged* precedent, and the one to **not** follow here: `:100-106` argues a caller-chosen page size is a DoS knob, which is why this story adds no bound at all rather than a settable one.

**Contract**
- `shared/schema/shared_schema/tile.py:146` `clean_code`, `:132` `_has_control_character` (whose docstring at `:140` already names "Story 2.5's catalogue list"), `:45` `MAX_CODE_LENGTH`. **Add** `clean_query(value: str) -> str` beside them: strip, `""` is legal and means browse-all, refuse over `MAX_CODE_LENGTH` and refuse control characters, `ValueError` carrying the sentence. A query is not a Code -- it is never uppercased and never required.
- `shared/schema/shared_schema/tile.py:258` `Tile`, `:224` `ReferenceImage` -- unchanged, and `extra="forbid"` on both (`:239`, `:267`) is why the list adds no field of its own.
- `shared/schema/shared_schema/ts/tile.ts:108` `TILE_KEYS`, `:168` `isTile` -- unchanged; `isTile` is the structural guard the screen runs over every row. **No TS twin for `clean_query`**: the server owns the rule, the client sends what was typed.

**Schema (read-only evidence — no migration)**
- `infra/migrations/20260921T1500_create_catalogue.up.sql:96` -- `code text NOT NULL UNIQUE`; `:115-117` -- the comment that already anticipates "Story 2.5 searches substrings of the Code"; `:118-119` -- the Size and Category indexes. **The only index on `code` is the unique btree, and an unanchored `ILIKE` cannot use it**: this is a sequential scan over 381 rows and is meant to be. `:58` -- `vector` is the only extension any migration enables; **no `pg_trgm`, and this story adds none**. `:232-237` -- `rocell_app` already holds `SELECT` on all six tables, so there is no DDL and no grant to write.

**Web**
- `apps/web/src/screens/UserListScreen.tsx` -- the screen to model on: the `Listing` union (`:98-101`), `asUsers` and its `MALFORMED_RESPONSE` throw (`:112-118`), the `inFlight` re-entrancy ref (`:327`), the `generation` stale-answer ref (`:365`), `load` (`:367-395`), the mount effect (`:397-403`), `retry` (`:414-425`), the title as focus rescue target (`:343`, `:354`), `role="status"` for loading (`:504-508`), the single `role="alert"` failure element (`:516`), the empty sentence (`:526-527`), the `role="region"` scroller and why one `<table>` serves every width (`:529-542`), `<th scope="col">` headers (`:544-568`), `.row`/`.cell` rows keyed by id (`:593-598`), and the labelled row-end controls that are deliberately **not** on the `<tr>` (`:616-678`). Its own docstring (`:266-292`) says "FR-18's search is catalogue search and belongs to Epic 2" -- leave that sentence true by building it here, not there.
- `apps/web/src/screens/UserListScreen.module.css` -- the recipe to copy class for class: `.screen` 17, `.title` 23, `.actions` 34, `.add` 44 (the accent fill), `.back` 60, `.pending` 75, `.failure` 83, `.error` 93, `.retry` 101, `.empty` 116, `.scroller` 126, `.table` 131, `.heading` 140, `.row` 153 with `:hover` 159, `.cell` 178, `.rowActions` 241, `.edit` 256.
- `apps/web/src/screens/EditTileScreen.tsx:819-874` -- the thumbnail recipe: `<img src={`${API_PREFIX}/admin/tiles/${tile.id}/images/${image.id}`}>` against the proxy route (`:82-86` states AD-9: proxied, never linked), `asTile` (`:236-245`), `API_PREFIX` (`:5`), and the `URLSearchParams` query-string precedent (`:390`). **Change:** `:247` takes `{ onBack }` only -- add an optional `tile` prop that is adopted as the starting Tile, and revise the docstring's `:38-45` two-stage paragraph and `:98-99` "No catalogue list and no substring search. Story 2.5's."
- `apps/web/src/screens/EditTileScreen.module.css` -- `.gallery` 196, `.thumb` 205, `.image` 226 (`aspect-ratio: 1`, `object-fit: contain`, `--thumbnail-size`): the row thumbnail reuses these values through its own class, since a CSS module is not shared.
- `apps/web/src/api/client.ts:562-643` `apiRequest` -- unchanged; the list is one `GET` returning JSON. `:404-414` `ApiRequestError`, `:448-459` `failed`, `:524-560` `refusal` and its 401 hook. `:184-373` -- the envelope-code export block; **add** `INVALID_QUERY` with a doc block in the Story 2.1-2.4 style.
- `apps/web/src/App.tsx` -- `Section` (`:46-55`, docstring `:24-45` whose `:27` says "Nine values"; `:38-44` is the paragraph that anticipates this surface), `Screen` (`:69-81`, docstring `:57-68` whose `:58` says "twelve screens"), `reachableBy` (`:94-107`), `currentScreen` (`:109-149`, whose `:139-147` `edit-user` branch is the exact precedent for an entity-keyed screen), the `editing` state (`:175-184`), `showSection` (`:346-367`), `showEditUser` (`:369-378` -- row first, then section), the Edit User render branch (`:473-508` -- `key={editing.id}` plus a `user` prop plus Back to the list), the add-tile (`:426-440`), edit-tile (`:442-454`) and bulk-upload (`:456-471`) branches whose comments say Back will return to the Catalogue, and the admin door block (`:551-575` comment, `:576-610` buttons).
- `apps/web/src/App.module.css` -- `.userList` 55, `.auditLog` 80, and the three rules this story **removes with their comments**: `.addTile` 108 (`95-107`: "will take the accent when Story 2.5 builds that surface and this door moves onto it"), `.editTile` 132 (`123-131`: "becomes a row-end control there"), `.bulkUpload` 161 (`147-160`: "moves onto it as a secondary control beside '+ Add Tile'"). One `.catalogue` rule replaces them, written longhand in the same outlined recipe. The file must still hold zero `var(--color-accent)`.
- `apps/web/src/styles/tokens.css` -- `--color-accent` 26, `--color-primary` 24, `--color-border` 32, `--color-muted-text` 36, `--thumbnail-size` 128, `--touch-target-min` 116, `--space-2`/`-3` 91-92 (DESIGN.md:190's density split). **No token is added** -- `tokens.test.ts:115` pins exactly eleven colours and reads DESIGN.md's frontmatter.

**Tests that fail unless they are extended**
- `apps/api/tests/test_admin_authorization.py:546` -- the count **is in the test name**: `..._thirteen_routes...` becomes fourteen. `:578-594` -- the literal route list gains `f"GET {ADD_TILE}"` (the path constant at `:94` already exists; `GET` on it is new). `:597-632` -- the lookup-segment ordering test stays green because the new route takes **no path parameter**; extend its comment to say why rather than leaving the reader to re-derive it.
- `apps/api/tests/test_no_registration.py:251-268` -- `/admin/tiles` is already in the path set, so this stays green: it compares paths, not methods. Do not add a duplicate entry.
- `apps/api/tests/test_catalogue_authorization.py:48-50,225,322,384` -- the staff, signed-out and uncacheable refusals; add the search route to each, asserting no row is disclosed.
- `apps/api/tests/test_source_guards.py:237` -- no SQL verb on a line with an f-string or concatenation; `:339` -- `catalogue.py` may not so much as name `audit_log`.
- `apps/api/tests/test_user_list.py:371,381,391,417` -- the statement-text guards to mirror **inverted**: the search statement *does* carry a `WHERE`, and must carry no `LIMIT`, `OFFSET` or `FETCH`, and its selected columns must still cover `Tile`'s fields.
- `apps/api/tests/test_tile_lookup.py:30-58` -- the fixture vocabulary to reuse (`needs_model`, `an_image`, `administrator`, `add`, `CODE`), and the suite that must stay green: the lookup is unchanged.
- `apps/api/tests/conftest.py:194,208,255,345` -- `conn`, `app_role_conn` (prove the read works under the app grant), `audit_rows` (prove a search records nothing), `client`.
- `apps/web/src/__tests__/styling-wiring.test.ts:1075` -- the admin-door list becomes `['.userList', '.auditLog', '.catalogue']`; `:1058-1072` is the comment to re-narrate; `:1084` still requires zero accent in `App.module.css`. `:373-388` -- the rejection-colour matrix gains a Catalogue row. `:154-188` -- every class in the new CSS module must be referenced by its sibling `.tsx`, and every reference must resolve. A new per-screen `describe` beside `:1088` must assert `+ Add Tile` is the **one** accent-filled control and that `Bulk upload`, `Search`, `Back`, `Try again` and the row-end `Edit` are outlined.
- `apps/web/src/__tests__/error-code-parity.test.ts:125-169` -- the `PYTHON` map gains `invalid_query`, and `:137`'s count narration moves on; `:171-202` -- the `TYPESCRIPT` mirror; `:224-248` -- every `export const` in `client.ts` must appear in a map or the exemption set. **No `BOUNDS` row**: this story adds no numeric bound.
- `apps/web/src/__tests__/no-raw-values.test.ts` -- picks new files up automatically; `:264-286` fails on a `var(--…)` the token layer does not declare.
- `apps/web/src/__tests__/user-list.test.tsx:120-151` `stubFetch` (keyed on the full `/api/...` URL), `:153-185` `stubDeferred`, `:192-195` `refusal`, `:214-220` `rowFor`, and `:636-681` the "exactly the controls it is meant to have" discipline -- the conventions the new suite copies. `:757-772` asserts the **user list** offers no search box; leave it alone.
- `apps/web/src/__tests__/bulk-upload.test.tsx:836-842` -- the "renders no main landmark of its own" test to copy; `:846` -- its home-panel door block, which must be retargeted to the Catalogue. Same for `apps/web/src/__tests__/add-tile.test.tsx:641` and `apps/web/src/__tests__/edit-tile.test.tsx:1647-1691`.
- `apps/web/src/__tests__/tile-contract.test.ts:37-49` -- `aTile()`'s literals (`RP.CMA.0001DJ.SM.0T`, `45X90`, `CREMA MARMOL`) to reuse as fixtures; the contract itself does not change.

**Read-only evidence**
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md:53` -- FR-18: "Search/filter by Code; partial matches included, not just exact. Administrator-only as written"; `SPEC.md:94` -- the staff lookup is an **open question**, not this story.
- `EXPERIENCE.md:35` (Catalogue: nav, Admin, search/browse), `:36-37` (Add/Edit Tile from a row or `+ Add Tile`; Bulk Upload from the Catalogue), `:71` (dense data-table row, row click opens detail), `:91` (the empty-search sentence, verbatim), `:109-113` (44px targets, visible focus, never colour-only), `:153` (denser admin tables).
- `DESIGN.md:107,212` -- `data-table-row`: surface background, background-on-hover, hairline borders, no card wrapper; `:190` -- `{spacing.2}`-`{spacing.3}` within admin table rows; `:208` -- the Card fallback below the table breakpoint, which `UserListScreen.tsx:529-536` deliberately answers with one table and a scroller at every width.
- `apps/web/vite.config.ts` -- `css: false` in the test config, which is why class assertions compare module **keys** (`user-list.test.tsx:27-31`).

## Tasks & Acceptance

**Execution:**
- `shared/schema/shared_schema/tile.py` -- add `clean_query(value: str) -> str` beside `clean_code`: strip, allow `""` as browse-all, refuse over `MAX_CODE_LENGTH` and refuse control characters, with a docstring saying why a query is neither uppercased nor required -- the Code rules live in one module and a search rule is one of them.
- `shared/schema/tests/test_tile.py` -- extend: `clean_query` accepts a blank query, a lowercase fragment and a Code-length query; refuses one character over the bound and refuses `\x00`; and never folds case -- the NUL case is the one that would otherwise surface as a `500`.
- `apps/api/api/catalogue.py` -- add `INVALID_QUERY` and its message; add `_SEARCH_TILES` and `_SEARCH_TILE_IMAGES` as constant statements; add a private pattern helper that escapes `\`, `%`, `_` and wraps the query in `%`; add `GET /admin/tiles` (`search_tiles`) declaring `require_administrator` and `get_connection`, setting `NO_STORE`, refusing an invalid `q` with `422`, and returning `list[Tile]` assembled from two statements with the images grouped in Python; and rewrite the module docstring's route inventory (`:3-29`) and its "not here, deliberately" paragraph (`:111-117`), and `lookup_tile`'s "until 2.5" paragraph (`:2099-2109`) -- the prose is load-bearing and names this story as absent.
- `apps/api/tests/test_catalogue_search.py` -- new; every row of the I/O matrix through the real route, including the metacharacter cases, the two-tiles-one-range case, the `UNKNOWN` category, a removed Tile's absence, an added Tile's immediate presence, no audit entry written, the answer readable under `app_role_conn`'s grant, and statement-text assertions that `_SEARCH_TILES` carries a `WHERE` and no `LIMIT`/`OFFSET`/`FETCH`.
- `apps/api/tests/test_catalogue_authorization.py` -- extend with the staff and signed-out refusals on `GET /admin/tiles`, each asserting nothing was disclosed, plus the uncacheable assertion -- a UI that hides a door is not authorization (AGENTS.md Policy).
- `apps/api/tests/test_admin_authorization.py` -- add `f"GET {ADD_TILE}"` to the route list, rename the test to `fourteen`, and extend both the list comment and the lookup-ordering comment with why a parameterless `GET` cannot shadow `lookup` -- the number in the name may never drift from the list.
- `apps/web/src/api/client.ts` -- export `INVALID_QUERY` with a doc block naming who renders it -- the parity contract requires the export, and the screen shows the server's own sentence.
- `apps/web/src/screens/CatalogueScreen.tsx` -- new; a `role="search"` form with a searchbox and an outlined `Search` submit over the user list's three-state `Listing`, `inFlight` and `generation` discipline; `+ Add Tile` as the single accent control, `Bulk upload` and `Back` outlined; a `role="region"` scroller holding one table with `Reference image`, `Code`, `Size`, `Category` and `Actions` columns; rows keyed by tile id, hover-lit, click-to-open, each with a lazily loaded proxied thumbnail, an `alt` naming the Code, and a labelled `Edit` row-end control carrying the keyboard path; `role="status"` while loading, one `role="alert"` on failure with `Try again`, and the two empty sentences -- this is FR-18's surface and the row is the door to Edit Tile.
- `apps/web/src/screens/CatalogueScreen.module.css` -- new; `UserListScreen.module.css`'s flat single-class recipe plus the thumbnail values from `EditTileScreen.module.css:226-232`, tokens only, no class declared that the screen does not use.
- `apps/web/src/screens/EditTileScreen.tsx` -- accept an optional `tile` prop, adopt it as the starting Tile so a row opens straight onto the edit stage, and revise the two-stage and "no catalogue list" paragraphs of its docstring -- the code-entry stage stays for the Tile nobody handed it.
- `apps/web/src/App.tsx` -- add the `catalogue` `Section` and `Screen` with their `reachableBy` and `currentScreen` arms, an `editingTile` state set row-first the way `showEditUser` sets `editing`, an `edit-tile` branch that falls back to the Catalogue when no Tile is held, the render branch passing `key={editingTile.id}` and the four Catalogue callbacks, `Back` from Add Tile, Bulk Upload and Edit Tile returning to the Catalogue, the home panel's three tile doors replaced by one `Catalogue` door, and both docstring counts corrected -- a screen with no door is unreachable and the counts are load-bearing prose.
- `apps/web/src/App.module.css` -- remove `.addTile`, `.editTile` and `.bulkUpload` with their comments and add `.catalogue` in the same outlined longhand recipe -- three doors became controls on the surface this story builds.
- `apps/web/src/__tests__/catalogue.test.tsx` -- new; the request carries `q`, a stubbed list paints rows in order with their thumbnails and their Size and Category, a search narrows them, the two empty sentences appear in their own cases, a refusal renders the server's sentence in one alert with a working `Try again`, a stale answer is discarded, a row and its `Edit` control both open the tile, the screen renders no `<main>` of its own, and it has exactly the controls it is meant to have.
- `apps/web/src/__tests__/edit-tile.test.tsx` -- extend: a Tile passed as a prop opens on the edit stage with no code to type and no lookup request made, the code-entry stage still works when no Tile is passed, and retarget the home-panel door block to the Catalogue row.
- `apps/web/src/__tests__/add-tile.test.tsx` + `bulk-upload.test.tsx` -- retarget each door block: both screens are now reached from the Catalogue and `Back` returns there.
- `apps/web/src/__tests__/styling-wiring.test.ts` + `error-code-parity.test.ts` -- extend both exactly as the Code Map itemises -- these are the suites that fail by design when a screen, a route or a code is added.

**Acceptance Criteria:**
- Given an authenticated Administrator and a catalogue holding Tiles whose Codes share a fragment, when they search that fragment in any case, then every Tile whose Code contains it is returned — each with its Size, its Category and its reference images — and no Tile whose Code does not contain it is, with Size and Category never consulted as filters.
- Given a Tile added, edited or removed in the same session, when the Administrator searches afterwards, then the list reflects that change immediately — the new or renamed Tile is present under its current Code and the removed one is absent — with no re-index step and no cache to clear.
- Given a query that is blank, when it is submitted, then the whole catalogue is browsed rather than nothing being returned; and given a query nothing matches, then the answer is an empty list under `200`, never a `404`.
- Given any non-Administrator or signed-out caller, when they call the search route, then the server refuses with `403` or `401` regardless of what the UI renders, no catalogue row is disclosed, and the refusal is uncacheable.
- Given a query over the Code length bound or carrying a control character, when it is submitted, then the response is a single `{"error": {...}}` envelope under `422` and no row is returned; and given any search at all, then no audit entry is written, because a read changes nothing.
- Given the Catalogue screen, when it opens, then it lists Tiles in the dense data-table treatment the user list established, each row carrying its reference image through the authenticated proxy route with no storage URL anywhere in the payload or the DOM, and the empty-search state reads `No tiles match — try a different code.` with no suggested alternatives.
- Given a row on the Catalogue, when the Administrator clicks it or activates its `Edit` control by keyboard, then Edit Tile opens already showing that Tile with no Code to type, and `Back` returns to the Catalogue with the search still in place.
- Given the Catalogue screen, when it is added, then `+ Add Tile` is the only accent-filled control on it, `Bulk upload` stands beside it as an outlined secondary control, the screen renders no `<main>` of its own, it is reachable only by an Administrator through the one outlined `Catalogue` door that replaced the three tile doors, every interactive element is keyboard-reachable with a visible focus state and a 44px target, and no raw colour or dimension literal appears outside the token layer.
- Given `shared/vision/`, when this story is complete, then not one line of it has changed, so no re-index and no eval run is owed; and no migration, no extension and no index was added.
- Given `make lint` and `make test`, when run from a clean tree, then both pass, with the catalogue tests exercised (not skipped) when the model artifact is present.

## Spec Change Log

## Review Triage Log

### 2026-09-22 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 14: (high 0, medium 2, low 12)
- defer: 5: (high 0, medium 4, low 1)
- reject: 6: (high 0, medium 0, low 6)
- addressed_findings:
  - `[medium]` `[patch]` The search was discarded on every `Back`, against the acceptance criterion that says it stays in place — the query now lives in `Gate` as `catalogueQuery` and the Catalogue's mount load runs it, so a return from Add, Edit or Bulk refetches *that* search rather than browsing everything.
  - `[medium]` `[patch]` Removing a Tile opened from a row left the Administrator on Edit Tile's code-entry stage for a Tile that no longer existed — a confirmed removal on a handed-over Tile now returns to the Catalogue, while the lookup-seeded path keeps its documented behaviour.
  - `[low]` `[patch]` The empty-state sentence branched on the live input, so clearing the box after a failed search claimed the catalogue was empty; every `Listing` now carries the query that produced it.
  - `[low]` `[patch]` A `null` Category rendered as a blank cell; the sentinel is rendered explicitly and fixtured.
  - `[low]` `[patch]` A search submitted while a request was open was silently swallowed; a newer submit now supersedes, the `generation` doc block states what it really guards, and the Search control no longer refuses a click that Enter would have honoured.
  - `[low]` `[patch]` `retry()` pulled focus before checking whether it would do anything; the guard moved above the focus call.
  - `[low]` `[patch]` The whole-row click fired at the end of a drag-selection, navigating away from a Code being copied; the row stands down while a selection is open.
  - `[low]` `[patch]` The ordering test asserted Python's codepoint order as though it were the database's collation; it now asserts stability and completeness over mixed-case, dotted, spaced and dash-delimited Codes.
  - `[low]` `[patch]` Every metacharacter test was `@needs_model`, so a run without the artifact proved nothing about Postgres treating an escaped `%` or `_` literally; one test now seeds its rows directly and runs unconditionally.
  - `[low]` `[patch]` The status region was unmounted once the answer landed, so a screen-reader user who searched heard nothing; one persistent `role="status"` now carries the outcome.
  - `[low]` `[patch]` Three comments this story left stale — Edit Tile's "a later story", App's "four catalogue ones", and the inverted claim about which `editingTile` branch is unreachable — corrected.
  - `[low]` `[patch]` `showEditTile` and `showEditUser` left the other entity selection set, against the invariant `showSection` states; each clears the other.
  - `[low]` `[patch]` The new "is told nothing" authorization tests ran against an empty table, so their disclosure assertions would have passed with the guard removed; both twins now seed a real Tile and assert its Code is absent.
  - `[low]` `[patch]` `lookup_tile`'s and `EditTileScreen`'s new docstrings claimed the code-entry stage is still reached as an entry point, which the `editingTile` guard makes false; both now state what is actually true and why the route is retained.

## Design Notes

**Why a bare array with no pagination, no cursor and no cap.** The catalogue is 381 files today and the whole product's index is sized at ~10k vectors, which is ~600 Tiles at sixteen views each — so the largest answer this route can give is a few hundred rows of short text plus their image ids. `api/users.py:635-642` already argued this once and `CLAUDE.md` says measure before reaching for a bigger mechanism. A cap would need a number, a TypeScript twin, a `BOUNDS` parity row and a "showing the first N" sentence that lies as soon as someone narrows the search; a caller-settable `limit` is the DoS knob `audit.py:100-106` refuses. The honest version is: every match, ordered by Code, and a note in the docstring saying what would change the answer.

**Why `ILIKE` on a sequential scan, and why that is not a shortcut.** The only index on `tile.code` is the unique btree from the migration, and an unanchored pattern cannot use it in any collation. A trigram index would mean `CREATE EXTENSION pg_trgm` in a new migration — a new database dependency for a table with a few hundred rows. The statement is a constant with `t.code ILIKE %s`; the wrapping and the escaping of `\`, `%` and `_` happen on the parameter, which keeps `test_source_guards.py:237` satisfied and makes a search for `%` mean the character rather than "everything".

**Why two statements and not one join, and not `_reference_images` per row.** A join would return one row per image and the Tile's columns repeated, which then has to be un-repeated in Python; calling `_reference_images` per Tile is a few hundred round trips on one pooled connection. Two statements — the Tiles, then their images by `tile_id = ANY(%s)` — keep both shapes flat:

```python
tiles = conn.execute(_SEARCH_TILES, (_pattern(wanted),)).fetchall()
images: dict[UUID, list[ReferenceImage]] = {}
for row in conn.execute(_SEARCH_TILE_IMAGES, ([tile["id"] for tile in tiles],)):
    images.setdefault(row.pop("tile_id"), []).append(ReferenceImage.model_validate(row))
```

`ReferenceImage` forbids extra keys, so `tile_id` comes off the row before validation; a Tile with no surviving image gets an empty list rather than a `KeyError`.

**Why the row opens Edit Tile with a Tile rather than an id.** `App.tsx:473-508` already hands Edit User a whole `User` with `key={editing.id}`, and the search answer is the whole `Tile` — fetching it again by id would add a route (`GET /admin/tiles/{tile_id}`) that nothing else needs and that `test_admin_authorization.py:597` would have to be taught to order around. `EditTileScreen`'s code-entry stage stays and keeps its suite: it is what a Tile nobody handed the screen still needs, Story 2.2's authorization AC names the lookup route it calls, and deleting a tested route inside a search story is a separate decision with its own review.

**Why the three doors move.** `App.module.css:95-107`, `:123-131` and `:147-160` were written by Stories 2.1, 2.2 and 2.4 to say what this story does with them: `+ Add Tile` takes the accent on the Catalogue, `Bulk upload` stands beside it outlined, and `Edit tile` becomes a row-end control. Leaving all three on the home panel beside a fourth Catalogue door would ship two ways to reach the same screen and a panel that contradicts EXPERIENCE.md:36-37.

**Why the row is clickable *and* carries a labelled control.** EXPERIENCE.md:71 asks for row click; EXPERIENCE.md:109-113 requires a keyboard path and a visible focus state on every interactive element, and `UserListScreen.tsx:617-622` refused to put the handler on the `<tr>` for exactly that reason. Both hold here: the `<tr>` takes the click as a mouse convenience, and the row-end `Edit` button — which stops the event from reaching the row — is the accessible, focusable, 44px path to the same action.

## Verification

**Commands:**
- `make lint` -- expected: ruff check, ruff format --check, oxlint and `tsc --noEmit` all clean.
- `uv run --project shared/schema pytest shared/schema/tests/test_tile.py -q` -- expected: green, including the new `clean_query` cases.
- `uv run --project apps/api pytest apps/api/tests/test_catalogue_search.py apps/api/tests/test_catalogue_authorization.py apps/api/tests/test_tile_lookup.py apps/api/tests/test_admin_authorization.py apps/api/tests/test_no_registration.py apps/api/tests/test_source_guards.py apps/api/tests/test_catalogue_audit.py -q` -- expected: green, with nothing reporting `skipped` for a missing model.
- `npm --prefix apps/web test -- --run catalogue edit-tile add-tile bulk-upload styling-wiring error-code-parity no-raw-values tokens app-shell auth-gating user-list tile-contract` -- expected: green.
- `make test` -- expected: the whole workspace green. Run it in partitions if one command exceeds the session's command ceiling, and say so.

**Manual checks (if no CLI):**
- `git status --porcelain` is empty of stray artifacts after a run, and `git diff --stat -- shared/vision` is empty -- a change there would owe a re-index and an eval run.

## Auto Run Result

Status: done

**Summary.** FR-18's catalogue search, end to end. `GET /admin/tiles?q=` matches substrings of the Code case-insensitively and answers a bare array of the existing `Tile` contract with its reference images; a blank query browses the whole catalogue. The Catalogue screen EXPERIENCE.md names is the surface: a search box over the user list's dense data-table treatment, each row carrying its proxied reference image, Code, Size and Category and opening Edit Tile for that row. The three tile doors left the home panel for it, as `App.module.css` and `App.tsx` had said since Story 2.1 they would: `+ Add Tile` takes the one accent there, `Bulk upload` stands beside it outlined, and `Edit tile` became a row-end control. No migration, no extension, no index, and `shared/vision/` is untouched — **no re-index and no eval run is owed**.

**Files changed**

- `shared/schema/shared_schema/tile.py` -- `clean_query`: strips, accepts blank as browse-all, refuses over `MAX_CODE_LENGTH` and refuses control characters.
- `shared/schema/tests/test_tile.py` -- `clean_query`'s cases, including the NUL that would otherwise have surfaced as a `500`.
- `apps/api/api/catalogue.py` -- `INVALID_QUERY` and its sentence; `_SEARCH_TILES` and `_SEARCH_TILE_IMAGES`; `_pattern`, which escapes `\`, `%` and `_` on the parameter and never in the statement; `GET /admin/tiles` (`search_tiles`); and the module docstring's route inventory, its "not here, deliberately" paragraph and `lookup_tile`'s "until 2.5" paragraph rewritten.
- `apps/api/tests/test_catalogue_search.py` -- new; every I/O-matrix row plus the statement-text guards and a model-free metacharacter test.
- `apps/api/tests/test_catalogue_authorization.py` -- the staff, signed-out and uncacheable refusals on the new route, seeded with a real Tile so "nothing was disclosed" is a claim about the guard.
- `apps/api/tests/test_admin_authorization.py` -- `GET /admin/tiles` in the route table, the count in the test name moved to fourteen, and both comments extended.
- `apps/web/src/api/client.ts` -- `INVALID_QUERY` exported with its doc block.
- `apps/web/src/screens/CatalogueScreen.tsx` + `.module.css` -- new; the search form, the table, the thumbnails, the two empty sentences, one persistent live region, and the row that opens a Tile by click or by a labelled keyboard-reachable `Edit`.
- `apps/web/src/screens/EditTileScreen.tsx` -- accepts a handed-over `tile` as initial state and an `onRemoved` for the row-opened path; docstring corrected.
- `apps/web/src/App.tsx` + `App.module.css` -- the `catalogue` section and screen, `editingTile`, `catalogueQuery`, Back from Add/Edit/Bulk returning to the Catalogue, three doors replaced by one, and both docstring counts corrected.
- `apps/web/src/__tests__/catalogue.test.tsx` -- new; the screen and its door, including the search surviving a round trip through a row.
- `apps/web/src/__tests__/edit-tile.test.tsx`, `add-tile.test.tsx`, `bulk-upload.test.tsx` -- the handed-over-Tile path, and each door block retargeted to the Catalogue.
- `apps/web/src/__tests__/styling-wiring.test.ts`, `error-code-parity.test.ts` -- the door list, the rejection matrix, the new per-screen block, and `invalid_query` on both sides of the parity map.

**Review findings breakdown**

- Patches applied: 14 (high 0, medium 2, low 12). The two mediums were the search being discarded on `Back` — the one acceptance criterion the first pass missed — and a removal from a row dead-ending on Edit Tile's code-entry stage. The twelve lows were an empty-state sentence that branched on the live input, an unguarded nullable Category, a silently swallowed submit, a focus pull before a no-op retry, a row click that fired at the end of a drag-selection, an ordering test asserting Python's collation, a metacharacter guarantee that vanished without the model artifact, an unmounted live region, three stale comments, two uncleared entity selections, two vacuous disclosure assertions, and two docstrings that over-claimed the lookup's reachability.
- Deferred: 5 — full-size derivatives behind 96px thumbnails (an AD-17 decision), the unthrottled and unrecorded whole-catalogue read, no optimistic concurrency on tile edits, Edit Tile's lookup replacing an in-progress edit, and `session-expiry.test.tsx`'s pre-existing flake under CPU contention. All five are recorded in frontmatter `deferred`.
- Rejected: 6, all low. The substantial ones and why: no `maxLength` mirrored onto the search box (the spec forbade a new `BOUNDS` parity row, and the server's refusal is tested on both sides); `INVALID_QUERY` exported without the screen branching on it (the parity contract requires the export and the screen renders that refusal's own sentence, which is Story 2.4's accepted precedent); a broken-image glyph if a thumbnail 404s between the list and the fetch (the window needs a concurrent removal and the row still reads); no key event driving the row-end `Edit` in tests (it is a real `<button>`); 44px and focus not restated per screen (`global.css` sets both and `styling-wiring.test.ts` forbids restating them per module); `sprint-status.yaml` and the deferred-work ledger not updated (orchestration-owned — this run may not write them).

**Follow-up review recommendation:** `true`. Patched this pass: high 0, medium 2, low 12. Score = 3x2 + 1x12 = 18, which is 5 or more.

**Verification performed**

- `make lint` -- green (ruff check, ruff format --check over 89 files, oxlint, `tsc --noEmit`).
- `uv run --project shared/schema pytest shared/schema/tests/test_tile.py -q` -- 48 passed.
- The spec's API command over the catalogue, authorization, lookup, route-table, registration, source-guard and audit suites -- 187 passed, nothing skipped for a missing model.
- `npm --prefix apps/web test -- --run` -- 25 files, 1503 tests passed, confirmed over eight consecutive clean runs.
- Every remaining API test file was run in partitions covering all forty of them -- 280, 275, 244, 134 and 107 passed across five partitions before the patch pass, and the three files the patch pass touched were re-run in the 187 above. `make test` was not used as one command: the full workspace suite runs past this session's ten-minute command ceiling.
- `uv run pytest shared/schema/tests infra/tests scripts/ingest/tests tests` -- 351 passed; `uv run pytest shared/vision/tests` -- 43 passed.
- Matrix test audit: every row of the I/O & Edge-Case Matrix maps to at least one test that ran and passed, none skipped.
- `git diff --stat -- shared/vision` is empty, and no migration, extension or index was added.

**Residual risks**

- One web test flakes under CPU contention -- `session-expiry.test.tsx`'s 401 tests, on the default 1000ms `findBy` timeout. It is not this story's: the same failure in the same file reproduces in a worktree built from `87d032c74169146906de0059b26a4b5cf34cdada`, and fifteen standalone runs of that file pass. Recorded as deferred.
- The search is a sequential scan by design. Correct at 381 rows and at the ~600-Tile scale the index is sized for; the answer past that is to measure before reaching for `pg_trgm`, and the statement's own comment says so.
- The image bytes, not the JSON, are what a full browse costs. The row count argument the spec makes for no pagination was never an argument about derivative bytes, which is the first deferred item.
- `EditTileScreen`'s code-entry stage is no longer an entry point -- nothing in the app opens that screen without a Tile. It remains as the post-404 fallback, and `GET /admin/tiles/lookup` is retained because Story 2.2's authorization criterion names it. Both docstrings now say exactly that rather than claiming a door that no longer exists.
