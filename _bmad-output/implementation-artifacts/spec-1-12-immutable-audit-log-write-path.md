---
title: 'Story 1.12 — Immutable Audit Log (write path)'
type: 'feature'
created: '2026-09-21'
baseline_revision: '65569510397d6478831f54a87524ef1ba6d3712e'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/infra/README.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The audit log has no retention, partitioning or archival path, and the
      malformed-address login branch appends a row per request from an
      unauthenticated caller the throttle cannot count.
    evidence: |-
      AD-4's grant model denies the application role DELETE, so no principal in
      the product can prune the table - `api/audit.py` states this as a virtue.
      The malformed-address path in `login` previously touched no database at
      all; it now takes a pool connection and writes an entry, and it is
      deliberately uncounted because the address carries a NUL and cannot be a
      `login_attempts` key. An attacker appending a control character to every
      guess therefore grows an unprunable table at request rate. Nothing
      (partitioning, an owner-run archival runbook, a volume alert in
      `infra/README.md`) answers what happens when it fills the disk.
    location: >-
      apps/api/api/audit.py, apps/api/api/auth.py (login)
    severity: medium
  - summary: >-
      There is no erasure path for the personal data the log now keeps
      permanently.
    evidence: |-
      `details.changed` records name and email before/after values,
      `user_deleted` records the deleted account's address, and `target_email`
      survives a hard delete by design (AD-10). Combined with "no update or
      delete path at any level", a departed staff member's name and address
      become unremovable. The delete route's docstring presents this as the
      point of the snapshot rule without noting it is also a data-protection
      commitment nobody has signed off.
    severity: medium
  - summary: >-
      ARCHITECTURE-SPINE.md AD-4 is now narrower than the shipped design in two
      places, and was not amended.
    evidence: |-
      AD-4 reads "`source_ip` is read only from the trusted reverse-proxy's
      forwarded-IP header"; the implementation reads the non-forgeable TCP peer
      when no header is configured. AD-4 also reads "the application's database
      role"; the implementation adopts `rocell_app` over the owner's DSN at
      connection startup rather than authenticating as it (DW-111). Both
      choices are argued at length in `api/audit.py` and `api/db.py`, but the
      next person implementing against AD-4 reads the unamended rule. Amending
      a planning artifact is an architect's call, not an unattended build's.
    location: >-
      _bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md
    severity: medium
  - summary: >-
      The seeded Administrator and `make reseed-admin` are user changes that
      still write no audit entry, and the middle path the architecture review
      suggests was not weighed.
    evidence: |-
      `infra/README.md`'s "Not audited, and not an oversight" section argues
      that inventing an actor is worse than a gap. The UX/architecture review
      rubric proposes, for the structurally identical `scripts/ingest` case,
      an entry "attributed to an operator/service USER row, with `source_ip`
      null or a documented sentinel for offline runs". That option - a NULL
      actor with `details.source = "cli"` - is never considered, and
      AGENTS.md:17 requires the log to cover user changes without exempting
      console ones.
    location: >-
      infra/rocell_infra/seed.py
    severity: medium
  - summary: >-
      Nothing asserts the universal "every mutating route writes an entry" at
      the surface where it could regress.
    evidence: |-
      Coverage is per-handler HTTP tests plus one sweep over `api/users.py`'s
      five routes. The new source guards catch a *second* writer of the table,
      never an *omitted* one, so a route added in Epic 2 or 3 that forgets its
      entry fails nothing. The three existing route-table walkers
      (`test_admin_authorization.py`, `test_forced_change_gate.py`,
      `test_no_registration.py`) are the precedent for the missing test: walk
      `create_app()`'s table and require every mutating route to be either on a
      written allowlist or observed writing an entry.
    location: >-
      apps/api/tests
    severity: medium
  - summary: >-
      `login_failed` records the targeted account in `actor_user_id` while
      `login_refused_locked`, written for the same unauthenticated caller,
      leaves the actor NULL.
    evidence: |-
      `_count_and_refuse` passes `actor_id=user_id` - the account being guessed
      at, not whoever made the request, whose identity was never proven. The
      matrix in this spec's frozen intent-contract prescribes exactly that, and
      no information is lost because `target_user_id` carries the same value,
      but the two unauthenticated events now disagree about what the actor
      column means. Story 1.13 renders one of these as "who did it" and must
      settle it.
    location: >-
      apps/api/api/auth.py (_count_and_refuse)
    severity: low
  - summary: >-
      A failed login snapshots the Python-folded address while a successful one
      snapshots the column Postgres stored, so two entries about one account
      can carry different addresses.
    evidence: |-
      `_count_and_refuse` writes `actor_email`/`target_email` from `email_key`
      (Python `strip().lower()`); `_authenticate`'s success path writes
      `user_row["email"]`. `api/users.py` already documents at length, for
      `_INSERT_USER` and `edit_user`, that the Python fold and Postgres's
      `lower()` are not guaranteed to agree on non-ASCII addresses. The failure
      path knows the row whenever `user_id` is not None and could use the
      stored value there.
    location: >-
      apps/api/api/auth.py (_count_and_refuse)
    severity: low
  - summary: >-
      `source_ip` is stored as `text` where `inet` would make the validation a
      database property.
    evidence: |-
      The column holds an `ipaddress.ip_address()`-validated string. `inet`
      would enforce that in the same place the grants are enforced (the
      migration's own argument for preferring the database over code
      discipline), normalize `::1` against its expanded form, and hand FR-22's
      anomaly work containment and CIDR operators. The cost is that psycopg3
      returns `ipaddress` objects for `inet`, so every assertion comparing to a
      string would change - which is why it was not done under review.
    location: >-
      infra/migrations/20260921T1000_create_audit_log.up.sql
    severity: low
  - summary: >-
      The trusted-header reader assumes exactly one trusted hop; behind two
      proxies it records the inner proxy's address as the user's.
    evidence: |-
      `source_ip` takes the last element of the last header line - correct for
      one trusted hop. With `client, real-client, edge1` the recorded value is
      the inner proxy's: a plausible but wrong address, which is the outcome
      the function's own docstring says the design exists to avoid. A
      configurable hop count would settle it; nothing in the README's "whatever
      your edge layer uses" guidance distinguishes the case.
    location: >-
      apps/api/api/audit.py (source_ip)
    severity: low
  - summary: >-
      `TRUSTED_PROXY_HEADER` is read per request with no startup validation, so
      a typo records NULL for the life of a deployment with nothing surfacing
      it.
    evidence: |-
      Every other configuration value in this service is resolved once at
      startup and fails loudly (`database_url` refuses to default). A misspelt
      header name instead produces a silently empty column - the precise
      failure the root README warns about in bold. Reading it per request is
      what lets tests monkeypatch it, so the fix is a startup check rather than
      a different read.
    location: >-
      apps/api/api/audit.py
    severity: low
  - summary: >-
      An `options` parameter already present in `DATABASE_URL` is silently
      overridden by the pool's `kwargs`.
    evidence: |-
      `create_pool` passes `"options": CONNECTION_OPTIONS` in `kwargs`, which
      libpq resolves after the connection string, so an operator who set
      `?options=-c statement_timeout=5s` loses it without warning. Merging the
      two (`conninfo_to_dict(url).get("options")` plus the role) would preserve
      both. No operator sets one today.
    location: >-
      apps/api/api/db.py (create_pool)
    severity: low
  - summary: >-
      A sign-in that spends the cookie it arrived with deletes that session and
      writes no `sessions_revoked` entry.
    evidence: |-
      `_authenticate` calls `delete_session(conn, rocell_session)` before
      issuing the new one, so a session the log claims to cover ends with only
      the `login_succeeded` row to show for it. Every other revocation in this
      story - both password writes, the expired-credential path, a
      deactivation - records one. Consistency, not loss: the event is
      inferable from the login entry.
    location: >-
      apps/api/api/auth.py (_authenticate)
    severity: low
  - summary: >-
      `details` is an untyped `dict[str, Any]` whose key vocabulary lives in
      `api/auth.py` and `api/users.py` rather than in the module that owns the
      log.
    evidence: |-
      `api/audit.py` describes `AuditAction` as the log's whole vocabulary, but
      the `REASON_*` and `CAUSE_*` constants are plain module constants in
      `api/auth.py`, and the keys a reader must know (`reason`, `cause`,
      `count`, `changed`, `locked_until`, `sessions_revoked`) are declared
      nowhere in one place. Story 1.13's renderer has to import refusal reasons
      from the auth module and guess at the rest.
    location: >-
      apps/api/api/audit.py
    severity: low
  - summary: >-
      `GRANT rocell_app TO current_user` is unguarded in the shared-cluster case
      the surrounding `DO` block is written for.
    evidence: |-
      The `CREATE ROLE` catches `duplicate_object` because a second database in
      the same cluster may already hold the role - but if that database was
      migrated by a different owner, the unguarded `GRANT` then fails for want
      of ADMIN OPTION on a role this user did not create. Failing loudly is
      arguably right (the application cannot adopt a role it is not a member
      of), which is why it was not patched; the comment block argues the first
      half of the scenario and misses the second.
    location: >-
      infra/migrations/20260921T1000_create_audit_log.up.sql
    severity: low
  - summary: >-
      CLAUDE.md still describes `make migrate`'s environment contract as
      `DATABASE_URL` plus `SEED_ADMIN_*`, which is now incomplete.
    evidence: |-
      The migration added in this story creates a database role, so the
      migrating role needs CREATEROLE or superuser. That prerequisite was
      documented in the migration header, `infra/README.md`, `README.md`, the
      Makefile and `make help`, but CLAUDE.md's Commands table was left alone
      deliberately: it is the project's own instruction file, not product
      documentation, and editing it is the user's call rather than an
      unattended run's.
    location: >-
      CLAUDE.md
    severity: low
  - summary: >-
      Nothing verifies at startup that the pool's `-c role=rocell_app` was
      actually adopted, so a missing role or membership surfaces as a hang
      rather than a named failure.
    evidence: |-
      `create_pool` calls `pool.open(wait=False)`, so a DSN whose role is not
      a member of `rocell_app` is refused by libpq at connect time and every
      request instead dies on the 10-second `POOL_TIMEOUT_SECONDS` acquisition
      failure. That is the most likely new deployment failure this story
      introduces, and `api/db.py`'s own precedent is the opposite: it refuses
      to default `DATABASE_URL` and fails loudly. A probe in `lifespan` would
      settle it; the spec's Code Map pins `lifespan` as unchanged, so this was
      not done under review.
    location: >-
      apps/api/api/db.py (create_pool), apps/api/api/main.py (lifespan)
    severity: medium
  - summary: >-
      An active lockout appends a `login_refused_locked` row per request from
      an unauthenticated caller, with no counter and no bound.
    evidence: |-
      The intent-contract matrix prescribes exactly this ("Attempt during an
      active lockout ... One `login_refused_locked` row; no counter write"),
      so it is not a deviation - but it is a second unbounded-growth path
      beside the malformed-address branch already recorded above, and it needs
      no malformed input to reach. Once an address is locked, every further
      guess is a free append to a table no principal in the product may prune.
      Coalescing repeats within the lock window, or counting refusals, would
      settle it; either is an intent-level change.
    location: >-
      apps/api/api/auth.py (login, the two lockout gates)
    severity: medium
  - summary: >-
      `user_deleted` records no session count, while the less destructive
      `user_deactivated` does.
    evidence: |-
      `deactivate_user` calls `delete_sessions_for_user` and writes
      `details.sessions_revoked`; `delete_user` relies on the `ON DELETE
      CASCADE` at `users.py` and records nothing, so "how many devices did
      this delete sign out" is unrecoverable the moment the row is gone -
      which is the class of fact AD-10's snapshot rule exists to preserve.
      The matrix does not require it, which is why it was not patched.
    location: >-
      apps/api/api/users.py (delete_user)
    severity: low
  - summary: >-
      Session revocation is encoded two incompatible ways, so Story 1.13 must
      union two shapes to answer one question.
    evidence: |-
      The two password paths write a separate `sessions_revoked` row carrying
      `details.count`; a deactivation instead writes `details.sessions_revoked`
      on the `user_deactivated` row. Both follow the matrix, which prescribes
      the first and is silent on the second. Neither key is declared in
      `api/audit.py`, the module that describes `AuditAction` as the log's
      whole vocabulary.
    location: >-
      apps/api/api/audit.py, apps/api/api/users.py (deactivate_user)
    severity: low
  - summary: >-
      `login_refused_locked` leaves `target_user_id` NULL even when the locked
      address names a real account.
    evidence: |-
      The first lockout gate refuses before any `users` read - that is what
      makes the refusal cost one indexed lookup - so the row genuinely has no
      id in hand. The consequence is that a lockout cannot be joined to the
      account it was against without matching on the email snapshot, which the
      entry above about the Python fold versus Postgres's `lower()` shows is
      not always the same string. Distinct from the actor-column disagreement
      already recorded above, which is about `login_failed`.
    location: >-
      apps/api/api/auth.py (login, the two lockout gates)
    severity: low
  - summary: >-
      The down migration's `REVOKE rocell_app FROM current_user` does not
      revoke what its comment says, and is unguarded against a missing
      ADMIN OPTION.
    evidence: |-
      The header says that after the revert "the owner is no longer one of its
      members", but the statement names `current_user` - the role running the
      revert, which need not be the role the `up` granted. A revert run by a
      second operator silently leaves the original membership behind, and a
      revert run by an operator without ADMIN OPTION on the role raises. This
      is the mirror of the hazard already recorded above for the `up`'s
      unguarded `GRANT`, on the reverse path, and failing loudly is arguably
      right for the same reason.
    location: >-
      infra/migrations/20260921T1000_create_audit_log.down.sql
    severity: low
  - summary: >-
      `audit_log_created_at_idx` is the table's only index; the columns an
      operator and FR-22 will filter on carry none.
    evidence: |-
      The index serves Story 1.13's chronological page. "Everything this
      Administrator did" filters `actor_user_id`, "everything that happened to
      this account" filters `target_user_id`, and FR-22's anomaly work filters
      `action` - all sequential scans today. Because nothing may prune this
      table, the index is only ever built against a monotonically growing
      relation, so deferring it gets strictly more expensive. Which indexes
      the read surface needs is Story 1.13's to decide, which is why this was
      not added here.
    location: >-
      infra/migrations/20260921T1000_create_audit_log.up.sql
    severity: low
  - summary: >-
      The two Python AD-4 guards treat prose inconsistently, so the rule can
      be explained in a `#` comment but not in a docstring.
    evidence: |-
      `test_nothing_climbs_back_to_the_table_owner` strips whole-line `#`
      comments through `_without_comments`; `test_nothing_mutates_the_audit_table`
      strips nothing, and neither strips docstrings. A future module docstring
      writing "never `UPDATE audit_log`" or "never `SET ROLE`" therefore fails
      the build - the "guard somebody argues with rather than obeys" outcome
      the comments say they exist to avoid. Stripping docstrings needs an AST
      walk rather than a line filter, which is why it was not patched.
    location: >-
      apps/api/tests/test_source_guards.py
    severity: low
  - summary: >-
      Address forms a real reverse proxy emits - a bracketed host with a port,
      an RFC 7239 `for=` element, a zone-suffixed link-local address - all fail
      `ip_address()` and record NULL.
    evidence: |-
      `source_ip` takes the last comma-separated element and hands it straight
      to `ipaddress.ip_address()`. An IPv6-aware edge commonly writes
      `X-Forwarded-For: [2001:db8::1]:443`, `Forwarded: for="[2001:db8::1]"`
      carries quotes and a `for=` prefix, and `fe80::1%eth0` carries a zone -
      none parses, so a correctly configured deployment silently logs an empty
      column for every request. That is the "configured and silently empty"
      failure the root README warns about in bold, and it is distinct from the
      unvalidated-header-name entry above: here the header name is right and
      the value is well formed. Stripping brackets, a port and a `for=` prefix
      before validating would settle it; which forms to accept is a deployment
      contract question the README's "whatever your edge layer uses" guidance
      does not answer.
    location: >-
      apps/api/api/audit.py (source_ip)
    severity: medium
  - summary: >-
      Activating an account that is already active writes a `user_activated`
      entry for a change that did not happen.
    evidence: |-
      `activate_user`'s own docstring says "Idempotent on an already-active
      account: 200, same row, nothing to say", and then records an entry
      indistinguishable from a real reactivation; `deactivate_user` has the
      same shape with `sessions_revoked: 0`. `logout` takes the opposite
      position in this very change - "a row saying otherwise would be the log
      recording an event that did not happen, which is a worse defect in an
      audit log than a missing one" - so the two halves of the story disagree.
      The matrix prescribes an entry for each of the five admin writes that
      succeeds and a 200 is a success, so resolving it means either dropping an
      entry the matrix requires or adding a `details` key the docstring argues
      against: an intent-level call.
    location: >-
      apps/api/api/users.py (activate_user, deactivate_user)
    severity: medium
  - summary: >-
      `login_refused_locked` writes an explicit `locked_until: null` where
      `login_failed` omits the key, so one fact has two encodings in `details`.
    evidence: |-
      Both lockout gates pass `details={"locked_until": _locked_until_iso(state)}`
      unconditionally, and that helper returns `None` for a state with no lock;
      `_count_and_refuse` instead adds the key only when it has a value. A
      reader of the log therefore cannot tell "no lock" from "not recorded"
      without knowing which action wrote the row. Distinct from the vocabulary
      entry above, which is about which keys exist rather than how absence is
      spelled.
    location: >-
      apps/api/api/auth.py (login, _count_and_refuse)
    severity: low
  - summary: >-
      The `.sql` guards duplicate `test_source_guards.py`'s scanning helpers in
      a second module, and live under `apps/api` though they only read
      `infra/migrations`.
    evidence: |-
      `_at`, the comment-blanking helper and the mutation regex now exist twice
      - `test_source_guards.py` (`_without_comments`, whole-line `#`) and
      `test_audit_immutability.py` (`_statements`, truncate at `--`) - with the
      same intent and different implementations. A later fix to one (docstring
      stripping, a new verb, an `ONLY`-qualified table) will not reach the
      other, which is the failure mode the last two review passes both found in
      the line-by-line scans. Moving the `.sql` pair to `infra/tests` beside the
      migrations it reads would also put it where somebody editing a migration
      looks.
    location: >-
      apps/api/tests/test_audit_immutability.py, apps/api/tests/test_source_guards.py
    severity: low
  - summary: >-
      `api/audit.py`'s headline claim to be the only file naming `audit_log` is
      false as written, and `api/db.py` stays clean only by accident.
    evidence: |-
      The migration pair, `conftest.py`, four test modules and both READMEs all
      name the table; the guard that is cited as enforcing the claim exempts
      `tests` and reads no `.sql`. `api/db.py` passes only because
      `create_audit_log` has no word boundary before `audit` - documented at
      `db.py`, so rewording that comment to "the audit_log migration" would
      fail the build for no substantive reason. The claim is true of the
      application's own modules and should say so; tightening the guard to
      match the sentence instead is the larger change.
    location: >-
      apps/api/api/audit.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** Every privileged write in the product today leaves no durable record of who did it.
A provisioning leaves only `created_at`, an edit only `updated_at` (which the next login
overwrites), a hard delete nothing at all, and a failed login only a counter keyed on an address.
AGENTS.md:17, FR-20 and NFR4 require an append-only log covering logins, failed logins and every
user change with who / what / when / source IP — and AD-4 requires that immutability be enforced
at the **database-role** level, not by code discipline, so it survives a later bug.

**Approach:** One new `audit_log` table, written through one new module (`apps/api/api/audit.py`)
that owns the only `INSERT` statement against it. A migration creates the table **and** the
product's first non-owner database role, `rocell_app`, granted `SELECT, INSERT` on `audit_log`
and full DML on every other table; `apps/api`'s pool adopts that role at connection startup
(`options=-c role=rocell_app`), so an `UPDATE` or `DELETE` against the log is refused by
PostgreSQL itself. Nine existing handlers gain an audit write and a `source_ip` dependency that
reads a configured trusted-proxy header, never an unconfigured one. No new route: Story 1.13 owns
the read surface.

## Boundaries & Constraints

**Always:**

- **The write is part of the unit of work, not a side effect.** Every audit insert sits inside the
  same `with conn.transaction():` as the change it records; where the change is a refusal on an
  autocommit connection (a failed login), the insert commits the same way the throttle counter
  already does. An audit insert that fails **fails the request** — it is never swallowed. This
  deliberately breaks the module's precedent for secondary writes (`_touch_session`, `_mirror`,
  `_sweep`); see Design Notes.
