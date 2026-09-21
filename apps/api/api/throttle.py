"""FR-4's failed-login counters: the one module that writes `login_attempts`.

AD-8 fixes two things about a rate-limit counter and this module is both of
them:

* it is a **row in Postgres**, not in-process memory — it survives a restart
  and a second `apps/api` instance; and
* it is mutated by **one atomic increment-and-check**, never a read followed by
  a write of a value derived from that read. `_RECORD_FAILURE` below is a
  single `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` that resets-or-
  increments, decides the lockout and hands back the new state. Two attempts
  arriving together are therefore serialised by the row lock, and neither can
  read a stale count and blow past the threshold.

`tests/test_source_guards.py` holds the second half of that to one file, the
way it already does for `sessions`: an `INSERT`, `UPDATE` or `DELETE` against
`login_attempts` anywhere but here fails the suite. *Reads* are deliberately
not guarded — Story 1.9 has to join this table to render an account's status,
and the property being protected is that the mutation is one statement in one
place, not that nobody may look.

**The counter is keyed on the submitted address, never on `users.id`.**
`api/auth.py` answers an unknown address, a wrong password, a deactivated
account and an expired temporary credential with one identical rejection —
same status, same body, same headers, same Argon2id work. A delay ladder
attached to an account would undo all of it: six wrong passwords at a candidate
address, and a delay means the account exists while an instant answer means it
does not. Keyed on the address the caller submitted, a garbage address accrues
exactly the same count, the same delay and the same lock, so the ladder carries
no signal. `record_failure`'s mirror `UPDATE` is issued whether or not an
account matches for the same reason.

**`users.locked_until` is status only and is never read to decide anything.**
FR-4 requires the lock to be visible to an Administrator, and the surface that
carries it is the shared `User` contract. The mirror is one-directional and
inert: `login_attempts` decides, `users.locked_until` reports, and the
enforcement path reads this table and nothing else.

**Not here.** Scan rate limiting (FR-23) and the anomaly baseline (FR-22) are
the other two AD-8 counters and are Epic 2's; they are not this module's
statements with a different table name, and no attempt is made to generalise
one out of it before there is a second caller. `POST /auth/password` is not
throttled either (DW-40) — epics.md scopes that story to login.

**There is still no unlock surface, and no story in Epic 1 owns one.** This
module used to say Story 1.10 would give an Administrator something to press.
1.10 has shipped, and its acceptance clauses are name, email and role: the lock
still expires on its own after `LOCKOUT_DURATION`, and FR-5's "go to an
Administrator" still ends in waiting it out. DW-64 stays open with no predicted
owner left. What 1.10 did add here is `carry_failures` — a rename moves the run
onto the new address rather than stranding it, precisely so that an edit is not
the unlock this product has decided not to have.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

# Imported for real rather than under `TYPE_CHECKING`: the sweep below catches
# `psycopg.Error`, which is a runtime reference, not an annotation.
import psycopg

#: Named as `api.auth`'s and `api.sessions`' are — an explicit `rocell.` prefix
#: rather than `__name__` — so the three auth-path loggers sit under one parent
#: and a deployment can filter or raise the level of all of them with one rule.
logger = logging.getLogger("rocell.api.throttle")

#: How many failures a run may hold before the *next* attempt is delayed.
#: epics.md 1.6 and FR-4: "Given 5 consecutive failed attempts ... when the 6th
#: attempt is made, then a measurable delay is introduced before it's
#: processed." Five is therefore the count at which the ladder starts, not the
#: attempt number — the 6th attempt is the one that finds five failures already
#: recorded.
FAILURES_BEFORE_DELAY = 5

#: The failure that locks the address. FR-4: "the 10th cumulative failed
#: attempt locks the account". The tenth failure writes the lock in the same
#: statement that records it, so the response to that attempt is already the
#: locked one.
FAILURES_BEFORE_LOCKOUT = 10

#: One rung of the ladder. The delay is `DELAY_STEP` on the 6th attempt, twice
#: that on the 7th, and so on — a second is long enough to be measurable by the
#: person triggering it and by a test, and short enough that a member of staff
#: who mistyped their password twice more does not think the app has hung.
DELAY_STEP = timedelta(seconds=1)

#: The ceiling on that ladder: 1s, 2s, 3s, 4s, 4s, and then the lock.
#:
#: **The cap is not what keeps the delay off the connection pool.** That is
#: `api.auth.login`'s doing: it gives its connection back before it sleeps and
#: takes a fresh one afterwards, so a delayed attempt holds no connection at
#: all. Do not read this constant as the bound on a held connection, and do not
#: reintroduce a sleep inside a connection block on the strength of it being
#: "only four seconds" — ten of those would empty a pool of ten
#: (`api.db.POOL_MAX_SIZE`) and take every endpoint in the product down with
#: them.
#:
#: What the cap still buys is a bound on the one resource a waiting attempt
#: does occupy: a Starlette threadpool worker (FastAPI runs this sync endpoint
#: in it, so the event loop is untouched). Uncapped, an attacker chooses how
#: long each attempt pins a worker and how many it pins at once; capped, no
#: single attempt holds one for more than four seconds. Worth having, and much
#: less load-bearing than it was.
#:
#: DW-34 — `POOL_MAX_SIZE` 10 behind a 40-worker threadpool — is untouched by
#: any of this and stays open on its own terms.
MAX_DELAY = timedelta(seconds=4)

#: How long the lock holds. Long enough that an online guessing run is not
#: worth continuing — ten guesses per quarter hour — and short enough that a
#: member of staff who locked themselves out before a shift is not waiting on
#: an Administrator who, per FR-5, has no unlock button to press: no story in
#: this epic builds one, so the expiry *is* the recovery path.
LOCKOUT_DURATION = timedelta(minutes=15)

#: How long a run of failures stays a run. A failure this much older than the
#: next one is not part of the same attack, and counting it would let three
#: mistyped passwords a month apart join up into a lockout. An hour is well
#: above `LOCKOUT_DURATION`, so a lock can never lapse into a window that has
#: also gone stale in some order that matters.
ATTEMPT_WINDOW = timedelta(hours=1)

#: How many stale rows one failed attempt will clear. A failed attempt adds at
#: most one row, so any bound above 1 drains a backlog rather than merely
#: keeping pace; a bound at all is what stops a single unlucky attempt paying
#: to delete everything a guessing run against thousands of invented addresses
#: left behind. The same reasoning, and the same number, as
#: `api.sessions.EXPIRED_SWEEP_LIMIT`.
ATTEMPT_SWEEP_LIMIT = 100

#: Whether the run this row records has ended, decided by the **database**
#: clock rather than by the application's. Two ways for it to have ended, and
#: both mean the next failure starts from 1:
#:
#:   * a lock that has lapsed — `LOCKOUT_DURATION` has passed, and re-arming
#:     instead of resetting would make one mistyped password an hour later
#:     re-lock the account immediately, permanently, with no unlock surface
#:     anywhere in the product to recover it; or
#:   * a last failure older than `ATTEMPT_WINDOW`.
#:
#: Interpolated into the two statements below as a shared fragment because it
#: has to mean exactly the same thing in the read and in the write — the read
#: decides whether to delay, the write decides whether to reset, and the two
#: disagreeing is a ladder that skips rungs. It is a **constant**, not a value:
#: the `%s` placeholder in it is a parameter, and nothing a caller supplies is
#: ever formatted into SQL here.
_RUN_ENDED = """
    (login_attempts.locked_until IS NOT NULL AND login_attempts.locked_until <= now())
     OR login_attempts.last_failure_at <= now() - %s
