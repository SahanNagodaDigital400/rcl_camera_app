---
title: 'Story 1.13 — View Audit Log'
type: 'feature'
created: '2026-09-21'
baseline_revision: '9f7c51194f056520f7d763c7d2a2bba381e208d8'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Reading the audit log is itself a privileged action, and this story makes
      it possible without recording it.
    evidence: |-
      `GET /admin/audit` writes nothing, `AuditAction` has no member for a read,
      and the module docstring's list of deliberate omissions does not mention
      it. FR-20 and AGENTS.md:17 enumerate logins, failed logins and account
      changes, so a read is outside the requirement as written - but "who read
      the security record, and when" is the one question this surface newly
      makes askable and cannot answer. Deciding it needs the retention and
      volume answers that are still deferred in the spine, since an entry per
      page of every read is a row per press in a table nobody can prune.
    location: >-
      apps/api/api/audit.py (read_audit_log)
    severity: medium
  - summary: >-
      The only way to find an old event is to press Load more through 50-row
      pages; there is no search, date range or source-IP lookup.
    evidence: |-
      The story's own purpose clause is "review access history", and its worked
      example is a lookup, not a scroll. `source_ip` is already canonicalised in
      `audit.py` precisely so grouping on it would be possible, and the index is
      `(created_at DESC, id DESC)`, so a date range is cheap and an address
      filter is not. Nothing in the acceptance criteria asks for either, so
      neither was built. Recorded as DW-143.
    location: >-
      apps/web/src/screens/AuditLogScreen.tsx, apps/api/api/audit.py
    severity: medium
  - summary: >-
      The screen never re-reads once loaded, so entries written after the first
      page are invisible until it is closed and reopened.
    evidence: |-
      `Try again` renders only in the failed state and `exhausted` is sticky, so
      there is no refresh control. An Administrator who acts in another tab, or
      who leaves the log open, is reading a snapshot with nothing saying so.
    location: >-
      apps/web/src/screens/AuditLogScreen.tsx
    severity: low
  - summary: >-
      DESIGN.md's prose and its own tokens disagree about the audit row, and
      nothing records that the implementation had to choose.
    evidence: |-
      DESIGN.md:212 calls the audit row "visually identical to a data table
      row", while the token block at :112-115 gives `audit-log-row` a
      `{colors.muted-text}` foreground against `data-table-row`'s
      `{colors.text}` and omits `background-hover` entirely. The screen followed
      the tokens, which is the right call, but the prose still says otherwise
      and the next reader of either will not know the other exists.
    location: >-
      _bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md:212
    severity: low
  - summary: >-
      Neither the arrival of the first page nor the appending of a later one is
      announced to a screen reader.
    evidence: |-
      The `role="status"` wait line is unmounted and replaced by a freshly
      mounted table rather than updated in place, and a live region that is
      replaced is unreliable. Inherited from `UserListScreen`, so it is a shared
      fix rather than a defect new to this screen - but this screen's whole
      content is the announcement.
    location: >-
      apps/web/src/screens/AuditLogScreen.tsx, apps/web/src/screens/UserListScreen.tsx
    severity: low
  - summary: >-
      A `details` payload has no length cap, so one large entry can dominate the
      table.
    evidence: |-
      `detailValue` JSON-encodes arbitrary nested values into one cell.
      `--measure-prose` caps the width but not the length, and Epic 2 and 3 add
      actions whose payloads nobody has seen yet. DW-145 records that the
      rendering is generic; it does not record that it is unbounded.
    location: >-
      apps/web/src/screens/AuditLogScreen.tsx (detailValue)
    severity: low
  - summary: >-
      `created_at` is the transaction timestamp, so an entry can commit with a
      time a paging walk has already passed.
    evidence: |-
      `now()` is stamped at transaction start. A write that began before a
      reader's page and commits after it carries a `created_at` inside a range
      the reader has already walked, so that walk never shows it. The window is
      the length of a write transaction - milliseconds here - and the entry is
      present on any fresh load, so nothing is lost. Closing it properly means
      `clock_timestamp()` or a monotonic key, which is a change to an applied
      migration and to Story 1.12's table.
    location: >-
      infra/migrations/20260921T1000_create_audit_log.up.sql:83-111
    severity: low
  - summary: >-
      No mockup exists for this surface, so the column set, their order and the
      details cell were decided in the implementation and checked against
      nothing.
    evidence: |-
      The UX pair has `mockups/key-user-list.html` and no audit equivalent, and
      EXPERIENCE.md's state table has no row for this surface at all - no empty,
      loading or error treatment. `vite.config.ts` sets `css: false` and jsdom
      performs no layout, so every visual claim is asserted by regex over the
      stylesheet's text rather than by anything that renders. Recorded as
      DW-146.
    location: >-
      apps/web/src/screens/AuditLogScreen.tsx
    severity: low
  - summary: >-
      A `details` value that is not a JSON object fails validation on the read
      and answers `500`, taking every page that holds the row with it.
    evidence: |-
      The column is `jsonb NOT NULL DEFAULT '{}'` with no CHECK that the value
      is an object, while `AuditLogEntry.details` is `dict[str, Any]`. The only
      application writer passes a dict, so this is unreachable through the
      product - but AD-4's stated way of correcting a wrong entry is an entry
      inserted by hand as the table owner, which is exactly the path that can
      store a scalar. One such row then makes a page of the append-only record
      unreadable with no way to page past it. Whether to coerce on read, add a
      CHECK in a later migration, or leave the loud failure as the honest
      answer is a decision this story has no mandate to make.
    location: >-
      apps/api/api/audit.py (read_audit_log), infra/migrations/20260921T1000_create_audit_log.up.sql:110
    severity: medium
  - summary: >-
      The shared `422` envelope carries no `cache-control: no-store`, unlike
      every other refusal in the API.
    evidence: |-
      `api/main.py`'s `validation_error_handler` calls `_envelope(422, ...)`
      with no `headers`, while `ApiError` refusals - including this story's own
      `404` - pass `NO_STORE` and are tested for it. Pre-existing and API-wide
      rather than anything this story introduced, and the `422` body carries no
      data, so it is recorded rather than fixed here: changing the shared
      handler is a cross-cutting edit no single story owns.
    location: >-
      apps/api/api/main.py (validation_error_handler)
    severity: low
  - summary: >-
      `--color-border` gives the audit row separator 1.24:1 against
      `--color-surface`, and `--disabled-opacity` puts an aria-disabled
      control's label at 3.74:1.
    evidence: |-
      Raised by the `ui-ux-pro-max` pre-delivery checklist run in the
      2026-09-21 review pass, which the screen otherwise passes. Neither is
      this screen's decision: `{colors.border}` is what DESIGN.md:112-115
      prescribes for `audit-log-row` and every other admin surface already uses
      it, and `--disabled-opacity` is a product-wide token. They fall below the
      3:1 non-text and 4.5:1 text thresholds respectively, and both are
      arguably exempt - a row separator beside text rows is decorative, and
      WCAG 1.4.3 exempts inactive components. The question is whether the
      tokens themselves should move, which is a spine decision affecting every
      screen at once.
    location: >-
      apps/web/src/styles/tokens.css
    severity: low
  - summary: >-
      `auth.py` still describes this screen in the future tense now that it
      exists.
    evidence: |-
      `apps/api/api/auth.py:777` reads "keeps 'every entry names who it was
      about' true for the read Story 1.13 builds". Every other forecast of this
      story - in `audit.py`, `test_source_guards.py`, `UserListScreen.tsx`,
      `EditUserScreen.tsx` and `README.md` - was corrected to the past tense by
      this story, and this one was not, because `auth.py` is on the intent
      contract's Never-touch list and a comment-only edit is still an edit to
      it. Cosmetic, and safe to fold into the next change that opens the file.
    location: >-
      apps/api/api/auth.py:777
    severity: low
---

<intent-contract>

## Intent

