---
title: 'Story 1.6 — Login Rate Limiting'
type: 'feature'
created: '2026-09-18'
baseline_revision: '8adb3041f57a5827e1cecee3f9f2425c21c1b3a9'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true # score 13 (0 high, 3 medium, 4 low patched); see Auto Run Result
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-rcl_camera_app-2026-08-30/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/EXPERIENCE.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-rcl_camera_app-2026-09-08/DESIGN.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A password spray — one password tried across every staff address — trips
      no counter at all, while every attempt still buys a full Argon2id verify.
    evidence: |-
      `api/throttle.py` keys the counter on the submitted address, which is what
      removes the account-existence oracle a per-account ladder would create.
      The cost is that the per-address counter is blind to the attack that uses
      each address once. FR-4 is written per account and the architecture
      spine's review-security.md already raised this against it, so closing it
      means a second counter — per source IP, or a global failure rate — and a
      decision about what to key it on that FR-4 does not make. `throttle.py`'s
      "Not here" section names FR-22, FR-23 and DW-40 and is silent on this one.
    location: >-
      apps/api/api/throttle.py
    severity: medium
  - summary: >-
      `AttemptState.retry_after()` subtracts a Postgres-produced timestamp from
      the API host's clock, in a module whose whole argument is that every
      decision is made against the database clock.
    evidence: |-
      `locked_until` is written by `now()` inside `_RECORD_FAILURE` and read back
      through `RETURNING`; `retry_after()` then compares it to
      `datetime.now(UTC)`. Skew between the two hosts mis-states the
      `Retry-After` header in either direction. Nothing in the product reads
      that header — `apps/web` is forbidden to render it — so the consequence is
      confined to a conforming third-party client. The fix is to have Postgres
      compute the remaining seconds alongside the lock, which means another
      column in the `RETURNING` list and a second value threaded through
      `AttemptState`, for a header nothing currently consumes.
    location: >-
      apps/api/api/throttle.py (AttemptState.retry_after)
    severity: low
  - summary: >-
      `make reseed-admin` issues a fresh credential that the lock then refuses,
      and clears neither the `login_attempts` row nor `users.locked_until`.
    evidence: |-
      `infra/rocell_infra/seed.py`'s reissue updates `password_hash`,
      `must_change_password`, `temp_credential_expires_at` and `updated_at` only.
      An Administrator locked out by ten failures who reaches for the one
      console tool they have gets a credential that is refused for the remainder
      of `LOCKOUT_DURATION`, and an account whose status still reads locked
      afterwards. Bounded at fifteen minutes, so it is an inconvenience rather
      than the unreachable-product hazard DW-41 describes — but it is the same
      recovery path, and widening the reissue to clear the throttle is a
      decision about what `reseed-admin` is for.
    location: >-
      infra/rocell_infra/seed.py
    severity: low
  - summary: >-
      `login_attempts` grows one row per invented address for a full
      `ATTEMPT_WINDOW`, and those rows are exactly the ones the sweep is
      forbidden to delete.
    evidence: |-
      `_SWEEP_ATTEMPTS` only removes rows whose `last_failure_at` is older than
      `ATTEMPT_WINDOW`, so a dictionary run against thousands of addresses
      leaves every row it creates untouchable for an hour — and `last_failure_at`
      carries no index, so each subsequent failed attempt scans them. The
      migration comment and `infra/README.md` now say this honestly rather than
      claiming a backlog never accumulates. Bounding it means either an index
      paid on every failure or a row-count ceiling with a policy for what to
      evict, and both are measurements this story has no numbers for.
    location: >-
      infra/migrations/20260918T1000_add_login_throttling.up.sql
    severity: low
  - summary: >-
      Changing a user's email address (Story 1.10) leaves the lock on the old
      address string and a stale `users.locked_until` on the account.
    evidence: |-
      The counter's primary key is the submitted address, and `_MIRROR_LOCK`
      matches on `lower(email)`. After an edit, the old string keeps its live
      lock — reachable by anyone who still tries it, which is harmless — while
      the new address starts from zero, which is a lock-evasion path that
      requires an Administrator to walk it. The mirror is never cleared either,
      so the account's status keeps reporting a lock that no longer corresponds
      to anything. Deciding whether a rename carries its counter is Story 1.10's
      to make; nothing here can settle it.
    location: >-
      apps/api/api/throttle.py (_MIRROR_LOCK)
    severity: low
  - summary: >-
      The progressive delay is per-attempt only when attempts are serial: a
      burst that arrives together all reads the same count and pays one rung
      between them.
    evidence: |-
      `login` reads `attempt_state`, sleeps, and only then does the credential
      work that records the failure, so ten simultaneous guesses at a count of
      five all see rung one and all sleep one `DELAY_STEP` in parallel instead
      of paying 1+2+3+4+4 seconds between them. The lockout at
      `FAILURES_BEFORE_LOCKOUT` is unaffected — the increment is AD-8's single
      atomic statement and every failure still lands — and the re-read added
      after the sleep now stops any of them authenticating once the lock is
      written. What is left is that the ladder's *cost* is per round trip
      rather than per attempt. Closing it means making the delay a property of
      the request rather than of the row it read — a queue, a per-address
      semaphore, or counting the attempt before it is processed rather than
      after — and each of those is a different design from the one FR-4's
      "delay before it's processed" describes.
    location: >-
      apps/api/api/auth.py (login)
    severity: medium
  - summary: >-
      `_MIRROR_LOCK` moves `users.updated_at` on an account nobody edited, so
      the column stops meaning "an Administrator changed this".
    evidence: |-
      The mirror sets `updated_at = now()` alongside `locked_until` because
      DW-17 leaves the column to be maintained by hand, and the spec's task
      list asks for exactly that. The consequence is that ten wrong guesses
      from a stranger now bump a timestamp that Stories 1.9 and 1.10 are the
      most likely readers of — a "recently changed" sort, or an optimistic
      concurrency check on the edit form, would both be driven by an attacker.
      Separating them means either a second column or a rule that the mirror is
      not an edit, and which one is right depends on what 1.10 decides
      `updated_at` is for.
    location: >-
      apps/api/api/throttle.py (_MIRROR_LOCK)
    severity: low
  - summary: >-
      DW-54's `session-expiry.test.tsx` flake reproduced twice in three full
      `apps/web` runs during this pass, and not once in six runs of that file
      on its own.
    evidence: |-
      Recorded here as new evidence for an entry that already exists, not as a
      new defect: this pass changed no `apps/web` source. Both failures were
      `findByLabelText(/password/i)` at line 237 exhausting testing-library's
      default 1000ms, and both were on the slow runs (2.78s and 3.12s against a
      steady 1.78s for the 13-file suite). Running the file alone passed 6/6 at
      a flat 1.17s. That points at worker contention across the parallel suite
      rather than at anything in `SessionProvider`, and it narrows DW-54's open
      question — "raise the timeout or find the real cause" — to the first
      option, but raising an async timeout across another story's suite is a
      decision about the harness that this story has no authority to make.
    location: >-
      apps/web/src/__tests__/session-expiry.test.tsx:237
    severity: low
  - summary: >-
      A lockout is a free, repeatable denial of service against a named member
      of staff, and nothing in the product limits or records it.
    evidence: |-
      A locked attempt is refused before any Argon2id work, any counter write
      and any sleep, so holding a colleague out costs an attacker ten cheap
      guesses per quarter hour and nothing else. There is no unlock to reach
      for (FR-5 sends the person to an Administrator; no story gives that
      Administrator a button until 1.10) and no audit entry until Story 1.12.
      This is the mirror image of DW-55 and the direct cost of keying the
      counter on the submitted address — the design note argues the other
      direction only. Closing it means something the requirement does not
      describe: a per-source-IP dimension, a shorter lock for a first offence,
      or an unlock surface. `README.md` now states the exposure plainly; the
      mitigation is a product decision.
    location: >-
      apps/api/api/throttle.py
    severity: medium
  - summary: >-
      FR-4's "visible to Administrators" and FR-5's recovery route are handed to
      Stories 1.9 and 1.10, whose acceptance clauses mention neither.
    evidence: |-
      `throttle.py`, `auth.py`, both READMEs and this spec all say Story 1.9
      renders the lock and Story 1.10 gives an Administrator something to press.
      `epics.md` 1.9 (lines 286-294) asks only for active/deactivated status and
      a last-login timestamp; 1.10 (296-307) is scoped to name, email and role.
      Neither names a lock or an unlock, so as the epic stands the column ships
      and nothing renders it, and FR-5's "goes through an Administrator" has no
      owner. This story cannot widen another story's acceptance clauses, and
      the `User` contract work here is complete either way.
    location: >-
      _bmad-output/planning-artifacts/epics.md:286-307
    severity: medium
  - summary: >-
      Every sign-in now takes two pooled connections instead of one, including
      the overwhelming majority that never sleep.
    evidence: |-
      `login` opens one `pool.connection()` for `attempt_state`, closes it, and
      opens a second for `_authenticate` whether or not `delay` is truthy. The
      split exists so the sleep holds nothing, which only the delayed path
      needs; against `POOL_MAX_SIZE = 10` and DW-34 it doubles acquisition
      pressure on the hottest unauthenticated path in the product to buy
      something the undelayed path does not use. Merging the two blocks when
      `delay` is falsy is straightforward, but it restructures the handler's
      connection lifetime around a cost nobody has measured, and CLAUDE.md is
      explicit that this is the order to do those things in.
    location: >-
      apps/api/api/auth.py (login)
    severity: medium
  - summary: >-
      An address holding a control character is the one rejection that is never
      counted, and it still spends a full Argon2id decoy each time.
    evidence: |-
      `_is_addressable` refuses before the counter is ever reached — necessarily,
      since the counter's key *is* the string Postgres cannot accept — but it
      pays `verify_dummy_password` first, so appending a NUL to every guess buys
      unlimited unthrottled Argon2id work and leaves no row behind. The decoy
      predates this story; what is new is that this is now the only path with no
      counter behind it. There is no oracle in it (the caller already knows the
      address is malformed, and no account can hold one), so the exposure is CPU
      only, and it is the same class DW-55 records for a spray across real
      addresses. Dropping the decoy on this path alone would close it, but the
      decoy's placement is an identical-rejection decision this story should not
      make on its own.
    location: >-
      apps/api/api/auth.py (_is_addressable)
    severity: low