"""

#: `_RUN_ENDED` asked of the row being merged *in* rather than the one already
#: there. Same three clauses, same parameter, different alias — `_CARRY_FAILURES`
#: is the only statement that has to judge two runs at once, and it has to judge
#: them by one rule.
_INCOMING_RUN_ENDED = """
    (EXCLUDED.locked_until IS NOT NULL AND EXCLUDED.locked_until <= now())
     OR EXCLUDED.last_failure_at <= now() - %s
"""

#: The pre-attempt read. Returns the state as the *run* sees it, not as the row
#: holds it: a lapsed lock and a stale run both come back zeroed, so the
#: handler never has to re-decide in Python what the write below decides in
#: SQL.
_SELECT_ATTEMPTS = f"""
SELECT CASE WHEN {_RUN_ENDED} THEN 0 ELSE login_attempts.failure_count END
           AS failure_count,
       CASE WHEN {_RUN_ENDED} THEN NULL ELSE login_attempts.locked_until END
           AS locked_until
  FROM login_attempts
 WHERE email_key = %s
"""

#: AD-8's single atomic increment-and-check, and the only statement in the
#: product that writes `login_attempts`.
#:
#: One statement decides three things at once — whether this failure starts a
#: new run, what the count becomes, and whether that count locks the address —
#: from the row as it is locked for update, not from a value read a moment ago
#: by some other request. `RETURNING` hands back the state that was actually
#: written, so the caller never re-reads and never guesses.
#:
#: `locked_until` is written in the same `SET` as the count it is derived from.
#: Computing the count here and the lock in a follow-up `UPDATE` would be
#: exactly the read-then-write AD-8 forbids, one statement later.
#:
#: **A live lock is never re-armed.** The `locked_until > now()` branch sits
#: ahead of the threshold branch and carries the existing expiry through
#: untouched. `api.auth` refuses a locked address before it reaches this
#: statement, but only one attempt at a time: a burst that all read
#: `attempt_state` before the lock lands arrives here afterwards, and without
#: this branch each of them would push the expiry out by another
#: `LOCKOUT_DURATION`. That is a lock nobody can wait out — an attacker holds a
#: legitimate user out indefinitely by continuing to guess, for free, since the
#: attempts cost no credential work. The count is still allowed to climb past
#: the threshold; only the deadline is fixed.
#:
#: The ordering of the three `WHEN`s is therefore load-bearing:
#: run-ended → live lock → threshold. Swap the middle two and a locked address
#: re-arms on every attempt again.
_RECORD_FAILURE = f"""
INSERT INTO login_attempts (email_key, failure_count, locked_until, last_failure_at)
VALUES (%s, 1, NULL, now())
ON CONFLICT (email_key) DO UPDATE
   SET failure_count = CASE WHEN {_RUN_ENDED} THEN 1
                            ELSE login_attempts.failure_count + 1 END,
       locked_until = CASE
           WHEN {_RUN_ENDED} THEN NULL
           WHEN login_attempts.locked_until > now() THEN login_attempts.locked_until
           WHEN login_attempts.failure_count + 1 >= %s THEN now() + %s
           ELSE login_attempts.locked_until END,
       last_failure_at = now()