**Problem:** Story 1.12 made every login, failed login and account change permanent, but gave
the record no surface. Today an Administrator answering "who signed in as Nadeesha on Tuesday,
and from where?" needs a `psql` prompt and the database credential — which is exactly the access
FR-21 exists to remove, and which nobody outside the build has. The log the product's security
spine is built on is, in the product, invisible.

**Approach:** One Administrator-only read route, `GET /admin/audit`, whose `SELECT` lives in
`apps/api/api/audit.py` beside the `INSERT` (the table has exactly one owning module), returning
entries newest-first in fixed-size pages walked by a keyset cursor — the order and the tiebreaker
`audit_log_created_at_idx` was created for. The entry shape becomes the product's third shared
contract (`shared_schema.audit` + its TypeScript twin), and a new `AuditLogScreen` renders it as
DESIGN.md's `audit-log-row`: the one table in the product with no row-end action at any role.

## Boundaries & Constraints

**Always:**

- **`apps/api/api/audit.py` remains the only application module that names the table.** The read
  statements are module-level `_UPPER_SNAKE` triple-quoted constants there, with `#:` blocks
  arguing *why*, exactly as `_INSERT_ENTRY` is. `tests/test_source_guards.py`'s `AUDIT_HOME` guard
  (L85, L339) already says the read surface belongs in this module — it must keep passing
  untouched, which also means **no file under `shared/schema` may contain the string `audit_log`**.
- **Read-only, everywhere.** No `UPDATE`, `DELETE` or `TRUNCATE` is added anywhere (AD-4,
  AGENTS.md:17), and the screen renders **zero row-end controls at any role** (EXPERIENCE.md:75,
  FR-21) — no edit, no delete, no menu, no checkbox, no row click.
- **Server-side authorization.** The route declares `Depends(require_administrator)` and lives
  under `/admin/`; both direction guards in `tests/test_admin_authorization.py` must pass. What
  `apps/web` renders is a convenience and never the control (AGENTS.md:11).
- **Newest first, with a total order.** `ORDER BY created_at DESC, id DESC`, matching
  `infra/migrations/20260921T1000_create_audit_log.up.sql:113-118` — `created_at` is the
  transaction timestamp, so two entries from one request share it exactly and `created_at` alone
  cannot be paged through.
- **Every SQL statement is a fixed string with `%s` placeholders.** `LIMIT %s` is a parameter;
  no `WHERE`, `LIMIT` or `ORDER BY` fragment is ever concatenated or interpolated
  (`test_source_guards.py:237`, AGENTS.md:14).
- **The response is a bare JSON array of `AuditLogEntry`**, mirroring `GET /admin/users`
  (`users.py:652`), with `response.headers.update(NO_STORE)` as the handler's first statement and
  a sync `def` handler.
- **Python and TypeScript change together.** `shared_schema/audit.py` and
  `shared_schema/ts/audit.ts` are one contract in two languages, pinned by a new parity test built
  on `tests/test_user.py`'s regex mechanism (L141-168). **The page size is part of that contract**:
  the client may not *choose* it, but it must *know* it, or it cannot tell a last page from a full
  one without asking.
- **The token layer is the only styling source** — no raw hex, no raw units outside `tokens.css`
  (`__tests__/no-raw-values.test.ts`). `audit-log-row` is `{colors.surface}` background, hairline
  `{colors.border}` separators, `{colors.muted-text}` foreground and — unlike `data-table-row` —
  **no hover background** (DESIGN.md:112-115).

**Block If:**

- Serving the read appears to require a migration, a new grant, or a second index. It does not:
  `GRANT SELECT, INSERT ON audit_log TO rocell_app` is already in place
  (`20260921T1000_create_audit_log.up.sql:170`) and the `(created_at DESC, id DESC)` index was
  created for this read. If a migration seems necessary, HALT rather than editing an applied one
  (AGENTS.md:34).
- The work appears to need a new runtime dependency (a table, virtualization, date-formatting or
  pagination library). It does not — `Date.prototype.toLocaleString` and a `<table>` are the
  precedent. Flag before adding one (AGENTS.md:36).

**Never:**

- **Never add the Flagged filter.** EXPERIENCE.md:38/:76 place it on this surface, but it renders
  FR-22 anomaly flagging, which is not in Epic 1 and has no data behind it — a filter over a
  column that does not exist. Record it as deferred; do not build a dead control.
- **Never add search, sort controls, column filters, a date-range picker, CSV export, or a
  client-chosen page size.** None is in the acceptance criteria, and a caller-supplied `limit` is
  a denial-of-service knob on the one table nobody can prune.