- **`apps/api/api/audit.py` is the only file in the repo that names the `audit_log` table**, exactly
  as `sessions.py` and `throttle.py` own theirs. New guards in `tests/test_source_guards.py`.
- **No `UPDATE`, `DELETE` or `TRUNCATE` against `audit_log` exists anywhere** — not in application
  code, not in any migration (infra/README.md:15), not in a test helper. A wrong entry is corrected
  by inserting a corrective entry (AD-4).
- **`source_ip` is never read from a header unless `TRUSTED_PROXY_HEADER` names one.** Unset, the
  value is the TCP peer (`request.client.host`), which is not client-supplied. Set, the named
  header is the only source and the peer is ignored. Every value is validated with
  `ipaddress.ip_address()` and stored as `NULL` when it does not parse.
- **Actor and target are AD-10 snapshots — id *and* email columns, no foreign key** to `users`.
  A hard delete (Story 1.11) must not be blocked by, or cascade into, a table the application role
  holds no `DELETE` on. This is the decision `apps/api/api/users.py:110-113` hands to this story.
- **Every SQL statement is a module-level `_UPPER_SNAKE` constant with a parameterized body**, sync
  `def` handlers, `response.headers.update(NO_STORE)` first, `#:` blocks arguing *why* above every
  new constant. Migrations are a matched `.up.sql`/`.down.sql` pair, `IF NOT EXISTS` throughout,
  and use nothing newer than PostgreSQL 13 (infra/README.md:328).
