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
  - summary: >-
      The three session-state authorization claims on the Catalogue are pinned
      on the add alone, so no other catalogue route proves them.
    evidence: |-
      `test_an_administrator_on_an_unclaimed_temporary_credential_is_refused`,
      `..._deactivated_mid_session_is_refused_as_unauthenticated` and
      `..._demoted_mid_session_is_refused_on_the_next_request` all send
      `post_tile` and nothing else, while the file's own
      `test_every_refusal_is_uncacheable` is parametrized across all seven
      routes. The claims hold today because `require_administrator` is one
      shared dependency, but that is the thing being asserted -- a route that
      ever declared its guard itself would be caught on the add and nowhere
      else, and `GET /admin/tiles` is the route where a stale role discloses
      the whole catalogue in one body. Pre-existing since Story 2.1; Story 2.5
      added the seventh route to the parametrized test and left these three
      unchanged, which is where the asymmetry became visible.
    location: >-
      apps/api/tests/test_catalogue_authorization.py:441-487
    severity: low
  - summary: >-
      A row's thumbnail that fails to load renders the browser's broken-image
      glyph instead of the deliberate "No image" state beside it.
    evidence: |-
      `CatalogueScreen` renders `<img>` with no `onError`, so a `404` from a
      derivative that never got written, a `403` or a dropped connection paints
      a broken glyph in a 96px cell -- next to rows whose genuinely imageless
      tiles say "No image" in words. CLAUDE.md makes the reference image the
      thing that makes a candidate verifiable, so the two failures reading
      differently matters. `EditTileScreen`'s gallery (Story 2.2) has the same
      gap and established the convention, which is why this story inherited it
      rather than introduced it; fixing one without the other would leave the
      product saying two things.
    location: >-
      apps/web/src/screens/CatalogueScreen.tsx row thumbnail; apps/web/src/screens/EditTileScreen.tsx gallery
    severity: low
  - summary: >-
      Every return to the Catalogue re-downloads every visible thumbnail,
      because the image route is `no-store` and the screen refetches on mount.
    evidence: |-
      `GET /admin/tiles/{tile_id}/images/{image_id}` answers with
      `{**NO_STORE, **NO_SNIFF}` (Story 2.1), so no thumbnail is ever cached by
      the browser, and the Catalogue's refetch on mount is deliberate -- a tile
      just added, renamed or removed has to show up. Together they mean that
      Back from Add tile, Edit tile or Bulk upload re-requests the list *and*
      every row's image through an authenticated, role-rechecking, DB-reading
      route. This compounds the oversized-derivative entry above rather than
      duplicating it: that one is about the size of one fetch, this one is
      about how many times it happens. Whether a catalogue thumbnail may be
      privately cached is an AD-17 / AGENTS.md decision about how much
      catalogue data may sit in a shared handset's disk cache, not a patch this
      story could make.
    location: >-
      apps/api/api/catalogue.py tile image route; apps/web/src/screens/CatalogueScreen.tsx mount refetch
    severity: medium
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
- patch: 3: (high 0, medium 2, low 1)
- defer: 2: (high 0, medium 1, low 1)
- reject: 16: (high 0, medium 0, low 16)
- addressed_findings:
  - `[medium]` `[patch]` `EditTileScreen`'s removal exit keyed on the mount-time `tile` prop rather than on the tile actually removed, so a tile found through the lookup stage after a `404` dropped the handed-over one left for a Catalogue that never listed it, swallowing the `<code> removed.` confirmation on the way. The branch now compares `opened?.id` against the removed tile's id; a new `edit-tile.test.tsx` case drives the `404` → lookup → remove-a-different-tile path and was verified to fail against the old condition.
  - `[medium]` `[patch]` The Catalogue told `App` the query on *submit*, so a query the server refused (`invalid_query` from a pasted paragraph — the box carries no bound of its own) was held and re-issued on the next visit, reopening the screen on an alert whose `Try again` repeats the same refusal. `onSearch` now fires from `load`'s success branch through a ref, so only a search the server answered survives the screen; two new tests pin both halves and were verified to fail against the old placement.
  - `[low]` `[patch]` `catalogue.test.tsx`'s "forgets the search when the session ends" asserted only that the search box is absent while the login screen is up — which the screen swap satisfies on its own — so the clearing was unpinned. It now signs back in, opens the Catalogue and asserts an empty box and a blank browse; verified to fail with both `setCatalogueQuery('')` calls removed. (The finding's claim that the sign-out reconciler alone is load-bearing is wrong: the role reconciler fires on the same transition, so the two are belt-and-braces. The test pins the outcome rather than either line.)