---

<intent-contract>

## Intent

**Problem:** FR-4 is entirely absent. `POST /auth/login` will verify an unlimited number of
credentials against one account at whatever rate a caller can post them, and nothing anywhere in
the product counts a failure. AGENTS.md Policy names login throttling as non-negotiable and
catalogue exfiltration through a compromised account as the primary commercial threat; epics.md
1.6 fixes the two thresholds — a measurable delay from the 6th attempt, a lock on the 10th failure,
visible to Administrators on that user's status.

**Approach:** One Postgres counter row per *submitted email address* (AD-8: rows in Postgres,
mutated by a single atomic increment-and-check), read at the top of every sign-in attempt. From the
6th attempt the handler sleeps a progressive, capped delay before it does any credential work; the
10th failure writes a lock that refuses further attempts with its own distinct code and message
until the lock expires. The lock is mirrored onto `users.locked_until` so an Administrator's account
status carries it, and the `User` contract — both language halves — grows the field Story 1.9's user
list will render.

## Boundaries & Constraints

**Always:**
- **Counted by submitted address, never by account.** An unknown address and a real one accrue
  failures, delays and locks identically. Keying the counter on `users.id` would make the delay an
  account-existence oracle and destroy the identical-rejection invariant this endpoint is built on
  (`api/auth.py` module docstring, `test_login.py::test_every_rejection_is_indistinguishable`,
  EXPERIENCE.md's deactivated-account row). The key is the same lowercased, stripped address
  `_SELECT_CREDENTIAL` is parameterized with.
- **AD-8:** the counter is mutated by one atomic statement — an `INSERT ... ON CONFLICT DO UPDATE
  ... RETURNING` that increments, decides the lock and returns the new state. Never a read followed
  by a write of a value derived from that read. Never in-process memory: it must survive a restart
  and a second `apps/api` instance.
- **One module owns the counter's writes** — `apps/api/api/throttle.py` — enforced by a guard in
  `tests/test_source_guards.py`, as `api/sessions.py` is for the `sessions` table.
- Parameterized SQL only. Every new constant documented with why its value is what it is.
- `users.locked_until` is **status only and is never read to decide anything.** Enforcement reads
  `login_attempts` and nothing else.
- The lockout response is reachable identically for a real and an unknown address, so it leaks
  nothing; it is the one rejection allowed to differ from `INVALID_CREDENTIALS`, because
  EXPERIENCE.md line 93 requires it to.

**Block If:**
- The lockout branch cannot be made reachable for an address with no account — that would trade
  FR-4 against the identical-rejection invariant, and neither may be relaxed without a human.
- Adding `locked_until` to `shared_schema.user.User` turns out to require changing what
  `POST /auth/login` or `POST /auth/password` *return* beyond adding this one key.

**Never:**
- **No unlock surface, and no admin endpoint of any kind.** The lock expires on its own after
  `LOCKOUT_DURATION`; an Administrator-driven unlock has no story and no route to hang on (no
  `require_admin` dependency exists yet). Story 1.9 renders the status; Story 1.10 owns editing a
  user.
- **No countdown anywhere in `apps/web`.** EXPERIENCE.md line 93 is explicit. The API's
  `Retry-After` header is machine-facing and must not be rendered.
- No throttling of `POST /auth/password` (DW-40) or of scanning (FR-23) — epics.md scopes this
  story to login.
- No audit entry for a failed login. Story 1.12 owns the write path and owes this endpoint its
  entries; no private log path is built in the meantime.
- No revocation of live sessions on lockout. FR-4 blocks *attempts*; Story 1.11's deactivation is
  what ends sessions.
- No global concurrency bound on the login handler (DW-34) — the cap on the delay below is this
  story's whole answer to it, and is not a fix for the pool/threadpool mismatch.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First failure | no `login_attempts` row; wrong password | 401 `unauthorized`, `INVALID_CREDENTIALS`, no delay; row created with `failure_count = 1` | Unchanged rejection |
| Failures 2–5 | count 1–4 | Same 401, no delay; count incremented | Unchanged rejection |
| The 6th attempt | count 5 | Handler sleeps `DELAY_STEP` **before** any credential work, then processes normally | Same 401 if the credential is wrong |
| The 9th attempt | count 8 | Sleeps `MAX_DELAY` (the ladder is capped), then processes | Same 401 if wrong |
| A correct password on the 6th attempt | count 5, correct credential | Delay is still paid, then the sign-in succeeds; the row is deleted | No error |
| The 10th failure | count 9, wrong password | `locked_until = now() + LOCKOUT_DURATION` written in the same statement as the increment; `users.locked_until` mirrored; response is 429 `account_locked` with `Retry-After` | The locking response, not `INVALID_CREDENTIALS` |
| Attempt while locked | `locked_until > now()` | 429 `account_locked` **before** any hashing, any counter write and any delay | No credential work is spent |
| Unknown address, 10 attempts | no `users` row at all | Identical behaviour and identical responses to a real account at every step; the `users` mirror updates zero rows | Indistinguishable |
| Correct credential while locked | `locked_until > now()` | Refused: 429, no session issued | The lock wins over the credential |
| First attempt after the lock expires | `locked_until <= now()` | Treated as a fresh run: count resets to 1 on a failure, `locked_until` cleared, no delay | Normal rejection |
| Stale run | `last_failure_at <= now() - ATTEMPT_WINDOW` | Treated as a fresh run for both the delay and the lock | — |
| Counter write fails | `psycopg.Error` from the increment | The failed sign-in is still refused with the same 401; the error is logged and never becomes a 500 | Fails in the safe direction: the attempt is not counted |
| Sweep fails | `psycopg.Error` from the stale-row sweep | Swallowed and logged; the rejection stands | As `login`'s session sweep already does |
| `apps/web` receives `account_locked` | login form submitted | The API's own sentence is shown; **neither field is marked invalid and the typed password is kept** — nothing the user typed is what failed | — |

</intent-contract>

## Code Map

**Read-only sources of truth (do not edit):**
- `_bmad-output/planning-artifacts/epics.md` **lines 244–256** — Story 1.6's acceptance clauses
  verbatim. Also 257–268 (1.7 owns self-service change), 286–294 (1.9 owns the user list and is what
  renders the status), 296–307 (1.10 edits users), 322–334 (1.12 owns audit).
- `_bmad-output/specs/spec-rcl_camera_app/functional-requirements.md` **FR-4** (line 13) and **FR-5**
  (line 15, "a locked-out … user goes through an Administrator" — the reason no unlock surface is
  built here).
- `ARCHITECTURE-SPINE.md` **AD-8** (lines 88–92) — counters are rows in Postgres, one atomic
  increment-and-check, never in-process memory. **AD-3** (58–62) — unchanged by this story.
- `EXPERIENCE.md` **line 93** (lockout: a different message from a wrong-password rejection,
  "temporarily locked", **no countdown**), **line 92** (a deactivated account is refused identically
  — the invariant the email-keyed counter protects), lines 50–57 (voice).
- `AGENTS.md` — "Rate-limit login (progressive delay after 5 failures, lockout at 10)"; migrations
  forward-only and never edited; no committed credentials in fixtures.
- `deferred-work.md` — **DW-34** (`POOL_MAX_SIZE = 10` behind a 40-worker sync threadpool; names
  this story as the owner, and the delay below makes it *worse*, which is why the ladder is capped),
  **DW-40** (`POST /auth/password` is a second Argon2id endpoint; explicitly out of scope),
  **DW-24** (the decoy verify that removes the unknown-address timing signal), **DW-21** (no
  migration checksum — why an applied migration is never edited, comments included), **DW-17**
  (`users` has no BEFORE UPDATE trigger, so `updated_at` is set by hand).

**Files that already exist and constrain the shape:**
- `apps/api/api/auth.py` — `login` (the whole ordering: `_is_addressable` → `_SELECT_CREDENTIAL` →
  `verify_password`/`verify_dummy_password` → the `active` and `credential_expired` checks →
  `_RECORD_LOGIN` → `issue_session` → `delete_expired_sessions` in a swallowed `try`). `_rejected()`
  is the **one** constructor for every 401 and must stay that way. `MAX_EMAIL_LENGTH`,
  `INVALID_CREDENTIALS`, `WEAK_PASSWORD`, `PASSWORD_CHANGE_NOT_REQUIRED` are the module-level
  `NAME = "..."` constants the web parity test reads by regex. `_RECORD_LOGIN` and `_SET_PASSWORD`
  each carry the ten-column `RETURNING` list `User.model_validate` consumes — **the two lists must
  not drift from each other or from `_SELECT_SESSION`.** The email is lowercased and stripped at
  line ~262; that exact value is the counter key.
- `apps/api/api/sessions.py` — `_SELECT_SESSION` selects the same ten `User` columns plus
  `s.id AS session_id` and `needs_touch`, which `lookup_session` `pop`s off before
  `User.model_validate` (`User` is `extra="forbid"`). A new `User` column is added to this list too.
  The module's `logger = logging.getLogger("rocell.api.sessions")` and `_touch_session`'s
  swallowed-`psycopg.Error` handling are the precedent the new module's error handling copies.
- `apps/api/api/db.py` — pooled connections are `autocommit=True` with `dict_row`, so a bare
  `conn.execute` commits on its own and a row is a mutable `dict`. `POOL_MAX_SIZE = 10` — the number
  the delay cap is chosen against.
- `apps/api/api/main.py` — `STATUS_CODES` already maps `429: "rate_limited"`; that is the *routing*
  fallback and is **not** this story's code. `ApiError` carries `headers` through
  `api_error_handler`.
- `shared_schema/user.py` / `shared_schema/ts/user.ts` — one contract in two languages. Python:
  `extra="forbid"`, `AwareDatetime | None`, and the `@field_serializer` list that emits UTC. TS:
  `NULLABLE_TIMESTAMP_KEYS`, `CONTRACT_KEYS`, `USER_KEYS` (sorted), and `isUser`'s exact key-count
  check — a new key must be added to the interface *and* to `NULLABLE_TIMESTAMP_KEYS`.
- `infra/migrations/20260917T1400_track_session_activity.up.sql` — the house style for a migration
  comment (what the column is, what it is **not**, deploy ordering, why no index). **Applied —
  read-only**, as are the three before it.
- `infra/rocell_infra/migrate.py` — `VERSION_PATTERN = ^\d{8}T\d{4}_[a-z0-9]+(_[a-z0-9]+)*$`; every
  `.up.sql` needs a `.down.sql`; the plan is filename-sorted.
- `infra/tests/test_runner_unit.py:33–43` — `test_the_repository_migrations_are_a_valid_plan`
  asserts the shipped version list **exactly**. `infra/tests/test_migrate.py:36–37` names the two
  session versions as constants and line 460+ is the "upgrade a database that already holds rows"
  pattern the new `ALTER TABLE users` needs.
- `apps/api/tests/conftest.py` — `conn`, `client` (https `base_url`), `make_user(role=, active=,
  must_change_password=, temp_credential_expires_at=, name=)` → `Account` with a runtime-generated
  password. The `database_url` fixture is **function-scoped**, so every test gets a fresh database
  and counters never leak between tests.
- `apps/api/tests/test_login.py` — `_rejection_cases` (7 cases, each on a *distinct* address, which
  is why none of them reaches a threshold), `_comparable_headers`,
  `test_every_rejection_is_indistinguishable`, `test_the_unknown_address_path_spends_a_real_verify`
  and `test_a_wrong_password_needs_no_decoy` (both monkeypatch `auth.verify_dummy_password`). All of
  these must keep passing **unchanged**.
- `apps/api/tests/test_source_guards.py` — `SESSIONS_HOME`, the fragment-assembled patterns
  (`_SESSIONS = "sessions"`), `test_only_one_module_writes_the_sessions_table`, and
  `test_the_scan_reaches_the_files_it_claims_to`, which asserts the scan actually reaches the files
  it names. The new guard is written in the same shape.
- `apps/web/src/api/client.ts` — `ApiRequestError` (carries `code` and `status`), `UNAUTHORIZED`,
  `HTTP_UNAUTHORIZED`, `notifyUnauthorized` (fires on **401 only**, so a 429 correctly does *not*
  drop the shell to a "session ended" notice).
- `apps/web/src/screens/LoginScreen.tsx` — `FormError { message, fields }`, `BOTH_FIELDS`, the
  `rejected` branch keyed on `code === UNAUTHORIZED` that wipes the password and focuses it, and the
  `role="alert"` `.error` paragraph that already renders the server's own sentence.
- `apps/web/src/__tests__/error-code-parity.test.ts` — `PYTHON`/`TYPESCRIPT` maps plus
  `it('compares every code the client exports')`, which asserts the set of exported string
  constants in `client.ts` equals the set of Python constant names. **A new exported code without a
  row here fails that test.**
- `apps/web/src/__tests__/{auth-gating,session-expiry,forced-password-change}.test.tsx` and
  `user-contract.test.ts`, `shared/schema/tests/test_user.py` — the `User` fixtures that must grow
  the new key (one occurrence each in the three `.tsx` files, four in `user-contract.test.ts`, five
  in `test_user.py`).
- `README.md` lines 74–98 (the operator account of the cookie) and `infra/README.md` line 48's
  migration table.

## Tasks & Acceptance

**Execution:**

- `infra/migrations/20260918T1000_add_login_throttling.up.sql` / `.down.sql` — create
  `login_attempts (email_key text PRIMARY KEY, failure_count integer NOT NULL DEFAULT 0
  CHECK (failure_count >= 0), locked_until timestamptz, last_failure_at timestamptz NOT NULL
  DEFAULT now())`, and `ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until timestamptz`.
  `IF NOT EXISTS` on both, matching the replay behaviour of the shipped four. Comment, in the house
  style: why the key is the **submitted address** and not `users.id`; that `users.locked_until` is
  **status only, never read for enforcement**, and that a value in the past means "not locked now,
  locked recently"; that there is deliberately no index (same bet on the row count the
  `last_seen_at` migration states, and the same instruction to measure before adding one); and the
  migrate-before-deploy ordering, because `api/throttle.py`, `api/auth.py` and `api/sessions.py` all
  name these objects. `down` drops the column and the table.