- **No password, password hash, session token or token hash ever reaches an audit row** — not in a
  column, not in `details`. The address a failed login submitted *may* be recorded: that is the
  one place with AD-4's protections, which is exactly why `throttle.py:504` refuses to log it.

**Block If:**

- Satisfying AD-4 appears to require a second connection string, a committed credential, or a
  choice of hosting/secret store. It does not: the role is adopted over the existing
  `DATABASE_URL`. If that proves impossible, HALT rather than inventing a deployment contract —
  hosting and secrets management are Deferred decisions in the spine.
- A change to `shared/schema` appears necessary. It does not: no route returns an audit entry in
  this story, so the entry shape is server-side only and Story 1.13 owns the shared contract and
  its TypeScript twin.

**Never:**

- **Never add a route.** Not `/admin/audit`, not a debug read. Story 1.13 owns the read surface,
  and the three route-table tests must pass unchanged.
- **Never use a trigger or a rule to enforce immutability.** AD-4 names the grant model; a trigger
  is app-adjacent logic the table owner can drop, and `updated_at` already has no trigger (DW-17).
- **Never write audit rows from `scripts/ingest`, `infra/rocell_infra/seed.py` or any migration.**
  Seeding and reseeding happen outside the application, with no actor and no request; infra's
  "Not audited yet" section stays true and must say why rather than being deleted.
- **Never `SET ROLE`, `RESET ROLE` or `SET SESSION AUTHORIZATION` from application code**, and
  never `DROP ROLE` in a `.down.sql` — a role is cluster-scoped and every test database shares the
  cluster.