RETURNING failure_count, locked_until
"""

#: The mirror, for FR-4's "visible to Administrators on that user's status".
#:
#: `WHERE lower(email)`, not `WHERE email`, for the reason `_SELECT_CREDENTIAL`
#: gives: `users` carries exactly one index on the address —
#: `users_email_lower_key ON users (lower(email))` — and an expression index
#: only serves the expression it was built on.
#:
#: Issued whether or not a row matches. For an address with no account it
#: updates zero rows, which is what keeps the locking response identical on
#: both paths; checking first would cost a `SELECT` whose only effect is to
#: tell a caller, by timing, which addresses exist.
#:
#: `updated_at` is set by hand — `users` carries no BEFORE UPDATE trigger
#: (DW-17), and the column's DEFAULT applies to inserts only.
_MIRROR_LOCK = """
UPDATE users
   SET locked_until = %s,
       updated_at = now()
 WHERE lower(email) = %s
"""

#: The same mirror, addressed by `users.id` rather than by the address.
#:
#: `carry_failures` needs this and `_MIRROR_LOCK` cannot serve it. That statement
#: matches `lower(email)` — Postgres's fold of the column — against a key that is
#: the *Python* fold of a submitted address, which is exactly the disagreement
#: `_INSERT_USER` writes `lower(%s)` to avoid, and it would silently update zero
#: rows where the two folds differ. During a rename the account is identified by
#: the id the request named, which is not an encoding of anything.
#:
#: `updated_at` is set by hand for `_MIRROR_LOCK`'s reason (DW-17, no BEFORE
#: UPDATE trigger). It lands on the same instant the rename did: `now()` is the
#: transaction timestamp, and this statement only ever runs inside the
#: transaction that just wrote the row.
_MIRROR_LOCK_BY_ID = """
UPDATE users
   SET locked_until = %s,
       updated_at = now()
 WHERE id = %s