- `infra/tests/test_runner_unit.py` — add the new version to the exact plan list.
- `infra/tests/test_migrate.py` — a version constant beside the two existing ones; apply the plan in
  two halves with a pre-existing `users` row in between, so the `ADD COLUMN` is proven against a
  table that already holds rows; and a full `up`/`down` round trip.
- `apps/api/api/throttle.py` — **new, and the only module that writes `login_attempts`.**
  - Constants, each with its reasoning: `FAILURES_BEFORE_DELAY = 5`, `FAILURES_BEFORE_LOCKOUT = 10`,
    `DELAY_STEP = timedelta(seconds=1)`, `MAX_DELAY = timedelta(seconds=4)`,
    `LOCKOUT_DURATION = timedelta(minutes=15)`, `ATTEMPT_WINDOW = timedelta(hours=1)`,
    `ATTEMPT_SWEEP_LIMIT = 100`.
  - `AttemptState` — a frozen dataclass carrying `failure_count`, `locked_until`, and a `locked`
    property; `delay()` returning the sleep this attempt owes.
  - `attempt_state(conn, email_key)` — the pre-attempt read. Returns a zeroed state for a missing
    row, and treats a run as ended (count 0, not locked) when the lock has expired **or**
    `last_failure_at` is older than `ATTEMPT_WINDOW`, so the decision is made from the database
    clock in SQL rather than in Python.
  - `record_failure(conn, email_key)` — one `INSERT ... ON CONFLICT (email_key) DO UPDATE ...
    RETURNING` that resets-or-increments and, when the new count reaches `FAILURES_BEFORE_LOCKOUT`,
    writes `locked_until = now() + LOCKOUT_DURATION` in the same statement. Then mirrors the lock
    onto `users.locked_until` with an `UPDATE ... WHERE lower(email) = %s` that is executed
    unconditionally — it matches zero rows for an unknown address, which is what keeps the two paths
    identical — setting `updated_at = now()` with it (DW-17: no trigger). Then a bounded stale-row
    sweep (`id IN (SELECT ... FOR UPDATE SKIP LOCKED LIMIT %s)` in the shape `_DELETE_EXPIRED`
    already uses, over `email_key`), swallowing `psycopg.Error` with a `logger.warning`.
  - `clear_failures(conn, email_key)` — delete the row. Called on a successful authentication.
  - Module-level `logger = logging.getLogger("rocell.api.throttle")`, matching the other two.