- **Never log an audit failure and continue.** Never add a private log path beside this one.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Successful login | Valid credentials | One `login_succeeded` row inside the same transaction as `_RECORD_LOGIN` and `issue_session`; actor = the user, target = the user, `source_ip` set | No error expected |
| Failed login, unknown address | Address names no row | One `login_failed` row, `actor_user_id` `NULL`, `target_email` = the submitted address, `details.reason = "unknown_account"`; response still `401 unauthorized` | `401` envelope, unchanged |
| Failed login, wrong password / deactivated / lapsed credential | Row exists | `login_failed` with `actor_user_id` and `target_user_id` set and `details.reason` naming the cause; the four causes are indistinguishable to the caller and distinct in the log | `401` envelope, unchanged |
| Failed login crosses the lockout threshold | 10th cumulative failure | The same `login_failed` row carries `details.locked_until`; no second action | `401` envelope |
| Attempt during an active lockout | Address locked | One `login_refused_locked` row; no counter write (unchanged) | `429` + `Retry-After` |
| Malformed address (NUL / control character) | Unsendable address | One `login_failed` row, `target_email` `NULL`, `details.reason = "malformed_address"` — the address itself cannot be stored in `text` | `401` envelope |
| Logout | Valid cookie | One `logged_out` row, actor = the session's user | No error expected |
| Logout with no or unknown cookie | Nothing to delete | **No row.** Nothing happened and no actor is known | `204`, unchanged |
| Temporary credential claimed | `POST /auth/password` succeeds | Two rows in one transaction: `password_claimed`, then `sessions_revoked` with `details.count` | No error expected |
| Password changed | `POST /auth/password/change` succeeds | Two rows: `password_changed`, `sessions_revoked` | No error expected |
| Lapsed credential discovered mid-request | `set_password` finds the credential expired and revokes every session | One `sessions_revoked` row with `details.cause = "credential_expired"` — the silent revocation `auth.py:827-834` calls a security event in its own right | `401` envelope |
| Wrong current password | `change_password` refused | One `login_failed`-shaped row? **No** — one `password_change_refused` row, actor = the signed-in user (DW-72) | `403` envelope |
| Provision / edit / deactivate / activate / delete a user | Any of the five admin writes succeeds | One `user_provisioned` / `user_edited` / `user_deactivated` / `user_activated` / `user_deleted` row inside that handler's transaction; actor = the Administrator, target = the affected row as a snapshot; `user_edited` carries `details.changed` as `{field: {from, to}}` over the three text columns only | No error expected |
| An admin write is refused (`403`, `404`, `409`) | Floor refusal, unknown id, Staff caller | **No row.** Nothing was written, so there is nothing to record | The route's existing envelope |
| `UPDATE audit_log` through the application pool | Any statement | `psycopg.errors.InsufficientPrivilege` — the role holds no grant | Refused by PostgreSQL |
| `DELETE FROM audit_log` / `TRUNCATE audit_log` through the pool | Any statement | `InsufficientPrivilege` | Refused by PostgreSQL |
| A user row is hard-deleted | Story 1.11's `DELETE` | Every audit row naming that user survives with its snapshot intact; the delete is not blocked | No error expected |
| The audit insert itself fails | `INSERT` grant revoked mid-flight | The surrounding transaction rolls back — the user row is **not** written — and the request answers `500` | `500` envelope |
| `TRUSTED_PROXY_HEADER` unset, client sends `X-Forwarded-For: 1.2.3.4` | Spoof attempt | `source_ip` is the TCP peer, never `1.2.3.4` | No error expected |
| `TRUSTED_PROXY_HEADER=x-real-ip`, header absent or unparseable | Misconfigured edge | `source_ip` is `NULL`; the peer is **not** used as a fallback | No error expected |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**