"""

#: The live lock at one address key, or no row. A **read**, and the only way to
#: learn what a carry actually left behind.
#:
#: `_CARRY_FAILURES` cannot answer it with a `RETURNING`: its `INSERT ... SELECT`
#: writes nothing at all when the old key has no run, and that is precisely the
#: case where the destination may still be carrying a lock of its own. Asked
#: afterwards, against the destination, this is true on every branch.
#:
#: `locked_until > now()` rather than a null check, and decided by the **database**
#: clock as every other decision in this module is: a past value is a lapsed lock,
#: which `attempt_state` already reads as a fresh run and which must not be
#: mirrored onto an account as though it were live.
_SELECT_LIVE_LOCK = """
SELECT locked_until
  FROM login_attempts
 WHERE email_key = %s
   AND locked_until > now()
"""

_CLEAR_ATTEMPTS = "DELETE FROM login_attempts WHERE email_key = %s"

#: Move a run of failures from one address key to another. Story 1.10, DW-59.
#:
#: **The direction is the account's, not the string's.** The counter is keyed on
#: the submitted address (see the module docstring), so an Administrator editing
#: someone's address moves the login that the run belongs to and leaves the run
#: behind. Three things were then wrong at once: the old string kept a live lock
#: nobody could reach, the new address started from zero, and `users.locked_until`
#: reported a lock corresponding to nothing. Carrying the row fixes all three.
#:
#: **Carrying rather than clearing is the security half of it.** Clearing the old
#: key would also fix the first and the third — by making a rename an unlock, a
#: lock-evasion path an Administrator can walk, and an unlock this epic
#: deliberately does not have (FR-5, DW-64). A rename must not be the unlock.
#:
#: **`GREATEST` per column, because the new key may carry its own run.** An
#: address that was guessed at before it became anybody's login already has a
#: row here, and merging has to keep the stricter of the two states rather than
#: whichever arrived second. Postgres's `GREATEST` **ignores NULLs**, which is
#: exactly the wanted behaviour for `locked_until`: "no lock" never wins over a
#: live one, in either direction.
#:
#: **Each side is normalised to the run it actually has before they are merged.**
#: `GREATEST` over the raw columns takes the stricter *value* per column, which
#: is not the same thing as the stricter *state*: a run the whole module already
#: considers over — a lapsed lock, or a last failure older than `ATTEMPT_WINDOW`
#: (`_RUN_ENDED`) — still carries the count and the expiry it ended with, and
#: pairing that count with the other side's fresher `last_failure_at` fabricates
#: a live run neither address had. Four stale failures merged onto one fresh one
#: would leave the account one mistyped password from a lockout it never earned,
#: and this epic has no unlock. So an ended run contributes `0` and no lock,
#: exactly as `_SELECT_ATTEMPTS` reads it and `_RECORD_FAILURE` rewrites it, and
#: what survives the merge is the stricter of the two *live* runs.
#:
#: **`last_failure_at` is normalised too, and it is the column that decides how
#: long the survivor lives.** It is the clock `_RUN_ENDED` reads, so letting an
#: ended run's fresher timestamp win is the same fabrication by another route:
#: a lock that lapsed a minute ago carries a `last_failure_at` far newer than a
#: live run of four failures nearly at the end of its window, and a raw
#: `GREATEST` would hand that live run a fresh window it never earned — another
#: `ATTEMPT_WINDOW` in which a fifth mistyped password locks the account. Each
#: side is therefore zeroed to NULL when its run has ended, and `GREATEST`
#: ignores NULLs. The `COALESCE` behind it is for the one case where *both* runs
#: have ended: the column is `NOT NULL`, so the row keeps the later of the two
#: raw timestamps — harmless, because the count beside it is `0` and the state
#: every reader sees is "no run".
#:
#: `INSERT ... SELECT` rather than a plain `VALUES`, so an old key with no row at
#: all inserts nothing and the statement is a no-op — the common case, since most
#: accounts have never failed a sign-in. `%s::text` because an untyped parameter
#: in a `SELECT` list has no column to take its type from. The insert branch
#: copies the carried row as it stands: nothing is fabricated there, and a row
#: that reads as ended at the old key goes on reading as ended at the new one.
_CARRY_FAILURES = f"""
INSERT INTO login_attempts (email_key, failure_count, locked_until, last_failure_at)
SELECT %s::text, carried.failure_count, carried.locked_until, carried.last_failure_at
  FROM login_attempts AS carried
 WHERE carried.email_key = %s