- `apps/api/api/auth.py` — wire it in and nothing else:
  - `ACCOUNT_LOCKED = "account_locked"` and its sentence, in EXPERIENCE.md's register, naming no
    duration. A `_locked(retry_after)` factory beside `_rejected()`, returning `429` with
    `Retry-After` and `NO_STORE`.
  - In `login`, after the address is normalised and `_is_addressable` passes: read the state; refuse
    immediately if locked, **spending no Argon2id work, writing no counter and sleeping nothing**;
    otherwise `time.sleep` the state's delay before the credential lookup. Every existing rejection
    path calls `record_failure` before it raises, and the success path calls `clear_failures` inside
    the existing transaction. Wrap the counter writes so a `psycopg.Error` is logged and the
    rejection still stands — the precedent is the sweep's `try`/`except` at the bottom of `login`.
  - Add `locked_until` to the `RETURNING` lists of `_RECORD_LOGIN` and `_SET_PASSWORD`, keeping the
    two identical.
- `apps/api/api/sessions.py` — add `u.locked_until` to `_SELECT_SESSION`'s user columns. No other
  change; the touch, the bounds and the sweep are untouched.
- `shared/schema/shared_schema/user.py` + `ts/user.ts` — add `locked_until` (nullable UTC
  timestamp) to both halves together: the pydantic field and its `@field_serializer` list, and the
  TS interface plus `NULLABLE_TIMESTAMP_KEYS`. Document on both sides that it is the
  admin-facing status FR-4 requires, that "locked now" is `locked_until > now()`, and that it is
  never what enforcement reads.