- `_bmad-output/planning-artifacts/epics.md` **lines 322–333** — Story 1.12's clauses verbatim,
  including "enforced at the database-role level, not just application code" and "`source_ip` is
  captured only from the trusted reverse-proxy header, never a raw client-supplied one";
  **line 57** (NFR4); **line 117** (UX-DR8 belongs to 1.13, not here).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` **line 59** — FR-20; **line
  61** FR-21 is Story 1.13.
- `ARCHITECTURE-SPINE.md` — **AD-4 (lines 64–69)**, the whole of this story's rule, including the
  `source_ip` trust boundary and "the specific proxy/hosting choice is Deferred"; **AD-10 (102–104)**
  snapshot-not-FK, whose "Prevents" clause names the audit log by name; **line 217** the ERD's
  `USER ||--o{ AUDIT_LOG_ENTRY`; **lines 256–261** the four ERD columns (`id`, `action`,
  `source_ip`, `created_at`) — a floor, not a ceiling; **line 26** `scripts/ingest` is outside the
  audit trail by design; **line 173** "never ad hoc logging"; **line 283** backup/DR is Deferred.
- `AGENTS.md` — **line 17** (append-only, who/what/when/source IP), **line 14** (parameterized SQL
  only), **line 15** (no secret in a fixture), **line 11** (server-side authz), **line 34**
  (migrations forward-only and reversible, never edit an applied one), **line 22** (raise rather
  than work around).
- `infra/README.md` — **lines 9–27** (the migration contract: matched pair, naming, one concern,
  one transaction, `IF NOT EXISTS` so a truncated ledger replays), **line 15** (no migration may
  add an UPDATE/DELETE path to the audit table), **lines 328–329** (nothing newer than
  PostgreSQL 13).
- `_bmad-output/implementation-artifacts/deferred-work.md` — **DW-77** (610–616, *this story's to
  close*: provisioning writes no audit entry, "Story 1.12 owns the write path"), **DW-63**
  (498–504, a lockout is unrecorded), **DW-72** (570–576, unlimited `current_password` guessing
  with "no record anywhere until Story 1.12"), **DW-61** (482–489, `updated_at` stopped meaning "an
  Administrator changed this"), **DW-55** (434–440, a per-source-IP counter — **not** this story),
  **DW-12** (89–95, no logging configuration), **DW-17** (129–135, no `updated_at` trigger — the
  precedent for not using a trigger here either), **DW-13** (97–104, no correlation id).
  Format: `### DW-<n>:` then `origin/location/source_spec/severity/reason/status`, one blank line
  between entries; highest in use is **DW-110** (line 874), so new entries start at DW-111.

**Files that already exist and constrain the shape:**

- `apps/api/api/db.py` (127 lines) — **`create_pool` (L69–84)** is where the role is adopted: add
  `"options": "-c role=" + APPLICATION_ROLE` to the existing `kwargs` dict (L80), and a
  `#:`-documented `APPLICATION_ROLE = "rocell_app"` constant beside `DATABASE_URL` (L39). `lifespan`
  (L87) and `get_connection` (L121) are unchanged. The docstring's transaction paragraph (L12–17)
  gains the new invariant. **`options` must not be assembled from a variable that could carry SQL —
  it is a fixed constant, and `test_source_guards`'s interpolation regex only looks at SQL verbs.**
- `apps/api/api/auth.py` (1183 lines) — six write points. `login` (L407/408) takes the **pool**, not
  a connection: the two `with pool.connection()` blocks are L467 and L501, the lockout refusals are
  L476 and L520, and the malformed-address rejection at L456–457 has **no connection** and needs a
  new short block. `_count_and_refuse` (L344) is the single funnel for unknown account (546–548),
  corrupt digest (560–568), wrong password (570–571), deactivated (575–576), lapsed credential
  (583–584) and vanished-mid-login (634–638) — it gains `source_ip` and a `reason`.
  `_authenticate`'s success transaction is **L587**, beside `_RECORD_LOGIN` (L588). `logout` (L681/682)
  must only write when `delete_session` actually removed a row. `set_password` (L807/808): the
  expired-credential revocation at **L851–868** and the success transaction at **L897** (two rows).
  `change_password` (L1062/1063): the wrong-current-password refusal at **L1130–1132** and the
  success transaction at **L1155** (two rows). **Three docstring blocks are falsified and must be
  rewritten**: L64–72, L827–834, L1109–1113.
- `apps/api/api/users.py` (1374 lines) — five write points, and the `administrator` parameter that
  every handler's docstring says is "unread in the lines below on purpose" **becomes read** here;
  those sentences must be corrected. `create_user` (L475/476) writes a bare autocommit `INSERT`
  (L545) and **must gain an explicit `with conn.transaction():`** so the row and its entry are
  atomic. `edit_user` txn **L952**, with `current` (the `FOR UPDATE` read at L956) and `row` giving
  the before/after diff; place the entry after `carry_failures` (L1006–1023). `deactivate_user` txn
  **L1215**, after `delete_sessions_for_user` (L1240) so `details.sessions_revoked` is known.
  `activate_user` txn **L1289**. `delete_user` txn **L1361**, entry after `_DELETE_USER` (L1367)
  using `current` (L1365) as the target snapshot. **Docstrings to rewrite:** L105–113 (the module's
  "No audit entry" block, which already states this story's AD-4/AD-10 conclusion), L508–513, L929–933,
  L1204–1207, L1282–1283, L1354–1357.
- `apps/api/api/dependencies.py` (230 lines) — `NO_STORE` (L78), `current_user` (L143),
  `require_claimed_user` (L170), `require_administrator` (L193). **Not edited**: the `source_ip`
  dependency lives in `audit.py`, beside the module that consumes it, so `dependencies.py` keeps
  meaning "the authorization chain". L20–30 is the argument against middleware that this story
  obeys by using a dependency.
- `apps/api/api/sessions.py` — `delete_sessions_for_user` (L366) **returns the rowcount**, which is
  `details.count` on every `sessions_revoked` row; `delete_session` (L359) returns nothing today and
  must report whether it deleted, so `logout` can stay silent on a no-op. `_SELECT_SESSION` (L157),
  `issue_session` (L267), `lookup_session` (L278) unchanged.
- `apps/api/api/throttle.py` — `record_failure` (L451) returns the `AttemptState` whose
  `failure_count` and `locked_until` go into `details`; `attempt_state` (L431) is the read behind
  the two lockout gates. **The module is not edited**: the audit write stays in `auth.py`, so
  `throttle.py` keeps its single responsibility and its L500–508 comment only needs its last
  sentence corrected (the address may now be recorded, in the log that has AD-4's protections).
- `apps/api/api/main.py` — `create_app` (L130), the four exception handlers (L149–152). **Not
  edited.** No middleware is added (L20–30 of `dependencies.py` is the standing argument).
- `infra/migrations/20260918T1000_add_login_throttling.up.sql` / `.down.sql` — **the structural
  model to copy**: `-- Story N.N — <purpose>.` opener, long `--` prose header saying what is
  deliberately absent and stating "**Apply this before deploying the code that reads these
  objects.**", aligned three-column DDL with per-column comments, `IF NOT EXISTS` throughout; the
  down opens `-- Reverts <up filename>, restoring the previous shape: …` and names indexes
  explicitly.
- `infra/migrations/20260917T1200_create_users.up.sql` **L13–14** — `id uuid PRIMARY KEY DEFAULT
  gen_random_uuid()`, core since PostgreSQL 13, no extension. The pattern for the new table's key.
- `infra/rocell_infra/migrate.py` — `VERSION_PATTERN` (L56), `_run_body` (L265–299) passes the whole
  file to `conn.execute()` with no parameters, so multi-statement bodies and `DO $$ … $$` blocks
  work; `_apply` (L318–336) wraps each migration in one transaction under an advisory lock.
  **Not edited.** A `GRANT`/`CREATE ROLE` body is executed exactly like any other DDL.
- `apps/api/tests/conftest.py` — `SEED_MIGRATION_VERSION` (L54), `database_url` (L153, a new
  database per test in a shared cluster), `migrated_url` (L170, migrations applied), `conn` (L191,
  **the superuser** — privileged, so it can still `UPDATE audit_log` and must not be the connection
  an immutability test uses), `make_user` (L218), `client` (L254), `_with_database` (L74).
  **A new fixture is needed**: a connection built the way the product builds one, i.e. through
  `db.create_pool(migrated_url)`, so the role is actually adopted.
- `apps/api/tests/test_source_guards.py` (231 lines) — `SESSIONS_HOME` (L55), `THROTTLE_HOME` (L58)
  and the fragmented-pattern convention (L61–63) are the model for `AUDIT_HOME`;
  `test_the_scan_reaches_the_files_it_claims_to` (L87–104) must name the new module; the
  login-attempts guard (L180–206) is the shape to copy; the negative controls (L209–231) are
  mandatory for each new regex.
- `apps/api/tests/test_no_registration.py` — **L202–213** the exact route-path set (unchanged: this
  story adds no route) and, critically, **`SOURCE_PATTERNS` (L78–86)**, which scan every `.py`,
  `.ts` and `.sql` under `apps/`, `infra/`, `scripts/`, `shared/` for `\bnew\s+account\b` and
  `\bcreate\s+(an?\s+)?account\b` **in prose and comments**. The new migration header and module
  docstrings must say "provision" / "provisioned account", never those phrases.
- `apps/api/tests/test_admin_authorization.py` L508–536 and `apps/api/tests/test_forced_change_gate.py`
  L55–75 — route-table walkers that must pass **unchanged**; adding a dependency to a handler does
  not disturb either, adding a route would.
- `apps/api/tests/test_login_throttling.py` **L626–631** — the assertion that the submitted address
  is absent from the *application log*. It stays, and gains a sibling asserting the address **is**
  in the audit row.
- `infra/tests/test_runner_unit.py` **L33–45** — `test_the_repository_migrations_are_a_valid_plan`
  pins the five versions as a literal list. The new version joins it.
- `shared/schema/` — **not edited.** `shared_schema/__init__.py`'s `__all__` (L23–34) and the
  Python/TypeScript parity tests (`tests/test_user.py` L147–190) are the reason: a Python model
  with no TypeScript twin would violate the package's stated rule, and there is no web consumer
  until Story 1.13.
- `apps/web/src/screens/EditUserScreen.tsx` **L73–74** and `apps/web/src/screens/UserListScreen.tsx`
  **L285–287** — "**No audit entry.** Story 1.12 owns the append-only log and is owed one by…".
  Both become false. **Comment-only edits**; no web behaviour changes and no web test changes.
- `README.md` **lines 22, 111–115, 153–155, 180–182, 212–214** and `infra/README.md` **lines 15,
  307–308, 318–324** — every sentence predicting this story. `infra/README.md`'s "Not audited yet"
  section stays (seeding runs outside the application) but must say *why* rather than "that log
  arrives with Story 1.12".

## Tasks & Acceptance

**Execution:**

- `infra/migrations/20260921T1000_create_audit_log.up.sql` + `.down.sql` — **new.** The up creates
  `audit_log` (`id uuid PRIMARY KEY DEFAULT gen_random_uuid()`, `created_at timestamptz NOT NULL
  DEFAULT now()`, `action text NOT NULL`, `actor_user_id uuid`, `actor_email text`,
  `target_user_id uuid`, `target_email text`, `source_ip text`, `details jsonb NOT NULL DEFAULT
  '{}'::jsonb`) with **no foreign keys** (AD-10) and one index
  `audit_log_created_at_idx (created_at DESC, id DESC)` for Story 1.13's chronological read. Then
  the role model: a `DO $$ … EXCEPTION WHEN duplicate_object THEN NULL … $$` block creating
  `rocell_app` with **no attributes** — adoption through `options=-c role=` needs membership,
  not `LOGIN`, and no password, because a credential is a deployment concern and never
  committed —
  `GRANT rocell_app TO current_user` via `EXECUTE format(…)` so the owner may adopt it,
  `GRANT USAGE ON SCHEMA public`, `GRANT SELECT, INSERT, UPDATE, DELETE ON users, sessions,
  login_attempts`, and on `audit_log` **`GRANT SELECT, INSERT` only**. The header must state: why
  the role is created here rather than in its own migration (the grant model is meaningless until
  the role is the one the application uses), that the role is **cluster-scoped** while each test
  gets its own database, that a future table needs its own `GRANT` in its own migration or the
  application cannot read it, and "**Apply this before deploying the code that reads these
  objects.**" The down drops the index and the table and revokes the three table grants, and
  **does not `DROP ROLE`** — it says why (the role is cluster-scoped and shared by every database)
  and that the code must be rolled back first. Avoid the phrases `test_no_registration.py` forbids.
- `infra/tests/test_runner_unit.py` — add `"20260921T1000_create_audit_log"` to the literal plan at
  L37–41.
- `apps/api/api/db.py` — add `APPLICATION_ROLE = "rocell_app"` with a `#:` block arguing AD-4, and
  `"options": f"-c role={APPLICATION_ROLE}"`-equivalent (a concatenation of constants, not an
  f-string around SQL) to `create_pool`'s `kwargs`. Argue in the comment why startup `-c role=`
  beats a `SET ROLE` in a `configure` hook: `RESET ROLE` returns to the startup value, so it
  cannot climb back to the owner.
- `apps/api/api/audit.py` + its docstring — **new, and the only file that names the table.**
  `AuditAction(StrEnum)` with the thirteen values the matrix uses (`login_succeeded`, `login_failed`,
  `login_refused_locked`, `logged_out`, `password_claimed`, `password_changed`,
  `password_change_refused`, `sessions_revoked`, `user_provisioned`, `user_edited`,
  `user_deactivated`, `user_activated`, `user_deleted`); `TRUSTED_PROXY_HEADER` env-var name and a
  `source_ip(request: Request) -> str | None` FastAPI dependency implementing the rules above;
  `_INSERT_ENTRY` as one parameterized module constant; and
  `record(conn, *, action, actor_id=None, actor_email=None, target_id=None, target_email=None,
  source_ip=None, details=None) -> None` that inserts and lets any `psycopg.Error` propagate.
  The docstring states the "Not here." boundary: no read surface (1.13), no shared contract type
  (1.13), no catalogue or scan events (Epics 2–3), no seed events (they run outside the app).
- `apps/api/api/auth.py` — thread `source_ip` through `login`, `logout`, `set_password`,
  `change_password` and `_count_and_refuse`; write the rows the matrix names at L456, L476, L520,
  L587, L698, L851–868, L897, L1130, L1155. Rewrite the three stale docstring blocks.
- `apps/api/api/users.py` — write the five rows inside the existing transactions, wrapping
  `create_user`'s `INSERT` in a new one; read the `administrator` parameter; build `user_edited`'s
  `details.changed` from `current` vs `row` over `name`, `email`, `role` only. Rewrite the six
  stale docstring blocks.
- `apps/api/api/sessions.py` — make `delete_session` return whether a row was removed, so a no-op
  logout writes nothing. Correct the docstring sentences that claim the caller count.
- `apps/api/api/throttle.py` — **comment only** (L500–508): the address may now be recorded, in the
  log that has AD-4's protections, and still never in the application log.
- `apps/api/tests/conftest.py` — add an `app_role_conn` fixture built from `db.create_pool(
  migrated_url)` so tests can act with exactly the privileges the product has, and an
  `audit_rows(conn)` helper returning the log in insertion order.
- `apps/api/tests/test_audit_immutability.py` — **new.** The role exists; `SELECT current_user`
  over the product's own pool is `rocell_app`; the `has_table_privilege` matrix
  (`audit_log`: INSERT+SELECT true, UPDATE/DELETE/TRUNCATE/REFERENCES false; `users`, `sessions`,
  `login_attempts`: all four true); `UPDATE`, `DELETE` and `TRUNCATE` through the product pool each
  raise `psycopg.errors.InsufficientPrivilege` while `INSERT` and `SELECT` succeed; a scan of
  `infra/migrations/*.sql` finds no UPDATE/DELETE/TRUNCATE path against the table; a regression test
  that **every** table in `public` except `audit_log` and `schema_migrations` is fully granted to
  the role (so a future migration that forgets its `GRANT` fails here, not in production); and the
  atomicity test — revoke `INSERT` on `audit_log` from the role, call `POST /admin/users`, assert
  `500` **and** that no `users` row was written.
- `apps/api/tests/test_audit_login_events.py` — **new.** Every row of the matrix's login half:
  success; each of the failure causes with its `details.reason`; the threshold crossing carrying
  `locked_until`; the `429` writing `login_refused_locked` and no counter; the malformed address;
  logout writing one row and a no-op logout writing none; both password writes producing their two
  rows; the expired-credential revocation; the wrong-current-password refusal (DW-72). Keep
  `test_login_throttling.py` L626–631's application-log assertion and add its audit sibling.
- `apps/api/tests/test_audit_user_events.py` — **new.** The five admin writes and their actor /
  target snapshots; `user_edited`'s `details.changed` over the three text columns and nothing else;
  a refused write (`403`, `404`, `409`) writing no row; and **the delete clause** — after Story
  1.11's hard delete the target's audit rows survive with their snapshot intact and the delete is
  not blocked.
- `apps/api/tests/test_audit_source_ip.py` — **new.** Unset: a spoofed `X-Forwarded-For` is ignored
  and the peer is recorded. Set: the named header is used, the last comma-separated element is
  taken, an unparseable value and a missing header both give `NULL`, and the peer is never a
  fallback. Prove the reader load-bearing by asserting the spoofed value appears nowhere.
- `apps/api/tests/test_source_guards.py` — add `AUDIT_HOME`, a fragmented `audit_log` pattern, a
  guard that only `AUDIT_HOME` names the table, a guard that no file anywhere carries an
  `UPDATE`/`DELETE FROM`/`TRUNCATE` against it, a guard that no file carries `SET ROLE`,
  `RESET ROLE` or `SET SESSION AUTHORIZATION`, the new entry in
  `test_the_scan_reaches_the_files_it_claims_to`, and a negative control per new regex.
- `apps/web/src/screens/EditUserScreen.tsx`, `apps/web/src/screens/UserListScreen.tsx` —
  **comment only.** The endpoints behind these screens now write audit entries; the log's own view
  is Story 1.13.
- `README.md`, `infra/README.md` — correct every sentence listed in the Code Map; document
  `TRUSTED_PROXY_HEADER` (what it is for, why it is unset by default, and that deploying behind a
  proxy without it records the proxy's address), the `rocell_app` role and the rule that a new
  table needs its own `GRANT`, and keep "Not audited yet" for seeding while saying why.
- `_bmad-output/implementation-artifacts/deferred-work.md` — mark **DW-77** `status: resolved` with
  a `resolution:` line between `reason:` and `status:` (the DW-37 precedent at L289–296). Append
  new entries from DW-111 for anything this story deliberately leaves: the unreplaced deployment
  credential for `rocell_app`, and the absence of a per-source-IP counter (DW-55 stays open).

**Acceptance Criteria:**

- **Given** the application's connection pool, **when** any statement runs through it, **then**
  `current_user` is `rocell_app`, not the table owner, and `UPDATE`, `DELETE` and `TRUNCATE`
  against `audit_log` are refused by PostgreSQL with `InsufficientPrivilege` while `INSERT` and
  `SELECT` succeed — the refusal holds without any application code checking for it.
- **Given** any login, failed login, or user provision/edit/deactivate/activate/delete that
  **succeeds**, **when** the response is returned, **then** exactly one audit row exists for it
  carrying the action, the actor's id and email, the target's id and email as denormalized
  snapshots with no foreign key, the timestamp, and the source IP.
- **Given** an admin write that is refused with `403`, `404` or `409`, **when** the response is
  returned, **then** no audit row was written and no user row changed.
- **Given** the `INSERT` grant is withdrawn, **when** an Administrator provisions an account,
  **then** the request fails and **no** `users` row is written — the entry and the change land
  together or not at all.
- **Given** `TRUSTED_PROXY_HEADER` is unset, **when** a caller sends `X-Forwarded-For`, **then**
  the recorded `source_ip` is the connection's peer address and the submitted header value appears
  in no audit row.
- **Given** a user is hard-deleted, **when** the delete completes, **then** it is not blocked, and
  every audit row naming that user still carries their id and email.
- **Given** the change is complete, **when** `make lint` and `make test` are run, **then** both
  exit 0, `git status --porcelain shared/schema` is empty, and the three route-table tests
  (`test_admin_authorization.py`, `test_no_registration.py`, `test_forced_change_gate.py`) pass
  with no change to their route or path sets — this story adds no route.

## Spec Change Log

## Review Triage Log

### 2026-09-21 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 16: (high 1, medium 6, low 9)
- defer: 15: (high 0, medium 5, low 10)
- reject: 9
- addressed_findings:
  - `[high]` `[patch]` `source_ip()` read the **first** line of a repeated trusted-proxy
    header, so a caller who sent their own `X-Forwarded-For:` line ahead of a proxy that
    appends a second one had their forged value recorded — the exact spoof AD-4 forbids.
    Switched to `getlist(...)[-1]`, then the last element of that line; three new tests,
    including one end-to-end through `POST /auth/login`. Reverting to `get()` fails all three.
  - `[medium]` `[patch]` Both new source guards scanned line by line, so the codebase's own
    multi-line triple-quoted SQL style walked straight through them. Now `finditer` over the
    whole file with the line number recovered from the match offset, `(?:public\.)?` accepted
    before the table name, and whole-line `#` comments stripped for the role-escape guard so
    prose about the rule still reads clean. Multi-line and schema-qualified negative controls added.
  - `[medium]` `[patch]` The migration created `rocell_app` with `LOGIN`. Adoption through
    `options=-c role=` needs membership, not `LOGIN`, so the cluster was gaining a passwordless
    login principal protected only by `pg_hba.conf`. Verified `-c role=` works against a NOLOGIN
    role, then dropped the attribute; DW-111 now names `ALTER ROLE … LOGIN PASSWORD` as the
    stronger form.
  - `[medium]` `[patch]` The down migration's four `REVOKE`s raised outright when the role was
    absent — the mirror of the case the up guards — so the pair was not reversible. Wrapped in a
    `pg_roles` existence check, and the membership the up granted to `current_user` is now revoked too.
  - `[medium]` `[patch]` `source_ip` was asserted on 3 of 18 `record()` call sites; dropping the
    keyword from `edit_user` or `delete_user` broke nothing. Asserted now on at least one entry
    per handler across both event files.
  - `[medium]` `[patch]` Atomicity was promised in nine docstrings and tested for `create_user`
    alone. Added revoke-INSERT tests for `delete_user` and for `logout`, whose transaction wrapper
    is new in this change and was held in place by nothing.
  - `[medium]` `[patch]` The post-delay lockout gate's `login_refused_locked` entry was
    unreachable by every existing test, because they all use the `instant` fixture. Added a test
    that sleeps the real ladder and reaches the second gate.
  - `[low]` `[patch]` `account_vanished` was the one refusal reason with no audit assertion; added
    one that also pins that the entry survives the rolled-back sign-in transaction.
  - `[low]` `[patch]` The counter-write-failure branch's `login_failed` row was unasserted;
    guarding the insert on `state is not None` now fails a test.
  - `[low]` `[patch]` Both event files asserted a literal `source_ip` without isolating
    `TRUSTED_PROXY_HEADER`; autouse `delenv` fixtures added, matching `test_audit_source_ip.py`.
  - `[low]` `[patch]` `test_every_refusal_writes_exactly_one_entry` slept the whole progressive
    delay ladder for a timing-irrelevant assertion; `instant` fixture added.
  - `[low]` `[patch]` Removed the dead `administrator` fixture in `test_audit_immutability.py`.
  - `[low]` `[patch]` Four prose counts of the refusal reasons contradicted each other and the
    code (five / six / four / six over seven constants); all now say seven.
  - `[low]` `[patch]` `test_the_scan_reaches_the_files_it_claims_to`'s comment still said "these
    three" over seven paths.
  - `[low]` `[patch]` `api/db.py` truncated the migration filename to dodge a guard that cannot
    match it; full name restored so the canonical reference is greppable.
  - `[low]` `[patch]` The migration now needs `CREATEROLE` on the migrating role and nothing said
    so; documented in the migration header, `infra/README.md`, `README.md`, the Makefile and
    `make help`.

### 2026-09-21 — Review pass (follow-up)

- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 0, medium 3, low 1)
- defer: 8: (high 0, medium 2, low 6)
- reject: 9
- addressed_findings:
  - `[medium]` `[patch]` **The `GRANT rocell_app TO current_user` block was
    exercised by nothing.** This suite's cluster hands out a superuser, and a
    superuser adopts any role without being a member of it — so deleting that
    block left `test_the_products_own_connection_runs_as_the_application_role`
    and the whole privilege matrix green, while a non-superuser deployment
    could not have opened a single pooled connection (`FATAL: permission
    denied to set role`), failing every request rather than only the audit
    writes. `pg_has_role` is no help for the same reason — it answers true for
    a superuser whatever the catalog says — so the membership is now read out
    of `pg_auth_members` directly. Proved load-bearing: with the block removed,
    exactly one test fails and it is the new one.
  - `[medium]` `[patch]` The three AD-4 source guards scanned `apps/api` and
    `shared/schema` only, so they never read `infra/` or `scripts/` — and
    `infra/rocell_infra/migrate.py` is the one connection in the repo that
    opens on the owner's DSN with **no** `options=-c role=`, holding full DML
    on the audit table. A retention purge, the thing the ledger says this
    table still needs, would land there by default: outside the grant *and*
    outside the guard. Added `AUDIT_SCANNED`/`_audit_sources()` for those three
    guards only (the interpolation rule keeps its narrower corpus, for the
    reason the module docstring gives), plus
    `test_the_audit_scan_reaches_beyond_the_api_package` so the corpus cannot
    drift back. Proved load-bearing: a probe module under `infra/rocell_infra/`
    carrying a multi-line `DELETE FROM audit_log` and a `SET ROLE` now fails
    all three guards; before this change it failed none.
  - `[medium]` `[patch]` `test_no_migration_carries_a_mutation_path_against_the_log`
    and `test_no_migration_drops_the_application_role` scanned line by line —
    the exact defect `test_source_guards.py` had already been corrected for,
    and worse in `.sql`, where every statement in `infra/migrations` is
    written across lines with its columns aligned. `DELETE\n  FROM audit_log`
    and `DROP\n  ROLE` both read as clean, and `public.audit_log` was not
    matched at all. Both scans are now `finditer` over the whole file with the
    line number recovered from the match offset and `(?:public\.)?` accepted;
    positive controls cover the multi-line and schema-qualified shapes, and
    negative controls pin that the permitted `INSERT`, `SELECT`, `GRANT` and
    the down migration's `DROP TABLE` still pass.
  - `[low]` `[patch]` Nothing asserted `audit_log_created_at_idx` exists after
    the up migration. It is the table's only index and it serves a read
    surface that does not exist yet, so deleting the `CREATE INDEX` left the
    whole suite green — `DROP INDEX IF EXISTS` and `DROP TABLE IF EXISTS` are
    both silent about it. Added beside the `sessions` index test that is the
    precedent for it.


### 2026-09-21 — Review pass (follow-up 2)

- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 2, low 5)
- defer: 5: (high 0, medium 2, low 3)
- reject: 14
- addressed_findings:
  - `[medium]` `[patch]` **`rocell_app`'s attributes were pinned by nothing.**
    Dropping `LOGIN` was a medium security finding in the first pass — a
    passwordless login principal guarded only by `pg_hba.conf` — and the
    migration argues it at length, but `rolcanlogin`, `rolsuper`,
    `rolcreaterole` and `rolbypassrls` are not table privileges, so the whole
    grant matrix passes against `CREATE ROLE rocell_app LOGIN` and even against
    a `SUPERUSER` role, which would make every refusal in that module vacuous.
    Added `test_the_application_role_carries_no_attribute_beyond_membership`
    reading `pg_roles` directly. Proved load-bearing: restore `LOGIN` and
    exactly one test fails, and it is the new one.
  - `[medium]` `[patch]` **Two thirds of the down migration was observed by
    nothing.** Its `DROP INDEX`/`DROP TABLE` are covered by the other down
    tests' column-set assertions; the `DO $$ … REVOKE … $$` block is not,
    because no test in either suite reads a privilege *after* a revert —
    `test_audit_immutability.py`'s matrix only ever sees a database migrated
    up. Deleting the entire block left the suite green while a reverted
    database kept `rocell_app` holding full DML on `users`, `sessions` and
    `login_attempts` and the owner still a member of a cluster-scoped role,
    which is the opposite of what the file's header and `infra/README.md`
    promise. Added `test_the_audit_down_takes_back_the_grants_and_the_membership`
    in `infra/tests`, which also round-trips the pair back up. Proved
    load-bearing: with the block removed, exactly one test fails.
  - `[low]` `[patch]` `source_ip` validated with `ipaddress.ip_address()` and
    then stored the *raw* string, so `2001:DB8::1`,
    `2001:0db8:0000:0000:0000:0000:0000:0001` and `2001:db8::1` reached a
    `text` column as three different values for one host — and Story 1.13's
    "everything from this address" filter and FR-22's anomaly work both group
    on that column. Now returns `str(parsed)`. Every existing assertion in the
    suite submits an already-canonical address, which is why nothing caught it;
    a parametrized test now covers both directions.
  - `[low]` `[patch]` `_MIGRATION_DROP_ROLE` shipped with a positive control
    and no negative one, against the Tasks rule of a negative control per new
    regex — and it is the guard that most needs one, since it must not fire on
    `CREATE ROLE`, `GRANT`, `REVOKE`, `DROP TABLE` or `DROP INDEX`, all of
    which the audit pair actually contains.
  - `[low]` `[patch]` `_ROLE_ESCAPE`'s comment block contradicted itself: one
    paragraph stated the guard "matches only inside a **string literal**" as
    current behaviour, and a later one stated the opposite and explained that
    the quote prefix had been removed. The stale paragraph was the one a reader
    hits first, and the `(?!\s*=)` rationale appeared twice. Merged into one
    account that keeps the history without asserting it as the present.
  - `[low]` `[patch]` `_SELECT_ACTOR` selected `id, email` and read only
    `email`; the id it returns is the parameter it was given.
  - `[low]` `[patch]` This spec's own Tasks section still prescribed creating
    `rocell_app` with `LOGIN`, which the first review pass rejected and the
    shipped migration does not do — so the document a re-derivation reads
    specified the thing the code deliberately avoids. Corrected to "no
    attributes", with the membership-not-LOGIN reason.


## Design Notes

**Why a role adopted at connection startup, and not a second connection string.** AD-4 wants the
application's database role to hold no `UPDATE`/`DELETE` on the audit table. The literal reading is
a second login role with its own credential in `APP_DATABASE_URL` — but hosting, CI/CD and secrets
management are all Deferred decisions in the spine, and AGENTS.md:15 forbids a committed
credential, so shipping a second DSN today would mean inventing a deployment contract this story
has no authority to invent. Adopting the role over the existing `DATABASE_URL` gives the same grant
model with no operator change:

```python
kwargs={"autocommit": True, "row_factory": dict_row, "options": "-c role=" + APPLICATION_ROLE}
```

`-c role=` is a startup GUC, so `RESET ROLE` returns to `rocell_app` rather than to the owner —
which is why it is used instead of a `SET ROLE` inside the pool's `configure` hook. The residual
gap is `SET SESSION AUTHORIZATION` / `SET ROLE <owner>`, which a source guard forbids and which no
parameterized statement can reach. The stronger form (a distinct login role with its own secret) is
a deployment-time hardening, recorded as deferred work rather than guessed at here.

**Why the audit write may fail the request.** Every other secondary write in this codebase swallows
`psycopg.Error` — `_touch_session`, `_mirror`, `_sweep`, `delete_expired_sessions`. Those are
tidy-up. This one is the record of record: FR-20 and NFR4 say the log is what makes an action
attributable, so an action that happened with no entry is precisely the state the story exists to
prevent. Inside a transaction the two land together; on a failure path the insert commits the same
way the throttle counter already does. The login endpoint's timing discipline is unharmed: every
input class now does the same amount of database work, and the malformed-address path does *more*
than before, not less.

**Why no foreign key, and why an email column beside each id.** `users.py:110-113` already worked
this out: a hard delete (Story 1.11) plus AD-4's missing `DELETE` grant means an FK from
`audit_log` to `users` would force a choice between blocking the delete and cascading into a table
nothing may delete from. AD-10's snapshot rule, written for Tiles and Reference Images, extends
here by its own wording. The id stays for joining while the row lives; the email is what the entry
still means after it does not.

**Why `source_ip` defaults to the peer rather than to `NULL`.** AD-4 forbids a *raw client-supplied
header*. The TCP peer is not one — it cannot be forged by the caller — and with no reverse proxy in
the repo it is the client. Reading a header only when `TRUSTED_PROXY_HEADER` names one means the
product can never be spoofed by default, and a deployment that puts an edge layer in front
configures it in the same breath as `DATABASE_URL`.

**Why no trigger.** A `BEFORE UPDATE … RAISE` trigger would be application-adjacent logic the table
owner can drop, and DW-17 already establishes that this codebase does not use triggers for
invariants. The grant is the enforcement AD-4 names.

## Verification

**Commands:**

- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings,
  `tsc --noEmit`).
- `make test` — expected: exit 0; the database tests run against the ephemeral cluster or skip with
  the usual "no PostgreSQL available" reason.
- `uv run pytest apps/api/tests/test_audit_immutability.py apps/api/tests/test_audit_login_events.py
  apps/api/tests/test_audit_user_events.py apps/api/tests/test_audit_source_ip.py
  apps/api/tests/test_source_guards.py -q` — expected: exit 0.
- `uv run pytest apps/api/tests/test_admin_authorization.py apps/api/tests/test_no_registration.py
  apps/api/tests/test_forced_change_gate.py infra/tests -q` — expected: exit 0, with only
  `infra/tests/test_runner_unit.py`'s version list changed.
- `git status --porcelain shared/schema` — expected: empty. This story ships no contract change.
- `git diff --stat apps/api/api/throttle.py apps/api/api/dependencies.py apps/api/api/main.py` —
  expected: comment lines only on `throttle.py`, empty for the other two.
- `git diff --stat apps/web` — expected: comment lines only, in exactly two files.
- Prove each new guard load-bearing by removing what it guards, then restoring it: drop the
  `options` entry from `create_pool` (every immutability test fails and the `current_user`
  assertion fails first); change `GRANT SELECT, INSERT` to `GRANT ALL` on `audit_log` (the
  privilege matrix fails); remove one handler's `audit.record` call (that handler's event test
  fails and nothing else does); remove the `TRUSTED_PROXY_HEADER` check so the header is always
  read (the spoof test fails); take `create_user`'s new transaction away (the atomicity test fails
  while every other create test still passes).