ON CONFLICT (email_key) DO UPDATE
   SET failure_count = GREATEST(
           CASE WHEN {_RUN_ENDED} THEN 0 ELSE login_attempts.failure_count END,
           CASE WHEN {_INCOMING_RUN_ENDED} THEN 0 ELSE EXCLUDED.failure_count END),
       locked_until = GREATEST(
           CASE WHEN login_attempts.locked_until > now()
                THEN login_attempts.locked_until END,
           CASE WHEN EXCLUDED.locked_until > now() THEN EXCLUDED.locked_until END),
       last_failure_at = COALESCE(
           GREATEST(
               CASE WHEN {_RUN_ENDED} THEN NULL ELSE login_attempts.last_failure_at END,
               CASE WHEN {_INCOMING_RUN_ENDED} THEN NULL ELSE EXCLUDED.last_failure_at END),
           GREATEST(login_attempts.last_failure_at, EXCLUDED.last_failure_at))
"""

#: Bounded and lock-skipping, in the shape `api.sessions._DELETE_EXPIRED`
#: already uses: `FOR UPDATE SKIP LOCKED` so two attempts arriving together
#: take disjoint rows instead of one waiting on the other's locks, and the
#: `LIMIT` caps what any one of them pays for. The `email_key IN (...)` form is
#: what carries a `LIMIT` into a `DELETE`, which SQL has no direct syntax for.
#:
#: A live lock is never swept, even though `ATTEMPT_WINDOW` is four times
#: `LOCKOUT_DURATION` and the two conditions cannot both be true today.
#: Deleting a locked row would release the lock, and this is a table tidy-up:
#: it must not be the thing that decides an address is free to try again.
_SWEEP_ATTEMPTS = """
DELETE FROM login_attempts
 WHERE email_key IN (
     SELECT email_key
       FROM login_attempts
      WHERE last_failure_at <= now() - %s
        AND (locked_until IS NULL OR locked_until <= now())
      FOR UPDATE SKIP LOCKED
      LIMIT %s
 )