- **Never let the client sort or re-order.** The statement states the order; the screen renders the
  array as received (`UserListScreen`'s precedent, `user-list.test.tsx:268-279`).
- **Never invent an entry.** A row whose `actor_user_id` is `NULL` is rendered as having no actor,
  never as "System" or as the target — an unknown-account sign-in attempt has no actor and saying
  otherwise is the log asserting something it does not know.
- **Never render a partially-understood body.** A body that is not an array of entries the type
  guard accepts throws `MALFORMED_RESPONSE` and shows the failure state
  (`UserListScreen.tsx:112-118`).
- **Never touch `apps/api/api/auth.py`, `users.py`, `sessions.py`, `throttle.py`,
  `dependencies.py`, `db.py` or anything under `infra/`.** This story adds a reader to a table
  that is already created, already indexed and already granted; every behaviour those modules own
  is unchanged.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First page | `GET /admin/audit`, Administrator | `200`, bare array of at most `PAGE_SIZE` entries, newest first, `cache-control: no-store` | No error expected |
| Next page | `GET /admin/audit?before=<id of the oldest row already shown>` | `200`, the next at most `PAGE_SIZE` entries strictly older than that row by `(created_at, id)` | No error expected |
| Cursor at the oldest entry | `before` names the oldest row | `200`, `[]` — the client stops offering more | No error expected |
| Cursor names no row | `before` is a well-formed UUID with no entry | `404` `audit_entry_not_found` — distinguished from an exhausted log, which is `[]` | `404` envelope |
| Cursor is not a UUID | `?before=nonsense` | `422` envelope from the existing validation handler | `422` envelope |
| Empty log | No rows | `200`, `[]`; the screen states there are no entries | No error expected |
| Entry with no actor | `actor_user_id`/`actor_email` `NULL` (unknown-account sign-in attempt) | Both serialize as `null`; the screen renders the no-actor word, not a blank cell | No error expected |
| Entry with unrecorded address | `source_ip` `NULL` (unparseable or absent trusted header) | Serializes as `null`; the screen renders the unknown-address word | No error expected |
| Entry with an action the twin does not know | A row whose `action` is outside `AuditAction` | Served and rendered verbatim — `action` is `str` on the wire, and the label map falls back to the stored value | No error expected |
| `details` with nested values | `user_edited` carrying `{"changed": {"role": {"from": "staff", "to": "admin"}}}` | Rendered as deterministic sorted `key: value` text; non-string values JSON-encoded | No error expected |
| Staff caller | Valid session, `role = staff` | `403` `administrator_required`, no rows | `403` envelope |
| Administrator on a temporary credential | `must_change_password` true | `403` `password_change_required` (the gate, unchanged) | `403` envelope |
| Unauthenticated caller | No cookie | `401` `unauthorized` | `401` envelope |
| Administrator demoted mid-session | Role changed to `staff` | The very next request is refused `403`; the screen shows that refusal and the home panel's door is gone on the next render | `403` envelope |
| Load fails | Network error, `500`, or malformed body | One `role="alert"` carrying the API's own sentence, no table beside it, and a "Try again" that refetches | Client-side state |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**

- `_bmad-output/planning-artifacts/epics.md` **lines 335-347** — Story 1.13 verbatim; **line 91**
  (UX-DR8: `audit-log-row` is "identical treatment, zero row-end actions"); **line 117**;
  **lines 126-129** (UX-DR16-19 are acceptance criteria on this story); **line 146** (at 1.13's
  ship date the log holds auth/account events only — catalogue events are Epic 2, scan Epic 3);
  **line 170** (UI contract: build against DESIGN.md + EXPERIENCE.md; run `ui-ux-pro-max`'s
  pre-delivery checklist before calling this done).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` **line 61** — FR-21;
  **line 63** FR-22 (the Flagged filter's source, out of scope here).
- `ARCHITECTURE-SPINE.md` — **AD-4 (64-68)**, whose grant is `INSERT` *and* `SELECT`, so this read
  is inside the granted set; **AD-6 (76-80)** every read goes through an authenticated `apps/api`
  endpoint; **AD-3 (62)** the shared session lookup re-reads role per request; **AD-10 (100-104)**
  and **line 264** — anything naming a Tile or Reference Image is a snapshot and may name a
  deleted row; **lines 256-261** the ERD's four declared `AUDIT_LOG_ENTRY` columns (a floor, not a
  ceiling — the shipped table has nine); **line 170** PascalCase entity naming; **line 171** UUIDv4
  ids, ISO 8601 UTC timestamps, one error envelope; **line 173** every privileged action
  re-verifies role server-side. **No AD and no line names FR-21 or Story 1.13** — there is no
  pagination convention anywhere in the spine.
- `DESIGN.md` — **112-115** the `audit-log-row` tokens (surface background, border, **muted-text**
  foreground, **no `background-hover` key**); **212-214** the prose ("visually identical…
  deliberately unremarkable"); **190** admin density `{spacing.2}`-`{spacing.3}`; **186** the `code`
  role is scoped to product Codes and is an unconfirmed assumption; **180** muted-text on
  background is 4.65:1 and passes only narrowly; **215** Phosphor outline icons.
- `EXPERIENCE.md` — **38** the IA row (reached from Nav (Admin); "chronological account/catalogue
  history"); **18** role-conditional nav, never disabled items; **42** the tab bar / sidebar that
  does not exist yet; **75** the read-only rule; **86/91** the register for an empty state;
  **95** a permission revoked mid-session redirects rather than dead-ends; **103** infinite scroll
  is banned (a "Load more" button is not infinite scroll); **109-113** the accessibility floor;
  **52-57** short factual sentences, no exclamation marks.
- `AGENTS.md` — **11** (server-side authz), **14** (parameterized SQL, output escaped), **17**
  (never add an update or delete path), **20** (two roles only), **33** (TS strict, no unexplained
  `any`), **34** (never edit an applied migration), **36** (flag any new dependency).
- `infra/migrations/20260921T1000_create_audit_log.up.sql` — **83-111** the nine columns;
  **113-118** the index and the comment that names this read "newest first" and explains why
  `id DESC` is the tiebreaker to page through; **170** the `SELECT, INSERT` grant. **Not edited.**

**Files that already exist and constrain the shape:**

- `apps/api/api/audit.py` (260 lines) — **the one module that may name the table.** `AuditAction`
  (L75-108, thirteen members) **moves to `shared_schema.audit` and is re-imported here**, so
  `auth.py:112` and `users.py:172` keep working unchanged. `TRUSTED_PROXY_HEADER` (L111-124),
  `_INSERT_ENTRY` (L127-142), `source_ip` (L145-220), `record` (L223-260) are otherwise untouched.
  **Three prose blocks are falsified and must be rewritten:** L47-56 ("**Not here.** No read
  surface — no route, no query function, no pagination"), L135-137 (the `RETURNING` argument, whose
  parenthetical hands the read to this story), and L214-218 (which promises "Story 1.13's
  'everything from this address' filter" — no filter is built; the canonicalisation argument stands
  on FR-22's grouping alone). The new router, page size, three `SELECT` constants and handler go
  here.
- `apps/api/api/users.py` — **`list_users` (L652-706) is the template**: `@router.get(path,
  response_model=list[Model])`, sync `def`, `administrator: Annotated[User,
  Depends(require_administrator)]`, `conn: Annotated[psycopg.Connection, Depends(get_connection)]`,
  `response.headers.update(NO_STORE)` first (L701), `return [Model.model_validate(row) for row in
  conn.execute(...)]` (L706). `_SELECT_USERS` (L615-650) is the `#:`-block-plus-constant model;
  its L634-642 comment ("no `WHERE`, no `LIMIT`… measure before reaching for pagination") is the
  argument this story answers differently and must not be copied. Error helpers L470/L485/L905/L951
  are the `ApiError(CODE, MESSAGE, status_code=…, headers=NO_STORE)` shape. **Not edited.**
- `apps/api/api/dependencies.py` — `NO_STORE` (L78), `require_administrator` (L193, "every route
  under `/admin/` declares this, and nothing else does"), which chains through
  `require_claimed_user` (L170) and so satisfies the forced-change gate walker. **Not edited.**
- `apps/api/api/main.py` — `from api import auth, users` (L27) and the two `include_router` calls
  (L170, L177). A third import and a third registration; the four exception handlers
  (L149-152) already serve this route's envelopes.
- `apps/api/api/db.py` — `APPLICATION_ROLE` (L79), `CONNECTION_OPTIONS` (L86), `create_pool`
  (L116), `get_connection` (L170). **Not edited** — `rocell_app` already holds `SELECT`.
- `shared/schema/shared_schema/user.py` (111 lines) — **the contract template**: module docstring
  naming its twin (L14-15), `from __future__ import annotations`, `StrEnum` with lowercase wire
  values (L43-47), `BaseModel` with `model_config = ConfigDict(extra="forbid")` (L63), snake_case
  fields identical on both sides, nullable fields as `X | None` **with no default** so JSON always
  carries every key (L58-60), and `@field_serializer(..., when_used="json")` emitting
  `value.astimezone(UTC).isoformat()` (L92-111).
- `shared/schema/shared_schema/__init__.py` — docstring L3-5 states the twin rule; imports L13-21
  (one line per module, modules alphabetical); `__all__` L23-34 in ASCII sort order.
- `shared/schema/shared_schema/ts/user.ts` (142 lines) — the twin template: string-literal union
  (L12), `ROLES` (L15), `export interface User {` with fields at exactly two-space indent and `}`
  at column 0 (L17-42), grouped `const X = [...] as const;` arrays (L49-56), `CONTRACT_KEYS`
  (L58-65), `USER_KEYS = [...CONTRACT_KEYS].sort()` (L68), `UUID_PATTERN` (L75),
  `UTC_TIMESTAMP_PATTERN` (L89-90), narrowers (L93-109), `isUser` closed-shape check (L123-138),
  private `isPlainObject` (L140-142, duplicated per file by design).
- `shared/schema/tests/test_user.py` — **the parity mechanism, and it is regex over text, not a
  TS parser.** `_ts_key_array` (L141-144) requires `const NAME = [ … ] as const;` with
  single-quoted literals; `test_the_typescript_narrowing_check_covers_every_python_field`
  (L147-159) requires the literal list be named `CONTRACT_KEYS` and spreads match `\.\.\.([A-Z_]+)`;
  `test_the_typescript_interface_declares_every_python_field` (L162-168) requires the one-line
  `export interface <Name> {` and two-space field indent; L185-190 transcribes
  `UTC_TIMESTAMP_PATTERN` verbatim. **Not edited** — its regexes are scoped to `user.ts`.
- `apps/api/tests/conftest.py` — `conn` (L192, superuser, for arranging rows), `app_role_conn`
  (L206, the product's own role), `_SELECT_AUDIT_ROWS`/`audit_rows` (L225-254), `make_user` (L279),
  `client` (L315, `base_url="https://testserver"`, `client=("127.0.0.1", 50000)` so `source_ip` is
  real). **Not edited.**
- `apps/api/tests/test_user_list.py` — the shape a new admin-read test file follows: an
  `administrator` fixture that provisions and signs in (L41-51), behavioural section, then a
  **statement-text section** (L340-425) parsing the module's SQL constant to pin the column list
  against `set(Model.model_fields)` and to assert what the statement does and does not contain.
  The audit twin of `test_the_read_is_every_account_with_no_filter_and_no_page` (L391) asserts the
  opposite and must say why.
- `apps/api/tests/test_no_registration.py` — **L202-213** the route-path set literal gains
  `"/admin/audit"`; the test's name (L144) counts the admin paths and is renamed with it.
  **`SOURCE_PATTERNS` (L78-86)** scan every `.py/.ts/.tsx/.css/.sql/.json/.html` under `apps`,
  `infra`, `scripts`, `shared` — **prose and comments included** — for `sign up`, `create an
  account`, `new account`, `/register|/signup|/join`. Every new docstring, comment and microcopy string
  must avoid them ("provision", "provisioned account").
- `apps/api/tests/test_admin_authorization.py` — `_declares` (L99) resolves a dependency at any
  depth; `_api_routes` (L116) raises rather than skips on an unrecognised route object;
  **`test_the_admin_route_table_is_the_six_routes_the_product_serves` (L510) with its literal at
  L529-538** gains `GET /admin/audit` and is renamed. Both direction guards (L541, L550) and the
  gate-chaining test (L563) must pass **unchanged** — note L550 means an Administrator-only route
  may not live outside `/admin/`.
- `apps/api/tests/test_forced_change_gate.py` — `ALLOWED_WITHOUT_THE_GATE` (L55-76) and
  `test_no_admin_route_is_exempt_from_the_gate` (L354). **Not edited**: `require_administrator`
  chains through the gate, so the new route needs no entry.
- `apps/api/tests/test_source_guards.py` — `AUDIT_HOME` (L85) and
  `test_only_one_module_names_the_audit_table` (L339, pattern `\baudit_log\b`, case-insensitive,
  whole file text, `tests` exempt) must pass **unchanged**; the L77-84 comment predicting this
  story's function stops being a prediction. `INTERPOLATED_SQL`/`test_no_sql_is_assembled_from_a_value`
  (L170-175, L237) forbids building the statement from a value, in source *and* in tests.
- `apps/web/src/App.tsx` — six edit points: the `Section` union (L33) and its docstring (L20-32),
  the `Screen` union (L46-54), `reachableBy` (L67-72), `currentScreen`'s section branches
  (L94-96 is the model), a render branch beside the `'users'` one (L349-365), and the home-panel
  door (L446-461). The role reconciler (L177-214) and focus effect (L219-239) cover a new screen
  without being touched.
- `apps/web/src/App.module.css` — `.userList` (L45-65) is the secondary-button treatment to copy;
  its comment ("there is one admin entry here rather than two") and the matching prose in
  `App.tsx` L444-452 become false and must be corrected: EXPERIENCE.md:33 and :38 are **two**
  nav entries for two collections, which is why a second door is not the thing line 34 rules out.
- `apps/web/src/screens/UserListScreen.tsx` (716 lines) — **the screen template**, and the
  strongest one in the repo: the three-state `Listing` union (L98-101), `asUsers` (L112-118),
  the generation-counter fetch (L352-400), `apiRequest` used directly and never through
  `SessionProvider` (L241-248), `titleRef`/`tabIndex={-1}`/`rescueFocus` (L340, L351, L402-422),
  and the render (L483-714): `<section>` with no `<main>`, heading, actions row, `role="status"`
  wait line, `role="alert"` failure with a Try again, empty text, then `.scroller`
  (`role="region"`, `aria-labelledby`, `tabIndex={0}`) around one `<table>` at every width
  (L526-539 argues why there is no phone reflow). **Comment-only edit** at L285-289 ("No view of
  the audit log… the log's own surface is Story 1.13").
- `apps/web/src/screens/UserListScreen.module.css` (335 lines) — `.row`/`.row:hover`/`.cell`
  (L151-182) are the `data-table-row` declarations; the audit variant drops the hover rule and
  takes `{colors.muted-text}` as its foreground.
- `apps/web/src/screens/EditUserScreen.tsx` **L73-76** — **comment-only**: the log now has a
  surface.
- `apps/web/src/api/client.ts` — `apiRequest` (L293-376) returns `unknown`,
  `credentials: 'same-origin'` (L311), `ApiRequestError` carrying `code`/`status` (L187-197),
  `RequestOptions` (L199-202) has no query helper, so a cursor is written into the path string.
  **Not edited** — the screen does not branch on the new code, and
  `__tests__/error-code-parity.test.ts` pins only codes the client imports (L34-45).
- `apps/web/src/__tests__/user-list.test.tsx` (802 lines) — the test template: handmade
  `stubFetch` keyed by prefixed path (L119-151), `stubDeferred` (L160-185), `renderScreen`/`rowFor`
  (L197-220), and the eight describes whose coverage the new screen owes — the request, the list
  (including an exact `toEqual` on the column headers), a failed load, a stale answer under
  StrictMode, an empty list, the controls (an exact `toEqual` on the button names and explicit
  absence of `link`/`menuitem`/`checkbox`/`textbox`/sortable headers), and the table at phone
  width. **Not edited.**
- `apps/web/src/__tests__/styling-wiring.test.ts` — the per-`*.module.css` used/declared class
  sweep (L154-188) auto-enrols a new stylesheet, so an unused class fails the build; the
  per-screen accent suite (L669-800) is the model for a new `describe`, including the whole-file
  accent count (L697-703), the `data-table-row` assertions (L779-791) and the `.scroller`
  overflow assertion (L793-799).
- `apps/web/src/__tests__/create-user.test.tsx` **L647-700** — `describe('the door on the home
  panel')` and `stubShell` (L649-654). `'is the one admin entry, not two'` (L663-673) stays true
  as an assertion (Create user is still not a door) but **its comment must be corrected** now that
  a second collection has its own entry.
- `apps/web/src/__tests__/no-raw-values.test.ts`, `tokens.test.ts` — auto-enrol new files.
- `apps/web/src/styles/tokens.css` — the tokens this screen uses: `--color-surface`,
  `--color-background`, `--color-border`, `--color-muted-text`, `--color-text`,
  `--color-primary`, `--color-destructive`, `--border-hairline`, `--space-1`…`--space-6`,
  `--radius-sm`, and the `label`/`body`/`caption` type roles. **Not edited.**
- `README.md` **lines 141-144** ("What it cannot yet do is *show* you… That screen is Story 1.13")
  and **line 184** ("The screen that displays the log is Story 1.13") — both become false.
- `_bmad-output/implementation-artifacts/deferred-work.md` — format `### DW-<n>:` then
  `origin/location/source_spec/severity/reason/status`, one blank line between entries; highest in
  use is **DW-141** (line 1123), so new entries start at **DW-142**.

## Tasks & Acceptance

**Execution:**

- `shared/schema/shared_schema/audit.py` — **new.** `AuditAction(StrEnum)` moved verbatim from
  `apps/api/api/audit.py:75-108` (all thirteen members and the docstring's reasoning, updated to
  say it now also names what the read surface labels), and `AuditLogEntry(BaseModel)` with
  `extra="forbid"` and the nine columns: `id: UUID`, `created_at: AwareDatetime`, **`action: str`**,
  `actor_user_id: UUID | None`, `actor_email: str | None`, `target_user_id: UUID | None`,
  `target_email: str | None`, `source_ip: str | None`, `details: dict[str, Any]`; a
  `@field_serializer("created_at", when_used="json")` emitting UTC ISO 8601. The docstring must
  argue **why `action` is `str` and not `AuditAction`** (writes are constrained, reads are not: the
  column has no CHECK by design, the vocabulary grows every epic, and a read surface that refuses
  to render an entry it does not recognise is the one failure an append-only log may not have) and
  must name `shared_schema/ts/audit.ts` as its twin. It also holds **`PAGE_SIZE`**, read by
  `apps/api/api/audit.py` and mirrored in the twin as `AUDIT_PAGE_SIZE`, so the screen knows when a
  page is the last one instead of guessing from the length of the first. **This file must never
  contain the table's name** — `test_source_guards.py` scans `shared/schema`.
- `shared/schema/shared_schema/__init__.py` — import the two names and add `"AuditAction"`,
  `"AuditLogEntry"` to `__all__` in ASCII sort order (immediately after `"ApiError"`).
- `shared/schema/shared_schema/ts/audit.ts` — **new, handwritten twin.** `AuditAction` string
  union, `AUDIT_ACTIONS`, `export interface AuditLogEntry` (two-space indent, closing brace at
  column 0, `action: string`, `details: Record<string, unknown>`), the grouped `as const` key
  arrays, `CONTRACT_KEYS`, `AUDIT_LOG_ENTRY_KEYS`, the transcribed `UUID_PATTERN` and
  `UTC_TIMESTAMP_PATTERN`, `isAuditAction`, `isAuditLogEntry` (closed shape: sorted-key equality
  then per-group value checks) and the local `isPlainObject`. No config change is needed —
  `@rocell/schema/*` is a wildcard alias.
- `shared/schema/tests/test_audit.py` — **new.** `test_user.py`'s structure against `audit.ts`:
  `EXPECTED_FIELDS`, the `CONTRACT_KEYS` parity test, the `export interface AuditLogEntry` parity
  test, the transcribed timestamp pattern, a naive-datetime refusal, an any-offset-serializes-UTC
  round trip, and a test that every `AuditAction` member appears in the twin's union.
- `apps/api/api/audit.py` — import `AuditAction` and `PAGE_SIZE` from `shared_schema.audit` and
  delete the local definition of the enum (re-exported, so `auth.py:112` and `users.py:172` are
  untouched); add a `#:` block on why the client is told the page size but never chooses it,
  `AUDIT_ENTRY_NOT_FOUND` / its message, `_SELECT_LATEST_ENTRIES`, `_SELECT_ENTRIES_BEFORE`
  (keyset: `WHERE (created_at, id) < (SELECT created_at, id FROM audit_log WHERE id = %s)`),
  `_SELECT_ENTRY_EXISTS`, `router = APIRouter(tags=["audit"])`, and the
  `@router.get("/admin/audit", response_model=list[AuditLogEntry])` handler taking
  `require_administrator`, `get_connection` and `before: UUID | None = None`. Rewrite the three
  falsified prose blocks (L47-56, L135-137, L214-218).
- `apps/api/api/main.py` — `from api import audit, auth, users` and a third `include_router`,
  with the existing `/admin/` boundary comment extended rather than duplicated.
- `apps/api/tests/test_no_registration.py` — add `"/admin/audit"` at L202-213 and rename the test
  to match the new count.
- `apps/api/tests/test_source_guards.py` — **comment only** (L77-84): the read surface this
  module's `AUDIT_HOME` comment predicts is now a function in `audit.py`, so the sentence states
  it rather than forecasting it. No regex, no constant and no assertion changes.
- `apps/api/tests/test_admin_authorization.py` — add an `AUDIT_LOG = "/admin/audit"` constant with
  the same doc-comment shape as its neighbours, add `GET {AUDIT_LOG}` to the literal at L529-538,
  and rename the test to the new count.
- `apps/api/tests/test_audit_read.py` — **new.** Every row of the matrix: ordering newest-first
  with two entries sharing a `created_at` proving the `id DESC` tiebreaker; a full page, the next
  page, no overlap and no gap across the boundary; the exhausted-log `[]`; the unknown cursor
  `404`; the malformed cursor `422`; the empty log; null actor, null target and null `source_ip`
  surviving to the body; an action outside the enum served verbatim (arranged through `conn`);
  `details` round-tripping nested JSON; `cache-control: no-store`; the body is a bare array; every
  element satisfies the `AuditLogEntry` contract; no password digest or session token anywhere in
  the body; Staff `403`, unclaimed Administrator `403`, unauthenticated `401`, demotion closing the
  surface on the next request. Then the **statement-text section**: the three constants parse to
  exactly `set(AuditLogEntry.model_fields)`, state `ORDER BY created_at DESC, id DESC`, carry a
  parameterized `LIMIT`, and contain no `UPDATE`/`DELETE`/`TRUNCATE`.
- `apps/web/src/screens/AuditLogScreen.tsx` + `AuditLogScreen.module.css` — **new.**
  `UserListScreen`'s three-state union, generation-counter fetch, focus rescue and table shape,
  with: named constants for every string; an `ACTION_LABELS: Record<AuditAction, string>` with a
  fallback to the stored value; six columns — When, Who, What, Target, Source IP, Details; `When`
  via `toLocaleString()`; the no-actor and unknown-address words for nulls; `details` rendered as
  deterministic key-sorted `key: value` text with non-strings JSON-encoded; an empty state, a
  `role="status"` wait line and a `role="alert"` failure with Try again; a "Load more" control
  that requests `?before=<oldest rendered id>`, appends, and disappears once a page comes back
  short or empty. **Zero row-end controls, no row click, no checkbox, no sortable header.** The
  stylesheet carries the `audit-log-row` treatment — surface background, hairline border-top,
  muted-text foreground, **no hover rule**, no `box-shadow` — and **no `var(--color-accent)` at
  all**: a read-only surface has no primary action.
- `apps/web/src/App.tsx` — add `'audit'` to `Section` and `Screen`, to `reachableBy`'s admin
  condition and to `currentScreen`; add the render branch beside `'users'`; add the role-conditional
  home-panel door. Correct the `Section` docstring (L20-32) and the door comment (L444-452): two
  of EXPERIENCE.md's six nav entries now exist, and Create/Edit user are still reached from the
  list rather than from here.
- `apps/web/src/App.module.css` — add `.auditLog` with `.userList`'s secondary treatment, and
  correct `.userList`'s comment.
- `apps/web/src/screens/UserListScreen.tsx`, `apps/web/src/screens/EditUserScreen.tsx` —
  **comment-only.** The log has a surface now, reached from the home panel.
- `apps/web/src/__tests__/audit-log.test.tsx` — **new.** The request (path, method,
  `credentials: 'same-origin'`, no body); the rendered rows in server order with an exact
  `toEqual` on the column headers; label mapping including the unknown-action fallback; the null
  actor / null address words; `details` formatting; Load more requesting the right cursor,
  appending rather than replacing, and disappearing when the page comes back short; **the controls
  test** — an exact `toEqual` on the button names and the explicit absence of `link`, `menuitem`,
  `checkbox`, `textbox`, `searchbox`, `combobox`, a sortable header and any per-row control; the
  row is not clickable (asserted by clicking); the failed load, the stale answer under StrictMode,
  the empty log, and the table-at-phone-width region assertions. Plus the door suite: offered to an
  Administrator, absent for Staff, opens and comes back, and gone after a mid-session demotion via
  `visibilitychange`.
- `apps/web/src/__tests__/styling-wiring.test.ts` — a new `describe` for the audit stylesheet: the
  `audit-log-row` declarations, **no `:hover` rule and no `box-shadow`**, `--color-accent` counted
  **zero** times with a comment saying why, Back / Try again / Load more as the navy outline, the
  muted wait line and destructive refusal pair, and `.scroller { overflow-x: auto }`.
- `apps/web/src/__tests__/create-user.test.tsx` — correct the `'is the one admin entry, not two'`
  comment (L663-673); the assertion itself is unchanged.
- `README.md` — rewrite lines 141-144 and 184: the screen exists, who can reach it, what it shows,
  that it is newest-first and paged, and that it offers no way to change or remove an entry.
- `_bmad-output/implementation-artifacts/deferred-work.md` — append from **DW-142** for what this
  story deliberately leaves: the Flagged filter (EXPERIENCE.md:38/:76) waiting on FR-22; no search,
  date-range or source-IP filter over a table that only grows; the fixed server-side page size and
  the extra empty request when the total is an exact multiple of it; `details` rendered
  generically rather than per action; and the absence of any audit-log mockup to check the render
  against.

**Acceptance Criteria:**

- **Given** I am an authenticated Administrator, **when** I open the audit log from the home
  panel, **then** entries appear newest-first, each showing who acted, what they did, when, and
  the source IP, and no edit, delete, menu, checkbox or clickable row exists anywhere in that
  view at any role.
- **Given** the log holds more entries than one page, **when** I press Load more, **then** the
  next page appends below the last row with no entry repeated and none skipped — including across
  two entries written by one request that share a `created_at` to the microsecond — and the
  control disappears once the oldest entry has been reached.
- **Given** a Staff user, an Administrator still on a temporary credential, or an unauthenticated
  caller, **when** `GET /admin/audit` is requested directly, **then** it is refused `403`, `403`
  and `401` respectively with no entry in the body, independent of what any UI renders.
- **Given** an Administrator is demoted while standing on the screen, **when** the session is
  revalidated, **then** the very next request is refused and the surface and its door are gone,
  with no frame in which the audit table is painted for a Staff user.
- **Given** the change is complete, **when** `make lint` and `make test` are run, **then** both
  exit 0; `test_source_guards.py`, `test_forced_change_gate.py` and `infra/tests` pass with **no
  edit**; `git status --porcelain infra/` is empty; and the only route-table tests that changed are
  the two literal lists that name the new path.
- **Given** the screen is complete, **when** the `ui-ux-pro-max` pre-delivery checklist is run
  against it (epics.md:170), **then** it passes, and `no-raw-values`, `tokens` and `styling-wiring`
  confirm no raw hex, no raw unit and no unused class.

## Spec Change Log

## Review Triage Log

### 2026-09-21 - Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 12: (high 0, medium 3, low 9)
- defer: 8: (high 0, medium 2, low 6)
- reject: 8
- addressed_findings:
  - `[medium]` `[patch]` `isAuditLogEntry`'s value-level and extra-key rejections were
    executed by nothing: the screen's two malformed bodies are both refused on shape before
    any value check, and the Python parity test reads `audit.ts` as text. Deleting the
    key-count line, or the timestamp check, left the whole suite green while
    `created_at: 'yesterday'` rendered `Invalid Date` into the record. Added
    `apps/web/src/__tests__/audit-contract.test.ts` (68 tests) on `user-contract.test.ts`'s
    model; both deletions now fail it.
  - `[medium]` `[patch]` `disabled={appending}` blurred the Load more control on every
    press, dropping a keyboard reader to `<body>` for the length of the request; the focus
    rescue fired only on the press that removed the control. Now `aria-disabled`, with
    `inFlight` as the refusal - which is the guard that already held for same-tick presses,
    and which the new re-entrancy test pins.
  - `[medium]` `[patch]` `when()` printed neither seconds nor a time zone, so the two
    entries one request writes - the reason `id DESC` is the tiebreaker - read as the same
    instant, in an unnamed zone. Now formatted with an explicit `dateStyle`/`timeStyle`.
  - `[low]` `[patch]` `actionLabel` reached `Object.prototype`: a stored action of
    `toString` or `constructor` returned a function, which is not nullish, so a function
    reached React as a child. Now narrowed with `isAuditAction`, which also gives that
    exported narrower its first consumer.
  - `[low]` `[patch]` The reason keyset paging was chosen over `OFFSET` - that rows land at
    the top between two requests - was argued in two docstrings and tested nowhere. Added a
    test that writes an entry between the two reads; page two by `OFFSET` fails it.
  - `[low]` `[patch]` Every `?before=` test returned a short page, so removing `LIMIT %s`
    from the cursor statement failed only the statement-text guard. Added a test arranging
    more than two full pages.
  - `[low]` `[patch]` The `404` for an invented cursor asserted status and code but not
    `cache-control: no-store`, which the sibling routes pin on their own `404`s.
  - `[low]` `[patch]` The Load more re-entrancy guard was untested: every press in the file
    was a single `fireEvent.click`, which flushes its own `act` scope. Deleting the guard
    fired three identical cursor requests and appended the same page three times, green.
    Added a three-clicks-in-one-scope test.
  - `[low]` `[patch]` `setAppending(false)` was guarded by the generation check while
    `inFlight` was cleared unconditionally, so an append invalidated mid-flight would strand
    the wait line and the control. Unreachable today, and the fix is a defensive
    simplification rather than a regression fix - stated as such, not claimed as tested.
  - `[low]` `[patch]` `audit.py`'s header dropped its NFR4 citation while three other files
    still cite NFR4 as the requirement the table exists for.
  - `[low]` `[patch]` `App.tsx`'s comment counted the admin table as "two collections and
    the four verbs behind them"; it is seven routes - two collection reads and five writes.
  - `[low]` `[patch]` The role rule was stated twice in sequence for what the comment beside
    it calls one thing; one guard now wraps both home-panel doors.

### 2026-09-21 - Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 10: (high 0, medium 3, low 7)
- defer: 3: (high 0, medium 1, low 2)
- reject: 22: (high 0, medium 0, low 22)
- addressed_findings:
  - `[medium]` `[patch]` No test tied a cell to the column above it. The header row was
    pinned exactly and every value assertion was scoped to a *row*, which `within` satisfies
    wherever in that row the string is - so swapping the Who and Target cells left all 56
    tests green, and the log would have named the deleted account as the principal that
    deleted it. Added `puts each value under the column that names it`, a positional
    `toEqual` over the six cells of `EDITED` (whose actor and target differ). Mutation-checked:
    transposing the two `<td>`s fails that test and only that test.
  - `[medium]` `[patch]` `asEntries` guards both call sites but only the first page's guard
    was exercised - every cursor reply in `audit-log.test.tsx` was well-formed, so narrowing
    the append to `body as AuditLogEntry[]` left the suite green. An unguarded append reaches
    `detailsText`, whose first statement is `Object.keys(entry.details)`, which throws during
    render and takes the rows already read down with it. Added
    `refuses a second page it could not understand, and keeps the first`; the narrowing
    mutation now fails it.
  - `[medium]` `[patch]` The cursor's query-parameter name was two string literals in two
    languages with nothing between them - `before: UUID | None` on the route and
    `CURSOR_PARAM = 'before'` in the screen - and each suite asserted against its own copy.
    This is the product's first query parameter, and an unknown one is *ignored* rather than
    refused, so a rename on either side would answer the first page to every Load more: the
    log repeating its newest fifty rows forever, green. Added `CURSOR_PARAM` to
    `shared_schema/audit.py` and `AUDIT_CURSOR_PARAM` to the twin - the same argument
    `PAGE_SIZE` already makes - pinned by a parity test and by a route-signature test.
    Mutation-checked from both sides.
  - `[low]` `[patch]` `test_the_route_declares_the_role_check_and_lives_under_admin` asserted
    `READ_AUDIT.startswith("/admin/")`, a tautology over this file's own literal, and never
    walked the route for `require_administrator` - it stayed green with the dependency
    deleted while claiming in its name to be what would catch that. Now walks the dependency
    tree as `test_admin_authorization.py:_declares` does.
  - `[low]` `[patch]` `_arrange` hard-coded `actor_user_id` and `target_user_id` to `None`
    for every row it could write, so `assert newest["actor_user_id"] is None` held for any
    arrangement and proved nothing about the case it named - and two of the nine contract
    fields were never once serialized with a value. Both are parameters now, with
    `test_an_entry_with_an_actor_serializes_both_id_halves` as the contrast.
  - `[low]` `[patch]` `assert "password" not in body.lower()` swept the whole serialized
    body, in which `password_claimed`, `password_changed` and `password_change_refused` are
    legitimate values of the `action` column. It passed only because no test here happened to
    arrange one. The row is now arranged deliberately and the claim is asserted per field
    against the markers credential material would actually carry.
  - `[low]` `[patch]` The `WHEN_FORMAT` doc block opened with "No second parse guard:
    `asEntries` has already run every element through `isAuditLogEntry`..." and closed with
    "No second parse guard here either, for the reason above" - a back-reference to itself.
    The duplicate is removed.
  - `[low]` `[patch]` The cursor was interpolated into the request path raw, safe only
    because `isUuid` had already refused anything else - a coupling the comment stated
    outright. Now `encodeURIComponent`, so the safety is local to the line rather than
    conditional on a narrower two files away staying exactly as strict. Unobservable today
    by construction, so it carries no test and is not claimed to.
  - `[low]` `[patch]` The last acceptance criterion requires the `ui-ux-pro-max` pre-delivery
    checklist to be run against the screen (epics.md:170) and nothing recorded that it was.
    Run this pass; it passes. Recorded under Design Notes, with the two token-level
    observations it raised deferred rather than acted on, since both are product-wide tokens
    the spine owns.
  - `[low]` `[patch]` `</content>` and `</invoke>` - tool-call scaffolding, not content - had
    been committed into the tail of this spec file. Removed.


### 2026-09-21 - Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 0, medium 0, low 4)
- defer: 1: (high 0, medium 0, low 1)
- reject: 24
- addressed_findings:
  - `[low]` `[patch]` The module docstring's list of what is deliberately *not*
    here omitted the omission the story's own first deferred item calls the most
    serious one: reading the log writes no entry. The list now says so, and says
    why it waits on the retention and volume answers the spine defers, so the
    deferral and the module agree.
  - `[low]` `[patch]` `when()` built an `Intl.DateTimeFormat` per cell per
    render - constructing the formatter is the expensive half, and the table
    only grows, so every Load more re-formatted every row already on screen from
    scratch. One module-level formatter now, `.format()` at the cell.
  - `[low]` `[patch]` The focus rescue fired on every last page, not only for a
    reader standing on the control it removes. The control is deliberately
    focusable throughout the request precisely so a keyboard Administrator can
    tab off it, and a reader who had tabbed to Back was dragged into the table
    when the page landed - the screen taking focus rather than saving it. Now
    rescued only when focus is on the control or has already fallen to `<body>`.
    Mutation-checked: dropping the guard fails the new test and only that test.
  - `[low]` `[patch]` The I/O matrix's demotion row reads as one sequence the
    assembled app can never paint - the reconciler redirects before this
    screen's next request - and nothing recorded that the implementation chose
    that branch or where each half is verified. Stated in Design Notes.


## Design Notes

**Why keyset pagination, when `GET /admin/users` deliberately has none.** `users.py:634-642`
argues that FR-10 is *every* account and that a page would hide one — and tells the next reader to
measure before reaching for pagination. The measurement is already in the repo: `users` is bounded
by the staff Rocell employs, while `audit_log` grows by a row per sign-in, per failed sign-in and
per account change, forever, in a table no principal in the product may prune (AD-4 grants no
`DELETE`). The two surfaces answer different questions, and the migration that created the table
wrote the index for this one:

```sql
-- infra/migrations/20260921T1000_create_audit_log.up.sql:113-118
-- The chronological read Story 1.13 renders, newest first. `id DESC` is the
-- tiebreaker rather than decoration: ... a sort on `created_at` alone would
-- have no total order to page through.
CREATE INDEX IF NOT EXISTS audit_log_created_at_idx ON audit_log (created_at DESC, id DESC);
```

Offset paging is wrong here for the same reason: new rows land at the top between two requests, so
page two would repeat what page one showed. The keyset compares the whole `(created_at, id)` pair
against the oldest row already rendered, which is stable under insertion.

**Why the cursor is one id and not a timestamp-plus-id pair.** A pair is two query parameters that
are only valid together, which needs a hand-written "both or neither" refusal FastAPI cannot
express. One id is self-consistent, is a value the client already holds, and — because the table
has no delete path — can only fail to resolve if a caller invented it, which is what the `404`
says. The statement resolves the pair itself:

```sql
WHERE (created_at, id) < (SELECT created_at, id FROM audit_log WHERE id = %s)
ORDER BY created_at DESC, id DESC
LIMIT %s
```

**Why the response is a bare array and the client counts against a published page size.** The envelope everywhere else in
this product is the *error* envelope; every success body is the thing itself
(`users.py:658-700` argues it). A `{items, has_more}` wrapper for one boolean would make this the
only shaped success body in the API. Instead the page size is published in the shared contract,
so a page shorter than `PAGE_SIZE` *is* the end and nothing has to be told to the client per
request. The client must **not** infer the size from the length of the first page: a log of five
entries would then look like a full page of five, and every short log — which is every log early
in this product's life — would offer a Load more that fetches nothing. The one press that remains
is the log whose length is an exact multiple of the page size, which is a press, not a defect, and
cheaper than a second body shape.

**Why `action` is `str` on the wire while `record()` still takes `AuditAction`.** The column
deliberately has no CHECK constraint (`audit.py:80-87`), the vocabulary grows with Epics 2 and 3,
and corrective entries are inserted by hand as the owner. A closed enum on the read would mean the
one table that can never be rewritten has a viewer that refuses to display parts of it. Writes
stay constrained because `record()` is the only writer the application has.

**Why the screen has no orange.** DESIGN.md's rule is one accent-filled primary action per screen.
This screen has no primary action — it is a record, and every control on it (Back, Try again,
Load more) is navigation. Painting Load more orange would make "fetch fifty more rows" the most
important thing on an Administrator's security surface. The stylesheet asserting **zero** accents
is the enforceable form of that.

**Where the demotion row is actually observable, and why it is two halves.** The matrix's
demotion row reads as one sequence — the next request is refused, the screen shows that refusal,
and the door is gone. In the assembled app it is two facts that cannot both be painted, and the
implementation chose the branch EXPERIENCE.md:95 asks for: the session reconciler in `App.tsx`
re-reads the role and swaps the screen out *before* this screen's own next request, so a demoted
Administrator is redirected to the home panel rather than left reading a refusal. The refusal is
still real and still what the server answers, which is why it is verified at the surface where it
is observable: `test_audit_read.py` pins the `403` at HTTP, `audit-log.test.tsx` pins the alert
wording on an isolated screen whose mount is refused, and the App-level suite pins the door and
the table disappearing together after a `visibilitychange`. No single test walks the whole
sentence, because under this branch there is no frame in which the whole sentence is true — which
is the stronger of the two readings, since the weaker one paints an error at a Staff user on a
surface they may not see.

**Why no monospace, despite the addresses.** `DESIGN.md:186` scopes the `code` role to product
Codes and flags it as an unconfirmed assumption. Stretching an unconfirmed role onto timestamps and
IP addresses is a design decision this story has no mandate to make; the columns use the normal
type roles, and the question is recorded as deferred rather than answered unattended.

**The `ui-ux-pro-max` pre-delivery checklist, run 2026-09-21 (epics.md:170).** Queried
`"scrollable region keyboard focus"` and `"data table responsive horizontal scroll"` against
`--domain ux`, then walked `references/pro-rules.md`'s checklist. The screen passes. Item by item,
against what is actually in the file rather than against intent:

- **Touch targets.** Back, Try again and Load more are `<button>`, which `global.css:77-86` gives
  `min-height`/`min-width: var(--touch-target-min)` (44px) on *both* axes. The stylesheet
  deliberately does not restate it.
- **Focus states.** `global.css:93` puts an accent `:focus-visible` outline on everything and
  `AuditLogScreen.module.css` never writes `outline` at all, so nothing here can suppress it. The
  scroll container is `tabIndex={0}` with `role="region"` and `aria-labelledby`, so the last
  column is reachable without a pointer — which is exactly result 1 and result 4 of the focus
  query.
- **Contrast.** Row text `--color-muted-text` `#736F82` on `--color-surface` `#FFFFFF` is 4.86:1;
  the failure sentence `--color-destructive` `#E30425` is 4.87:1; the three secondary controls'
  `--color-primary` `#131B5E` is 15.6:1. All clear 4.5:1. Two token-level observations fall below
  their thresholds and are deferred rather than acted on here, because both are product-wide
  tokens the spine owns rather than anything this screen chose.
- **Icon discipline.** Not applicable and deliberately so: this screen renders no icon and no
  emoji. Every control is a text label.
- **Reduced motion.** `global.css:98-106` neutralises animation, transition and scroll behaviour
  under `prefers-reduced-motion: reduce`, and this screen declares none of the three, so there is
  nothing to neutralise.
- **Responsive.** `.scroller`'s `max-width: 100%; overflow-x: auto` is the checklist's own
  prescription for a table at phone width (result 2 of the table query) and keeps the *page* from
  scrolling sideways at 375px. No fixed pixel width anywhere; `.details` caps on `--measure-prose`,
  which is in `ch`.
- **Colour is not the only indicator.** The failure state is red *and* a sentence in a
  `role="alert"`; the disabled control is dimmed *and* `aria-disabled`.

Two checklist areas do not apply to this product: it defines no dark theme (no
`prefers-color-scheme` block exists in `tokens.css`), and it has no safe-area chrome — the shell,
not this screen, owns the app bar.


## Verification

**Commands:**

- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings,
  `tsc --noEmit`).
- `make test` — expected: exit 0; the database tests run against the ephemeral cluster.
- `uv run pytest apps/api/tests/test_audit_read.py shared/schema/tests/test_audit.py -q` —
  expected: exit 0.
- `uv run pytest apps/api/tests/test_source_guards.py apps/api/tests/test_forced_change_gate.py
  apps/api/tests/test_admin_authorization.py apps/api/tests/test_no_registration.py
  apps/api/tests/test_audit_immutability.py apps/api/tests/test_audit_login_events.py
  apps/api/tests/test_audit_user_events.py infra/tests -q` — expected: exit 0. The only changes
  in this set are the two route-table literals and one comment in `test_source_guards.py`; no
  assertion, regex or fixture in any of them is edited.
- `cd apps/web && npm test` — expected: exit 0, including the new `audit-log.test.tsx`.
- `git status --porcelain infra/ shared/schema/shared_schema/user.py` — expected: empty. No
  migration, no grant change, no edit to the existing contract.
- `git diff --stat apps/api/api` — expected: `audit.py` and `main.py` only.
- Prove each new guard load-bearing by breaking what it guards, then restoring it: drop
  `ORDER BY` from `_SELECT_LATEST_ENTRIES` (the ordering and tiebreaker tests fail, the rest pass);
  change `<` to `<=` in the keyset predicate (the no-overlap test fails); remove
  `Depends(require_administrator)` (the authorization tests and both direction guards fail);
  remove `response.headers.update(NO_STORE)` (the no-store test fails); give the client a `limit`
  parameter (the statement-text test fails); add a hover rule to the audit stylesheet (the
  `audit-log-row` test fails); add one row-end button (the controls `toEqual` fails).

**Manual checks (if no CLI):**

- `make migrate` against a fresh database, `make dev`, sign in as the seeded Administrator,
  provision and edit a user, then open the audit log from the home panel: the sign-in, the
  provisioning and the edit are the top three rows, newest first, each naming the Administrator,
  the target, the time and `127.0.0.1`, and nothing on any row is clickable.
- Sign in as a Staff user: the home panel shows no audit entry at all, and
  `curl -b <staff cookie> https://localhost/api/admin/audit` answers `403`.

## Auto Run Result

Status: done

**Summary of implemented change.** Story 1.13 gives the append-only audit log its read surface.
One Administrator-only route, `GET /admin/audit`, whose `SELECT` statements live in
`apps/api/api/audit.py` beside the `INSERT` so the table keeps exactly one owning module, returns
entries newest-first in fixed 50-row pages walked by a keyset cursor over `(created_at, id)` - the
order and the tiebreaker the migration's `audit_log_created_at_idx` was created for in Story 1.12.
The entry shape, the page size and the cursor's parameter name are the product's third shared
contract (`shared_schema.audit` and its TypeScript twin), into which `AuditAction` moved.
`AuditLogScreen` renders it as DESIGN.md's `audit-log-row`: the one table in the product with no
row-end control at any role. No migration, no grant change, no new dependency; `infra/`, the
existing `User` contract and the seven modules the spec puts out of bounds are untouched.

This was a second follow-up review pass over the whole diff since `9f7c511`, entered because the
previous pass set `followup_review_recommended: true`. It changed no route, no statement, no state
machine and no test expectation: the four patches are one docstring omission, one formatter
hoisted out of a render loop, one focus guard narrowed, and one design decision written down.

**Files changed this pass:**

- `apps/api/api/audit.py` - the module docstring's "Still not here" list now names the one
  omission it was missing: the read itself is not recorded.
- `apps/web/src/screens/AuditLogScreen.tsx` - one module-level `Intl.DateTimeFormat` instead of one
  per cell per render; the focus rescue is now conditional on the reader still standing on the
  control that is about to be removed (or on nothing).
- `apps/web/src/__tests__/audit-log.test.tsx` - `leaves the reader where they moved to while the
  page was in flight`, which the narrowed guard makes pass and the old unconditional rescue fails.
- `_bmad-output/implementation-artifacts/spec-1-13-view-audit-log.md` - this pass's triage log, one
  deferred item, and a Design Note recording which reading of the demotion row the implementation
  chose and where each half of it is verified.

**Review findings breakdown.** Four review layers ran in parallel over the full 5704-line diff.
4 patches applied (high 0, medium 0, low 4); 1 item deferred (low); 24 rejected. The rejections
are chiefly: bookkeeping about the deferred-work ledger and `sprint-status.yaml`, which the
orchestrator owns and which this run does not write; five restatements of items the spec's
`deferred` list already carries (no refresh control, unbounded `details`, the non-object `details`
500, the transaction-timestamp paging skew, and visual claims asserted over stylesheet text);
unreachable inputs that the contract or the database already refuses (empty-string emails, a
non-UUID cursor, a `404` for a cursor the client itself rendered on a table with no delete path);
a claim that the route-declaration test passes vacuously on an unrecognised route object, which is
wrong - it raises; and the observation that an append failure keeps the table on screen where the
I/O matrix's "Load fails" row says otherwise, which is the better of two defensible readings,
argued in the source and pinned by its own test, and was rejected on the same grounds last pass.

**Follow-up review recommendation: false.** Patched this pass: high 0, medium 0, low 4.
Score = 3 x 0 + 1 x 4 = 4, which is below 5.

**Verification performed:**

- `make lint` - exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, `tsc --noEmit`).
- `make test` - exit 0; 1072 pytest tests against the ephemeral cluster (unchanged) and 1037
  vitest tests across 20 files (1036 before this pass, +1).
- `uv run pytest apps/api/tests/test_audit_read.py shared/schema/tests/test_audit.py` - 67 passed.
- `uv run pytest` over the seven guard modules and `infra/tests` - 325 passed. None of them is
  edited this pass.
- `git status --porcelain infra/ shared/schema/shared_schema/user.py` - empty.
  `git diff --stat apps/api/api` against the baseline - `audit.py` and `main.py` only.
- The one patch that can be proved load-bearing was proved by mutation and restored byte-for-byte:
  dropping the `owed` condition from the focus rescue fails the new test, 1 of 58, and nothing
  else. The formatter hoist is an efficiency change with identical output, and the two prose
  patches carry no test; neither is claimed as a fix.

**Residual risks.**

- Unchanged from the previous pass, and none of them moved: the acceptance criterion's sentence is
  still verified in two halves that nothing joins, because there is no end-to-end harness in this
  repository; every visual claim is still asserted by regex over the stylesheet's text, with no
  mockup for this surface to check the six-column composition against; and reading the log still
  leaves no trace. All are recorded as deferred, and the last one is now stated in the module
  docstring as well.
- `apps/web/src/__tests__/session-expiry.test.tsx` remains intermittently flaky, pre-existing and
  unrelated. Every run reported above was clean.