**Manual checks (if no CLI):**

- `make migrate` against a fresh database, then `psql`: `\dp audit_log` shows `rocell_app` with
  `ar` (SELECT, INSERT) and nothing else; `SET ROLE rocell_app; UPDATE audit_log SET action='x';`
  is refused.
- `make dev`, sign in, provision and edit a user, then read the table: the rows carry the
  Administrator's id and email, the target's, and a `source_ip` of `127.0.0.1`.
- `make migrate` then `uv run python -m rocell_infra.migrate down --yes` and back up again, on a
  database that already has the role, to confirm the `DO` block and the grants replay cleanly.



## Auto Run Result

Status: done

**Summary of implemented change.** Story 1.12 ships the append-only audit log's write path: one
`audit_log` table, one module (`apps/api/api/audit.py`) that owns the only `INSERT` against it, and
the product's first non-owner database role, `rocell_app`, which the pool adopts at connection
startup so PostgreSQL itself — not application discipline — refuses `UPDATE`, `DELETE` and
`TRUNCATE` against the log (AD-4). Nine handlers across `auth.py` and `users.py` gain an audit
write inside their existing transaction and a `source_ip` dependency that reads a configured
trusted-proxy header and otherwise the non-forgeable TCP peer. No route was added; `shared/schema`
is untouched; Story 1.13 owns the read surface.