"""


@dataclass(frozen=True, slots=True)
class AttemptState:
    """What the counter says about one address, right now.

    Both constructors are SQL — `attempt_state` and `record_failure` — and both
    normalise a lapsed lock and a stale run to a zeroed state before it reaches
    Python. That is what makes `locked` a plain null check rather than a second
    comparison against a second clock: a `locked_until` that survives to here is
    one the *database* considers live.
    """

    failure_count: int
    locked_until: datetime | None

    @property
    def locked(self) -> bool:
        """Whether this address is refused outright. See the class docstring."""
        return self.locked_until is not None

    def delay(self) -> timedelta:
        """The sleep the *next* attempt owes, before any credential work.

        `failure_count` is what is already recorded, so the attempt about to be
        made is number `failure_count + 1`: five recorded failures make this the
        sixth attempt and the first delayed one. The ladder is one `DELAY_STEP`
        per rung and is capped at `MAX_DELAY` — see that constant for why the
        cap is a security property rather than a nicety.

        Reads both constants through the module rather than capturing them, so
        a test can shorten the ladder without the suite sleeping in real
        seconds.
        """
        rungs = self.failure_count - FAILURES_BEFORE_DELAY + 1
        if rungs <= 0:
            return timedelta(0)
        return min(DELAY_STEP * rungs, MAX_DELAY)

    def retry_after(self) -> int:
        """Whole seconds until the lock lapses, for the `Retry-After` header.

        Rounded **up**, and never below 1: a client that retried at the instant
        this returns would be refused again, and RFC 9110's `delay-seconds` is a
        non-negative integer, so `0` would read as "retry now".

        Machine-facing only. `apps/web` must not render it — EXPERIENCE.md is
        explicit that the lockout message carries no countdown.
        """
        if self.locked_until is None:  # pragma: no cover - guarded by `locked`
            return 0
        remaining = (self.locked_until - datetime.now(UTC)).total_seconds()
        return max(1, math.ceil(remaining))


def attempt_state(conn: psycopg.Connection, email_key: str) -> AttemptState:
    """What the counter says about `email_key` before this attempt is processed.

    A missing row is a zeroed state, and so is a row whose lock has lapsed or
    whose last failure is older than `ATTEMPT_WINDOW` — the decision is made in
    SQL, against the database clock the write below is also measured against.

    Read, not written: this runs on every sign-in attempt including the ones
    that succeed, and an attempt that is neither delayed nor locked must cost
    one indexed lookup and nothing else.
    """
    row = conn.execute(
        _SELECT_ATTEMPTS,
        (ATTEMPT_WINDOW, ATTEMPT_WINDOW, email_key),
    ).fetchone()
    if row is None:
        return AttemptState(failure_count=0, locked_until=None)
    return AttemptState(failure_count=row["failure_count"], locked_until=row["locked_until"])


def record_failure(conn: psycopg.Connection, email_key: str) -> AttemptState:
    """Count one failed sign-in and return the state that decides the response.

    Three writes, in this order and for these reasons:

    1. The counter itself, in AD-8's one atomic statement. Everything the
       caller needs comes back from its `RETURNING`.
    2. The mirror onto `users.locked_until`, **only** when this failure locked
       the address, and then unconditionally — it matches zero rows for an
       address with no account, which is what keeps the two paths identical. It
       is never cleared: a value in the past is the record that this account was
       locked recently, which is exactly what an Administrator's view of the
       status wants to say.
    3. A bounded sweep of rows nothing can reach any more, whose failure is
       swallowed — see `_sweep`.

    The counter write is **not** wrapped here. Its failure is the caller's to
    decide about, and `api.auth` decides that the sign-in is still refused and
    the attempt simply goes uncounted: failing in the safe direction means a
    rejected credential stays rejected, not that a database fault becomes a 500
    on the one endpoint anybody can reach without one.
    """
    row = conn.execute(
        _RECORD_FAILURE,
        (
            email_key,
            ATTEMPT_WINDOW,
            ATTEMPT_WINDOW,
            FAILURES_BEFORE_LOCKOUT,
            LOCKOUT_DURATION,
        ),
    ).fetchone()
    if row is None:  # pragma: no cover - both upsert branches produce a row
        # Unreachable: `ON CONFLICT DO UPDATE ... RETURNING` yields a row on the
        # insert branch and on the update branch alike. Answered as "counted
        # nothing, not locked" rather than by raising, because every caller of
        # this function is already on its way to refusing a sign-in and must
        # not have that refusal turned into a 500.
        return AttemptState(failure_count=0, locked_until=None)
    state = AttemptState(failure_count=row["failure_count"], locked_until=row["locked_until"])

    # The failure that *wrote* the lock, which is exactly the one that reaches
    # the threshold: the statement above locks at `>= FAILURES_BEFORE_LOCKOUT`
    # and carries a live lock through untouched, so a count of exactly
    # `FAILURES_BEFORE_LOCKOUT` and a freshly written `locked_until` are the
    # same event. A later attempt on an already-locked row re-mirrors nothing
    # and logs nothing — it changed nothing.
    if state.failure_count == FAILURES_BEFORE_LOCKOUT and state.locked_until is not None:
        # The brief's security addendum wants a lockout logged and visible to
        # administrators. The *visible* half is the mirror below; the durable
        # half is the audit entry `api.auth` writes for the same attempt,
        # carrying `details.locked_until` on the `login_failed` row that
        # crossed the threshold (Story 1.12). This line is the operational
        # trace, for whoever is watching the process rather than the table.
        #
        # **The address is still not logged here**, and neither is anything
        # derived from it. Most of what this counter holds was never an
        # account, and an application log that accumulated every address
        # someone guessed would be a list of candidate usernames in a file
        # with none of the audit log's protections. The address *is* recorded
        # — in the audit log, which has AD-4's protections and exists to hold
        # exactly this. The count and the duration are what an operator needs
        # here to see a run happening.
        logger.info(
            "a sign-in lockout was written after %d failures, for %d seconds",
            state.failure_count,
            state.retry_after(),
        )
        _mirror(conn, email_key, state.locked_until)

    _sweep(conn)
    return state


def clear_failures(conn: psycopg.Connection, email_key: str) -> None:
    """Forget this address's run of failures. Called on a successful sign-in.

    Deleting the row rather than zeroing it: a count of zero and no row at all
    are the same state to `attempt_state`, and the row is what the sweep would
    otherwise have to come back for.

    `users.locked_until` is deliberately left alone. It is status and history,
    not state — see the module docstring — and a successful sign-in after a
    lapsed lock should still show an Administrator that the account was locked
    an hour ago.
    """
    conn.execute(_CLEAR_ATTEMPTS, (email_key,))


def carry_failures(
    conn: psycopg.Connection, old_key: str, new_key: str, user_id: UUID
) -> datetime | None:
    """Move this address's run of failures onto its new address. FR-12, DW-59.

    Called by `api.users.edit_user` when an Administrator changes the address on
    an account, and by nothing else. The counter is keyed on the submitted
    address (module docstring), so without this a rename strands the run: the old
    string keeps a lock nobody can reach and the new address starts from zero.

    Both keys are the **Python** fold of an address — `email.strip().lower()`,
    what `api.auth.login` keys on — never the value in `users.email`, which is
    Postgres's fold of the same string. See `api.users.edit_user`, which is where
    the old key is derived and where the difference bites.

    **This is deliberately not `clear_failures`.** Clearing the old key would
    tidy the same mess by making the rename an *unlock* — a lock-evasion path an
    Administrator can walk, and an unlock this epic does not have: FR-5 sends a
    locked-out user to an Administrator, and no story in Epic 1 gives that
    Administrator a control (DW-64). Carrying the run keeps the lockout a
    property of the account rather than of a string somebody can change.

    **`users.locked_until` is re-mirrored, and it has to be.** The tempting claim
    — that the account's mirror already holds whatever lock it carries, so a
    rename moves both together — is false on the very path `_CARRY_FAILURES` was
    written for. When the *destination* key carries the live lock (an address
    guessed at while it belonged to nobody, so `_MIRROR_LOCK` matched zero rows
    at the time), the carry either writes nothing or `GREATEST` keeps the
    destination's longer expiry, and the account's mirror was never written for
    either. FR-4's one status surface would then show no lock while
    `POST /auth/login` answered `429 account_locked` — the enforcement and the
    report disagreeing, which is the one thing the mirror exists to prevent.
    So the resulting live lock is read back and written onto the account, by id.

    The mirror is still one-directional and still never *cleared*: a destination
    with no live lock leaves the column exactly as it was, because it is history
    as much as status (`clear_failures`).

    **It opens no transaction of its own.** The carry, the mirror and the
    `UPDATE` that renames the account have to commit together or not at all — a
    carry that survived a rolled-back rename would move a lock onto an address
    nobody uses, and a rename that survived a failed carry is the stranded run
    this exists to prevent. The caller's `with conn.transaction():` is that unit
    of work, which is also why nothing here is swallowed the way `_mirror` is:
    inside somebody else's transaction a swallowed failure is not a smaller
    failure, it is the same one reported later and less clearly.

    Returns the live lock now in force at `new_key`, or `None` when there is
    none. A no-op returning `None` when the address did not really change, and
    harmless when the old key has no row: `_CARRY_FAILURES`' `INSERT ... SELECT`
    inserts nothing, and the delete removes nothing.
    """
    if old_key == new_key:
        return None

    conn.execute(
        _CARRY_FAILURES,
        (new_key, old_key, ATTEMPT_WINDOW, ATTEMPT_WINDOW, ATTEMPT_WINDOW, ATTEMPT_WINDOW),
    )
    conn.execute(_CLEAR_ATTEMPTS, (old_key,))

    row = conn.execute(_SELECT_LIVE_LOCK, (new_key,)).fetchone()
    locked_until: datetime | None = None if row is None else row["locked_until"]
    if locked_until is not None:
        conn.execute(_MIRROR_LOCK_BY_ID, (locked_until, user_id))

    return locked_until


def _mirror(conn: psycopg.Connection, email_key: str, locked_until: datetime) -> None:
    """Copy the lock onto `users.locked_until`. Never fails the refusal.

    Swallowed for the same reason `_sweep` is, and with more at stake: the
    counter row has already committed on an autocommit connection, so the lock
    is durable whatever happens here. Letting a failure out would answer `500`
    to the *tenth* attempt while every other attempt answered `401` or `429` —
    a response shape reachable at one specific count, which is the kind of
    difference this endpoint exists to not have.

    What is lost when it fails is the Administrator's view of the status, not
    the enforcement, and the `logger.warning` is how that is noticed. Nothing
    retries it: a later attempt on the same address is already locked and
    writes no new lock, so the mirror stays stale until the run ends.
    """
    try:
        conn.execute(_MIRROR_LOCK, (locked_until, email_key))
    except psycopg.Error:
        logger.warning(
            "the account-status mirror could not be written; the lock itself stands",
            exc_info=True,
        )


def _sweep(conn: psycopg.Connection, limit: int = ATTEMPT_SWEEP_LIMIT) -> None:
    """Delete rows no run can be resumed from, up to `limit`. Never raises.

    `attempt_state` already reads a stale row as a fresh run, so this changes no
    behaviour — which is exactly why nothing else would notice it becoming a
    no-op while the table grew one row per invented address forever. A guessing
    run against a dictionary of addresses is the case it exists for.

    Swallowed on failure, as `login`'s session sweep and `_touch_session` both
    are: the caller is on its way to refusing a sign-in, and a deadlock or a
    statement timeout in a table tidy-up must not turn that rejection into a
    500 — which, on this endpoint, would be a 500 for one address and a 401 for
    every other. Logged, because a sweep that keeps failing is a table that
    keeps growing.
    """
    try:
        conn.execute(_SWEEP_ATTEMPTS, (ATTEMPT_WINDOW, limit))
    except psycopg.Error:
        logger.warning(
            "stale login-attempt sweep failed; the rejection itself stands", exc_info=True
        )