- `shared/schema/tests/test_user.py`, `apps/web/src/__tests__/user-contract.test.ts` — the new key
  in every fixture, plus a case proving `isUser` rejects a body missing it and one proving a naive
  datetime is refused, in the shape the existing nullable-timestamp cases use.
- `apps/api/tests/test_source_guards.py` — `test_only_one_module_writes_the_login_attempts_table`,
  matching `INSERT INTO`/`UPDATE`/`DELETE FROM` against a fragment-assembled `login_attempts` and
  allowing only `THROTTLE_HOME`; add that path to `test_the_scan_reaches_the_files_it_claims_to`.
  Reads are deliberately **not** guarded — Story 1.9 has to join this table to render the status,
  and the AD-8 property being protected is that the mutation is one atomic statement in one place.
- `apps/api/tests/test_login_throttling.py` — **new.** Every row of the I/O matrix, with the
  timing constants monkeypatched down so the suite does not sleep in real seconds, plus: that the
  6th attempt measurably sleeps and the 5th does not; that the delay is paid on a *correct*
  credential too; that the ladder is capped at `MAX_DELAY`; that a locked attempt spends no
  `verify_password` and no `verify_dummy_password` (monkeypatch both, as `test_login.py` does);
  that the whole 10-attempt sequence against an address with **no account** produces byte-identical
  statuses, bodies and `_comparable_headers` to the same sequence against a real one; that a
  successful sign-in deletes the row; that an expired lock starts a fresh run; that a stale run
  resets; that the counter survives being driven from two connections (AD-8's concurrency
  property); and that a failing counter write leaves the rejection intact.
- `apps/api/tests/test_login.py`, `test_session_lookup.py`, `test_seeded_login.py` — assert the new
  `User` key where the ten columns are asserted today; confirm the existing rejection and decoy
  tests still pass untouched.
- `apps/web/src/api/client.ts` — `export const ACCOUNT_LOCKED = 'account_locked';` with the comment
  explaining why it is not `unauthorized` (the credential is not what was refused) and why the
  screen must not render a countdown.
- `apps/web/src/screens/LoginScreen.tsx` — branch the existing error handling: on `ACCOUNT_LOCKED`
  show the server's sentence with `fields: []`, keep the typed password, and leave focus alone. No
  new element, no new class, no countdown.
- `apps/web/src/__tests__/error-code-parity.test.ts` — the `account_locked` row in `PYTHON` and
  `TYPESCRIPT`.
- `apps/web/src/__tests__/login-screen.test.tsx` — a lockout case: the message is shown, neither
  input is `aria-invalid`, the password is still in the field, and no number appears in the
  rendered text.
- `apps/web/src/__tests__/{auth-gating,session-expiry,forced-password-change}.test.tsx` — the new
  `User` key in each fixture.
- `README.md`, `infra/README.md` — the throttle in operator terms (the two thresholds, that the lock
  clears itself after 15 minutes, that there is no admin unlock and none is owed until Story 1.10,
  and that the counter is keyed on the submitted address so an unknown one behaves identically), and
  the migration-table row with the migrate-before-deploy ordering.

**Acceptance Criteria:**

- Given an account with five recorded failures, when a sixth sign-in is attempted, then the response
  is measurably later than the fifth by at least one `DELAY_STEP`, and the delay is paid before any
  credential is read or hashed.
- Given nine recorded failures, when a tenth sign-in fails, then that response is `429`
  `account_locked` carrying a message that is not `INVALID_CREDENTIALS` and names no duration, and
  `users.locked_until` for that account is set to a future instant.
- Given a locked account, when a sign-in is attempted with the **correct** password, then it is
  refused with the same `429` and no session row is created.
- Given a locked account, when an Administrator reads that account through the API's `User`
  contract, then the body carries `locked_until` in the future — and given the same account after
  the lock has lapsed, `locked_until` is in the past and a sign-in with the correct password
  succeeds.
- Given an email address with no account, when ten sign-ins are attempted against it, then every
  status, body and header matches the same sequence against a real account, attempt for attempt.
- Given `git grep` over `apps/api`, when the new code is inspected, then no SQL is assembled by
  concatenation or interpolation, and `INSERT`/`UPDATE`/`DELETE` against `login_attempts` appears in
  `api/throttle.py` alone.
- Given `apps/web` receives `account_locked`, when the login screen renders it, then the server's
  own sentence is shown, neither input is marked invalid, the typed password is preserved, and no
  countdown or numeric duration appears.

## Spec Change Log