**This pass** was a follow-up review of an already-`done` spec (third review pass). It found no
intent gap and no spec defect; it applied seven patches, all of them to verification and prose, and
deferred five findings.

**Files changed in this pass:**

- `apps/api/tests/test_audit_immutability.py` — pins `rocell_app`'s role attributes (NOLOGIN, not
  superuser/createrole/createdb/bypassrls); adds the missing negative control for the `DROP ROLE`
  scan.
- `infra/tests/test_migrate.py` — asserts the audit `down` actually takes back the three table
  grants, `USAGE` on `public` and the role membership, and that re-applying restores them.
- `apps/api/api/audit.py` — `source_ip` returns the parsed address in canonical form rather than
  the spelling it arrived in; docstring says so.
- `apps/api/tests/test_audit_source_ip.py` — parametrized test for that canonicalization, in both
  directions.
- `apps/api/api/auth.py` — `_SELECT_ACTOR` no longer selects an `id` it does not read.
- `apps/api/tests/test_source_guards.py` — `_ROLE_ESCAPE`'s comment block no longer contradicts
  itself about the string-literal narrowing.
- `_bmad-output/implementation-artifacts/spec-1-12-immutable-audit-log-write-path.md` — Tasks
  corrected to prescribe a `rocell_app` with no attributes; triage log and deferred list extended.