### 2026-09-22 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 0, low 7)
- defer: 1: (high 0, medium 0, low 1)
- reject: 19: (high 0, medium 0, low 19)
- addressed_findings:
  - `[low]` `[patch]` A mid-session demotion cleared the section, the edited user and the edited Tile but not the search — the fragment a demoted Administrator typed survived in state and would have been handed back on a promotion, against the sign-out reconciler's own stated reason for clearing it. `catalogueQuery` now goes with them.
  - `[low]` `[patch]` `reachableBy`'s new `'catalogue'` arm, and the role reconciler that reads it, were exercised by nothing: every Staff assertion was a door-presence check the JSX condition alone satisfies, so the whole role-conditional half of the section could be deleted and ship green. A demotion test now drives it — verified to fail against both the removed `reachableBy` arm and the missing query clear.
  - `[low]` `[patch]` A handed-over Tile whose removal is refused `404` — two Administrators on one row, the second confirming a removal the first already made — was the entry path this story added and the one the documented fallback was never pinned on. `edit-tile.test.tsx` now asserts it: the alert, the lookup stage, the focus, and that `onRemoved` is *not* called.
  - `[low]` `[patch]` FR-20's "a search writes no audit entry" carried `@needs_model` only because its control was the add, so on a machine without the ONNX artifact the claim went unmade and `make test` does not depend on that target. A model-free twin seeds a Tile and uses the removal as its control; `seed()` now returns the id.
  - `[low]` `[patch]` `App`'s Add Tile and Bulk Upload comments claimed the Catalogue's mount refetch "shows the tile just added" and lists "the whole batch", which this story's own query-persistence patch made false — the refetch runs the retained search. Both now say what actually happens and how to see the rest.
  - `[low]` `[patch]` A test named "sends one request for two presses of Try again, and moves focus once" read no focus at all; the focus claim is the next test's and the name now stops at what it asserts.
  - `[low]` `[patch]` A stray triple blank line in `CatalogueScreen.tsx` between `retry()` and the render.

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

**Summary of implemented change.** This run was a follow-up review pass over the already-implemented Story 2.5 diff (baseline `87d032c74169146906de0059b26a4b5cf34cdada`), not a re-implementation. Four review layers ran in parallel over the full 5,495-line diff; triage produced no `intent_gap` and no `bad_spec`, three `patch` findings — two correctness defects in the story's own new code and one unpinned claim — and two `defer` items. The story's shape is unchanged: one admin-only `GET /admin/tiles?q=` over `ILIKE` on the Code, the Catalogue screen, and the three tile doors moved onto it.

**Files changed in this pass:**

- `apps/web/src/screens/EditTileScreen.tsx` -- the removal exit now keys on the id of the tile actually removed rather than on the mount-time `tile` prop, so a tile found through the lookup stage after a `404` announces its removal there instead of leaving for a Catalogue that never listed it; two doc blocks state the rule as the code now enforces it.
- `apps/web/src/screens/CatalogueScreen.tsx` -- the submitted query is handed to `App` from `load`'s success branch (through a ref kept current in an effect, so `load` stays dependency-free and `oxlint`'s ref rule is satisfied) rather than from `submit`, so a refused query is not held and re-issued on the next visit.
- `apps/web/src/__tests__/edit-tile.test.tsx` -- one new case: a `404` drops the handed-over tile, a different tile is found through the lookup stage and removed, and the announcement plus focus is asserted while `onRemoved` is not called.
- `apps/web/src/__tests__/catalogue.test.tsx` -- two new cases pinning that only an answered search reaches `App`, and the sign-out case now signs back in and asserts an empty box and a blank browse.