## Review Triage Log

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 13: (high 1, medium 4, low 8)
- defer: 5: (high 0, medium 1, low 4)
- reject: 12: (high 0, medium 1, low 11)
- addressed_findings:
  - `[high]` `[patch]` The progressive delay slept while holding a pooled connection, so ten throttled sign-ins could hold all of `POOL_MAX_SIZE` for `MAX_DELAY` each and stall every other request in the product. `login` now takes the pool rather than a connection and uses two short-lived blocks with the sleep between them; `test_the_delay_holds_no_pooled_connection` inspects `pool.get_stats()` from inside the sleep.
  - `[medium]` `[patch]` `_RECORD_FAILURE` re-armed a live lock: a burst that read the state before the lock landed pushed its expiry out by a fresh `LOCKOUT_DURATION` each. A `locked_until > now()` branch now holds the deadline still; `test_a_live_lock_is_never_re_armed` pins it.
  - `[medium]` `[patch]` No test read the shipped value of any threshold, so a one-second lockout or a millisecond ladder kept the suite green. `test_the_thresholds_are_the_ones_the_requirement_names` restates them as literals, including `LOCKOUT_DURATION < ATTEMPT_WINDOW`.
  - `[medium]` `[patch]` The `Retry-After` assertion was `> 0`, which `retry_after()`'s own `max(1, …)` clamp guaranteed. It is now compared against the `locked_until` actually written.
  - `[medium]` `[patch]` The new `_SignInVanished` branch — the handler's only `except` — had no test, so breaking it would turn a rare race into the one 500 this endpoint must never give. Covered by forcing `_RECORD_LOGIN` to match no row.
  - `[low]` `[patch]` `_MIRROR_LOCK` was unguarded while `_sweep` was not, so a fault in the status mirror answered 500 instead of 429. Wrapped with the same swallow-and-warn.
  - `[low]` `[patch]` A lockout left no operational trace. `record_failure` now logs the transition at info, with the count and the duration and never the address.
  - `[low]` `[patch]` Nothing enforced that `users.locked_until` is inert; a future admin "unlock" clearing it would appear to work. A test now sets it to NULL under a live lock and asserts the refusal stands.
  - `[low]` `[patch]` The no-countdown web assertion banned every digit in the document; scoped to the alert's own text.
  - `[low]` `[patch]` Nothing pinned that a 429 leaves the unauthorized observer alone, so a change to the status check would silently drop the login screen into a session-ended notice. Covered in `api-client.test.ts`, with the 401 case beside it.
  - `[low]` `[patch]` The concurrency test checked only `is_alive()`, hiding worker exceptions behind a barrier timeout. Exceptions are now collected and re-raised.
  - `[low]` `[patch]` The real-clock test's absolute `fifth < 0.5s` ceiling would flake on a loaded runner; the bound is now relative to the fifth attempt.
  - `[low]` `[patch]` The migration comment and `infra/README.md` claimed the sweep stopped a backlog accumulating, which is only true of rows past `ATTEMPT_WINDOW`. Corrected to say what it actually bounds.

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 0, medium 1, low 3)
- defer: 3: (high 0, medium 1, low 2)
- reject: 22: (high 0, medium 6, low 16)
- addressed_findings:
  - `[medium]` `[patch]` The lock decision was read *before* the sleep and never re-asked, so the previous pass's fix — sleeping outside the connection blocks — opened a `MAX_DELAY`-wide window in which an attempt that started unlocked could be authenticated after another request had locked the address. With a correct credential it would then have been issued a session and `clear_failures` would have **deleted the row the lock lives in**, ending everyone's lockout. `login` now re-reads `attempt_state` after the sleep, on the delayed path only, and refuses before any credential work; `test_a_lock_that_lands_during_the_delay_still_beats_a_correct_password` drives the race deterministically through the stub clock, and `test_an_undelayed_attempt_reads_the_counter_once` pins that an ordinary sign-in still pays one lookup.
  - `[low]` `[patch]` `ATTEMPT_SWEEP_LIMIT` was unverified — the one behavioural sweep test seeds a single stale row and passes whether the `LIMIT` is 100, 1 or absent. `test_the_sweep_is_bounded_so_one_attempt_never_drains_a_whole_backlog` seeds `ATTEMPT_SWEEP_LIMIT + 5` and asserts the surplus survives, in the same shape as the session sweep's existing bound test.
  - `[low]` `[patch]` The corrupt-digest rejection was the one `_count_and_refuse` conversion nothing asserted: reverting it to `_rejected()` kept the whole suite green, leaving an account with a damaged `password_hash` as the single address in the product that never locks — and therefore the one that answers 401 at the tenth attempt where every other answers 429. Covered as a third case in `test_a_deactivated_account_and_an_expired_credential_are_counted_too`.
  - `[low]` `[patch]` `test_the_lock_is_logged_without_naming_the_address` counted INFO records by level alone, and `caplog`'s handler is attached at the root; it now filters on `rocell.api.throttle` as well, so the assertion does not break the day another module logs at INFO during a login.

### 2026-09-18 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 7: (high 0, medium 3, low 4)
- defer: 4: (high 0, medium 3, low 1)
- reject: 12: (high 0, medium 3, low 9)
- addressed_findings:
  - `[medium]` `[patch]` `clear_failures` was the last counter write in the product that could
    still fail a request: it runs inside the sign-in's own transaction, unguarded, so a statement
    timeout or a lost connection on that one `DELETE` answered 500 to a **correct** password and
    rolled the session back with it — while `record_failure`, the status mirror and both sweeps all
    swallow `psycopg.Error` by design. It is now on a nested `conn.transaction()` (a SAVEPOINT) with
    the same swallow-and-warn, so the delete unwinds alone and the sign-in commits; the count is
    left exactly where the unguarded version left it. `test_a_failing_counter_clear_leaves_the_sign_in_standing`
    pins it against a genuinely aborted transaction.
  - `[medium]` `[patch]` Nothing held `users.locked_until` inert on the *read* path. This story added
    `u.locked_until` to `_SELECT_SESSION`, one line from the `AND u.active` that does end a session,
    and no test in the suite made an authenticated request while a lock was live — so adding the
    matching `AND (u.locked_until IS NULL OR u.locked_until <= now())` stayed green while shipping a
    way to sign any member of staff out by typing ten wrong passwords at their address.
    `test_a_lock_does_not_end_a_session_that_is_already_open` closes it, and is also the only place
    the story's own acceptance clause — a live lock on the `User` contract, in the future — is
    observable at all, since a locked account cannot sign in to be read.
  - `[medium]` `[patch]` The unknown-address parity test claimed to prove the status mirror runs for
    an address with no account, and proved no such thing: its `count(*) FROM users WHERE locked_until
    IS NOT NULL` is satisfied identically by a build that skips `_mirror` whenever nothing matches —
    which would put the account-existence timing oracle back at the tenth attempt, the one this story
    is loudest about. `test_the_status_mirror_runs_for_an_address_that_is_not_an_account` asserts the
    call itself.
  - `[low]` `[patch]` Both operator documents were off by one: "from the 6th consecutive failure"
    where the code delays on the 6th *attempt*, the one that follows five recorded failures. As
    written, the enumerated ladder (1s, 2s, 3s, 4s, 4s) would have run past the tenth attempt instead
    of ending on it. Corrected in `README.md` and `infra/README.md`, and the README now also states
    the exposure the keying decision buys in the other direction — see the new `deferred` entry.
  - `[low]` `[patch]` `20260918T1000_add_login_throttling.down.sql` described the revert as restoring
    "a `users` table with ten columns"; `20260917T1200_create_users` defines eleven. Ten is the key
    count of the `User` contract, not the column count of the table.
  - `[low]` `[patch]` Two comments in `test_login_throttling.py` still described the pre-fix design,
    attributing `MAX_DELAY` to bounding a *held connection* — which `MAX_DELAY`'s own comment now
    denies in as many words, since `login` holds none across the sleep. Rewritten to name the
    threadpool worker, which is what the cap actually bounds.
  - `[low]` `[patch]` `test_the_throttling_migration_upgrades_a_database_that_already_holds_users`
    asserted `up(conn, plan) == [LOGIN_THROTTLING_VERSION]` over the *whole* plan — the exact
    fragility this same change removed from the activity migration's test two functions above. Story
    1.7's first migration would have failed it for a reason unrelated to the `ADD COLUMN` it exists
    to prove. Cut at this version, in the same shape.