**Review findings breakdown.** 7 patches applied (medium 2, low 5); 5 items deferred (medium 2,
low 3) onto this spec's `deferred` list, now 28 entries; 14 rejected — chiefly findings already
recorded as deferred in earlier passes, and the claim that `_count_and_refuse`'s audit write turning
a `401` into a `500` on a broken connection is a defect: the intent contract states that an audit
insert which fails fails the request, so that is the designed behaviour.

**Follow-up review recommendation: true.** Patched this pass: high 0, medium 2, low 5. Score =
3 × 2 + 1 × 5 = 11, which is ≥ 5.

**Verification performed:**

- `make lint` — exit 0 (ruff check, ruff format --check, oxlint --deny-warnings, `tsc --noEmit`).
- `make test` — exit 0; 1005 pytest tests passed against the ephemeral cluster (none skipped) and
  872 vitest tests passed across 18 files.
- `uv run pytest apps/api/tests/test_audit_immutability.py apps/api/tests/test_audit_source_ip.py
  apps/api/tests/test_source_guards.py infra/tests/test_migrate.py -q` — exit 0, 206 passed.
- Both new guards proved load-bearing by breaking what they guard: restoring `LOGIN` on
  `CREATE ROLE rocell_app` and deleting the down migration's whole `DO $$ … REVOKE … $$` block
  together failed exactly two tests, and they were the two added in this pass. Both edits reverted;
  `git diff --stat infra/migrations` is empty against the committed state.
- `git status --porcelain shared/schema` — empty.
- `git diff --stat apps/web` since the baseline — two files, comment lines only.
- `git diff --stat` since the baseline for `dependencies.py` and `main.py` — empty; `throttle.py`
  comment lines only.

**Residual risks.**

- The immutability refusals are proved on a cluster that hands out a superuser. The membership the
  real deployment needs is now read out of `pg_auth_members` and the role's attributes out of
  `pg_roles`, but nothing opens a pool as an ordinary non-superuser owner, so "a missing membership
  surfaces as a named failure rather than a 10-second pool timeout" remains documentation, recorded
  as deferred.
- AD-4's enforcement binds to connections opened by `api.db.create_pool`. Every other principal on
  the database — the migration runner, `seed.py`, `psql` — still connects as the table owner with
  full DML on the log; that residual surface is covered by source-text guards, which is
  code discipline, the thing AD-4 exists not to rely on. Stated in the module's own comments and in
  the deferred list.
- Two unbounded-growth paths into a table no principal in the product may prune (an active lockout,
  and the malformed-address login branch) are prescribed by the intent contract's matrix and remain
  deferred; so does the absence of any retention, partitioning or erasure path.
- `ARCHITECTURE-SPINE.md` AD-4 and `CLAUDE.md`'s Commands table are both now narrower than what
  shipped and were deliberately left alone — amending a planning artifact and the project's own
  instruction file are not an unattended run's call. Both are on the deferred list.