**Review findings breakdown.** Patches applied: 3 (medium 2, low 1). Items deferred: 2 (medium 1, low 1) -- the thumbnail's missing `onError` fallback, shared with Story 2.2's gallery, and the `no-store` image route compounding the Catalogue's refetch on mount. Items rejected: 16, all judged cosmetic or already recorded -- among them the `INVALID_QUERY` constant having no screen-side branch (the screen renders the server's own sentence by design), the absence of a spoken confirmation after a row-opened removal (the row's disappearance and the live region's count are the confirmation, and the spec chose this deliberately), the lookup form still rendering above the edit form (already on the deferred list), the substring-based disclosure guards, the three spellings of the browse URL across suites, and the `@needs_model` gating that predates this story. The intent-alignment audit reported divergences descriptively and claimed no defect; its observations about search persistence, the removal exit and the `null`-category sentinel are all decisions the spec records.

**Follow-up review recommendation:** `true`. Patched counts this pass: high 0, medium 2, low 1. Score = 3 x 2 + 1 x 1 = 7, which is >= 5. No high-severity finding was patched.

**Verification performed:**

- `make lint` -- green (ruff check, ruff format --check, oxlint with `--deny-warnings`, `tsc --noEmit`). The first attempt failed on `react(refs)` for a ref written during render; the ref is now seeded at first render and kept current from an effect declared above the mount effect.
- `npm --prefix apps/web test -- --run` -- 25 files, 1508 tests, all green. This supersedes the narrower web command in the Verification section.
- `uv run --project shared/schema pytest shared/schema/tests/test_tile.py -q` -- 48 passed.
- `uv run --project apps/api pytest apps/api/tests/test_catalogue_search.py apps/api/tests/test_catalogue_authorization.py apps/api/tests/test_tile_lookup.py apps/api/tests/test_admin_authorization.py apps/api/tests/test_no_registration.py apps/api/tests/test_source_guards.py apps/api/tests/test_catalogue_audit.py -q` -- 116 passed, nothing skipped for a missing model.
- `make test` -- **not run to completion.** It exceeded the session's 10-minute command ceiling, as did `pytest apps/api` on its own, so it was run in the partitions above, as the Verification section provides for. This pass changed no Python at all (`git diff --stat` over `apps/api`, `shared/`, `scripts/` and `infra/` is empty for this run's edits), so the API partitions named in the Verification section plus the full web suite cover what changed.
- `git diff --stat -- shared/vision` is empty. No re-index and no eval run is owed.
- Each patch was mutation-checked: reverting the `EditTileScreen` branch fails the new removal test; reverting the `onSearch` placement fails both new Catalogue tests; removing both `setCatalogueQuery('')` calls fails the strengthened sign-out test.

**Residual risks:**

- Removing only the sign-out reconciler's `setCatalogueQuery('')` leaves the behaviour correct, because the role reconciler fires on the same transition and clears it too. The strengthened test pins the observable outcome rather than either line, which is the right level, but it does mean neither line is individually load-bearing.
- The two deferred items above are real and unaddressed: a broken thumbnail still paints a browser glyph, and a browse of the whole catalogue still re-downloads every visible derivative on each return to the screen. Both need a decision outside this story (AD-17 for the derivative and its cacheability, the shared `<img>` convention for the fallback).
- The full `make test` has not been observed green in one command in this session; the Python half was verified only through the partitions named above.