## Design Notes

**Why the counter is keyed on the submitted address.** This endpoint's central invariant is that
four different failures are one response, down to the header and the elapsed time — `_rejected()`
exists as a single constructor for that reason, and `verify_dummy_password` exists to pay the
Argon2id cost an unknown address would otherwise skip. A delay ladder attached to `users.id` undoes
all of it: post six wrong passwords at a candidate address, and a delay means the account exists
while an instant answer means it does not. Keying on the address the caller submitted means a
garbage address accrues exactly the same count, the same delay and the same lock, so the ladder
carries no signal. The cost is rows for addresses that were never accounts, which is what the
bounded sweep and `ATTEMPT_WINDOW` are for.

**Why the lock is mirrored onto `users` rather than joined.** FR-4 requires the lock to be visible
in the admin-facing account status, and the surface that renders it is the shared `User` contract —
which is built in three places, two of them `UPDATE ... RETURNING` statements where a left join is
not expressible without restructuring the write. A mirrored, nullable column costs one extra
`UPDATE` on the tenth failure and nothing at all on the read path. The duplication is contained by
making the mirror one-directional and inert: `login_attempts` decides, `users.locked_until` only
reports, and the enforcement path never reads it. The mirror `UPDATE` is issued for every tenth
failure whether or not an account matches, so the locking response costs the same either way.

**Why the delay is a sleep, and why it is capped at four seconds.** The clause says a delay is
introduced "before it's processed" — a refusal with a `Retry-After` would be a different behaviour,
not a delayed one. A sleep in a sync handler is safe for the event loop (FastAPI runs it in the
threadpool) but it holds a pooled connection, and `POOL_MAX_SIZE` is 10 against a 40-worker
threadpool (DW-34). A ladder of 1s, 2s, 3s, 4s, 4s reaches the lock after five delayed attempts
having held a connection for at most four seconds at a time; an uncapped ladder would let an
attacker choose how long to hold one. This is a bound on the damage, not a fix for DW-34, and that
entry stays open.

**Why an expired lock resets the run rather than re-arming.** Without a reset, the eleventh failure
after a lapsed lock is still "the tenth or later" and re-locks immediately, so one mistyped password
an hour later leaves a legitimate user effectively locked out for good — with no unlock path in the
product at all, since FR-5 sends them to an Administrator and no story gives that Administrator a
button. Resetting restores the full ladder, which is also what makes the progressive delay
exercisable more than once.

```sql
-- apps/api/api/throttle.py — the shape of the increment, not the code.
INSERT INTO login_attempts (email_key, failure_count, last_failure_at)
VALUES (%s, 1, now())
ON CONFLICT (email_key) DO UPDATE
   SET failure_count = CASE WHEN <run ended> THEN 1
                            ELSE login_attempts.failure_count + 1 END,
       locked_until  = CASE WHEN <run ended> THEN NULL
                            WHEN login_attempts.failure_count + 1 >= %s THEN now() + %s
                            ELSE login_attempts.locked_until END,
       last_failure_at = now()
RETURNING failure_count, locked_until
-- <run ended> := (locked_until IS NOT NULL AND locked_until <= now())
--             OR last_failure_at <= now() - <window>
```

## Verification

**Commands:**
- `make lint` — expected: exit 0 (ruff check, ruff format --check, oxlint --deny-warnings,
  tsc --noEmit).
- `make test` — expected: exit 0; the `apps/api` database tests run against the ephemeral cluster or
  skip with the same "no PostgreSQL available" reason (DW-18/DW-39).
- `uv run pytest apps/api/tests/test_login_throttling.py apps/api/tests/test_login.py -q` —
  expected: exit 0, with every pre-existing rejection and decoy test passing unmodified.
- `uv run pytest infra/tests -q` — expected: exit 0, including the extended plan list and a full
  `up`/`down` round trip over the new pair.
- `uv run pytest apps/api/tests/test_source_guards.py shared/schema/tests -q` — expected: exit 0.
- `npm --prefix apps/web run test` — expected: exit 0, including the parity row and the lockout case.
- `git status --porcelain infra/migrations/20260917T*.sql` — expected: empty. The four applied
  migrations are untouched.
- `git grep -nE "INSERT INTO login_attempts|UPDATE login_attempts|DELETE FROM login_attempts" apps shared` —
  expected: matches in `apps/api/api/throttle.py` and test files only.
- Prove each new guard load-bearing by removing what it guards: delete the lock branch in `login`
  (the locked-account case fails), key `attempt_state` on `users.id` instead of the address (the
  unknown-address parity case fails), remove the `MAX_DELAY` cap (the ladder-cap case fails), and
  drop `locked_until` from `_SELECT_SESSION` (the `User`-contract case fails).

**Manual checks (if no CLI):**
- Invoke the `ui-ux-pro-max` skill and run its pre-delivery checklist against the login screen's
  lockout state before calling this story done (epic context: required for every UI story).
- `make migrate`, then `make dev`: sign in wrongly five times and watch the sixth take visibly
  longer; continue to the tenth and read the distinct message; confirm the correct password is still
  refused; `SELECT locked_until FROM users WHERE email = …` shows the future instant; wait out
  `LOCKOUT_DURATION` (or move it back by hand) and sign in successfully.


## Auto Run Result

Status: done

**Summary.** A follow-up review pass over a story already at `done`
(`followup_review_recommended: true`, `review_loop_iteration` 0). Four reviewer layers ran in
parallel over the whole diff since `8adb3041f57a5827e1cecee3f9f2425c21c1b3a9`. Triage found no
intent gap and no spec defect, so nothing was re-derived. Seven patches were applied and four
residual issues recorded.

Three of the patches matter. The first is behavioural: `clear_failures` runs inside the sign-in's
own transaction and was the one counter write left in the product that could still decide a
response — a fault on that `DELETE` answered 500 to a *correct* password and took the session with
it, while every other counter write in the module fails safe by design. It is now on a savepoint,
so the delete unwinds alone.

The other two are verification gaps on the story's two loudest claims. `users.locked_until` reaches
every authenticated request through `_SELECT_SESSION` under an invariant — a lockout blocks
attempts, it does not sign anybody out — that no test held: adding the obvious-looking
`AND (u.locked_until IS NULL OR u.locked_until <= now())` beside the existing `AND u.active` left
the whole suite green while shipping a way to sign any member of staff out by typing ten wrong
passwords at their address. And the unknown-address parity test claimed to prove the status mirror
runs for an address with no account, when its assertion is satisfied identically by a build that
skips the mirror whenever nothing matches — which puts the account-existence timing oracle back at
the tenth attempt. Both are now asserted directly.

**Files changed in this pass:**
- `apps/api/api/auth.py` — `clear_failures` moved onto a nested `conn.transaction()` (SAVEPOINT)
  with swallow-and-warn, matching the module's three other counter writes.
- `apps/api/tests/test_login_throttling.py` — three new tests
  (`test_a_failing_counter_clear_leaves_the_sign_in_standing`,
  `test_a_lock_does_not_end_a_session_that_is_already_open`,
  `test_the_status_mirror_runs_for_an_address_that_is_not_an_account`) and two comments corrected
  where they still described the pre-fix connection-holding design.
- `infra/tests/test_migrate.py` — the throttling upgrade test cut at its own version instead of
  running to the end of the plan, so Story 1.7's migration cannot fail it for an unrelated reason.
- `infra/migrations/20260918T1000_add_login_throttling.down.sql` — the revert restores eleven
  `users` columns, not ten (comment only; the four applied migrations are untouched).
- `README.md`, `infra/README.md` — the delay starts on the 6th *attempt*, not the 6th failure; and
  the README now states that a lockout is a free, repeatable way to hold a named colleague out.
- `_bmad-output/implementation-artifacts/spec-1-6-login-rate-limiting.md` — this pass's triage
  entry, four appended `deferred` items, and this section.

**Review findings breakdown:** 7 patched (0 high, 3 medium, 4 low), 4 deferred (0 high, 3 medium,
1 low), 12 rejected (0 high, 3 medium, 9 low).

The three medium rejections were checked against the source rather than waved off. `attempt_state`
is unguarded on purpose: a database that cannot answer the counter read cannot authenticate anyone
either, so failing open would silently disable FR-4 and buy nothing. The lockout `logger.info` does
not breach the "no private log path" clause — that clause bans an audit entry per failed login, and
this is one address-free record of a transition, in the shape the module's existing warnings already
use. The `Retry-After` byte-comparison in the parity test is not a flake risk in the way it was
reported: each sequence computes the header against its *own* `locked_until` within one request, and
excluding the header would weaken precisely the oracle that test exists to catch. Two further
rejections were about this pass's scope: DW-62's overlap with DW-54, and the spec/board metadata,
are both the orchestrator's ledger and board to reconcile, not this run's.

**Follow-up review recommendation:** `true`. Patched this pass: 0 high, 3 medium, 4 low →
`3 × 3 + 1 × 4 = 13`, which is ≥ 5.

**Verification performed:**
- `make lint` — exit 0 (ruff check, ruff format --check over 46 files, oxlint --deny-warnings,
  tsc --noEmit).
- `uv run pytest` (full Python workspace) — **485 passed**, 0 failed, 42s (was 482; +3 new tests).
- `make test` — exit 0. `apps/web` 489 passed across two full runs (2.08s, 1.83s). DW-54's
  `session-expiry.test.tsx` flake did **not** reproduce this pass, unlike the last one.
- Each new guard proven load-bearing by removing what it guards, not merely by passing: reverting
  the savepoint fails `test_a_failing_counter_clear_leaves_the_sign_in_standing` alone; adding
  `AND (u.locked_until IS NULL OR u.locked_until <= now())` to `_SELECT_SESSION` fails
  `test_a_lock_does_not_end_a_session_that_is_already_open` alone — every session test and the
  parity test stayed green, which is the gap; guarding `_mirror` with a `SELECT 1 FROM users` fails
  `test_the_status_mirror_runs_for_an_address_that_is_not_an_account` alone, and notably *not* the
  unknown-address parity test. Each was restored and the suite re-run green.
- `git status --porcelain infra/migrations/20260917T*.sql` — empty; the four applied migrations are
  untouched.
- `git grep -lE "INSERT INTO login_attempts|UPDATE login_attempts|DELETE FROM login_attempts"` over
  `apps shared` — `apps/api/api/throttle.py` and `apps/api/tests/test_login_throttling.py` only.

**Residual risks:**
- **A lockout is an unmitigated denial of service against a named member of staff** (deferred,
  medium). Ten cheap guesses hold a colleague out for fifteen minutes and cost the attacker nothing,
  with no unlock to reach for and no audit entry until Story 1.12. This is the price of the
  address-keyed counter — the mirror image of DW-55 — and it is now stated in `README.md` rather
  than left implicit. Bounding it is a product decision FR-4 does not make.
- **FR-4's admin visibility has no renderer and FR-5's recovery has no owner** (deferred, medium).
  The column, the contract and the mirror are complete; `epics.md` 1.9 and 1.10 name neither a lock
  nor an unlock in their acceptance clauses. Nothing in this story can widen them.
- **The delay ladder is still defeatable by concurrency** (DW-60, unchanged). The lockout is not.
- **Every sign-in now costs two pooled-connection checkouts** (deferred, medium), including the
  undelayed majority. Merging them when no sleep will happen is easy; doing it on an unmeasured
  hunch is what CLAUDE.md says not to do.
- The lock is still recoverable only by waiting out `LOCKOUT_DURATION`, and `make reseed-admin` does
  not clear it — DW-57, unchanged.
