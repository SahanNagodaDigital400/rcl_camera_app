"""`POST /auth/login`, `GET /auth/session`, `POST /auth/logout`, `POST /auth/password`,
`POST /auth/password/change`.

The product's whole auth surface. Five things about it are load-bearing:

**There is no registration endpoint, and there never will be.** FR-1: accounts
are provisioned by an Administrator, and the first one is written by the
migration runner. `tests/test_no_registration.py` asserts the absence over the
route table *and* over the source tree, because "we just did not write it" is
not a guarantee.

**Every rejection is the same rejection.** Four states refuse a sign-in —
unknown address, wrong password, deactivated account, and a temporary
credential past its 72 hours — and a caller cannot tell them apart. Same
status, same code, same message, same headers, and the same Argon2id work, so
the response time does not separate them either. They are all built by
`_rejected()` for exactly that reason: two of them (`active = false`, expired
credential) are states a maintainer will one day be tempted to explain to the
user "to be helpful", and constructing them from one factory makes that a
visible edit rather than an accident.

**The forced change is the one write that ends every session of its user.**
`POST /auth/password` is where an admin-issued temporary credential stops being
trusted, and a credential that travelled by note or message may have been
issued a session on a device its owner cannot reach. Replacing the digest
without revoking those would leave the note working. The caller is handed a
fresh token in the same response, so their own browser is not bounced to the
login screen. The *gate* that makes the change unavoidable is not here — it is
`api.dependencies.require_claimed_user`, declared by every route that serves
real data.

**A sign-in is throttled before it is processed.** FR-4: a progressive delay
from the 6th failure and a lockout on the 10th. The counter lives in
`api.throttle` — AD-8's Postgres row, one atomic increment-and-check — and is
keyed on the **submitted address**, never on `users.id`, because a ladder
attached to an account is an account-existence oracle and would undo the
identical-rejection rule above. The lockout is therefore the one rejection this
endpoint is allowed to word differently: it is reachable identically for a real
address and an invented one, so it leaks nothing, and EXPERIENCE.md requires
the screen to say something other than "email or password is incorrect".

**The two password writes are one behaviour behind two contracts.**
`POST /auth/password` exchanges a temporary credential for a real one and
refuses a claimed account; `POST /auth/password/change` (FR-5) is the signed-in
self-service change and refuses an *un*claimed one, because it declares
`require_claimed_user`. Between them they cover every account exactly once, and
neither is reachable for the other's state. What they do once they have decided
to write is deliberately identical — replace the digest, revoke every session of
that user, issue the caller a fresh one — so `delete_sessions_for_user` has one
meaning in this module rather than two.

**Not here.** There is **no signed-out recovery of any kind** — no reset route,
no token, no link, no mail transport, not even a dependency (FR-5, AGENTS.md
Policy: admins distribute credentials manually). A user who has forgotten their
password goes through an Administrator, and `tests/test_no_password_reset.py`
asserts the absence over the route table, over a live probe *and* over the
source tree and the dependency manifests. Neither password endpoint is
throttled (DW-40) — epics.md scopes Story 1.6 to login, and the self-service
change is a direct extension of that same open question rather than a new one.
There is no unlock surface either, and no story in Epic 1 owns one: the lock
expires on its own and FR-5 sends a locked-out user to an Administrator who has
nothing to press. Story 1.10 was where one was predicted; it shipped with the
edit it was scoped to — name, email and role — and no unlock, so DW-64's
recovery half stays open with no owner left.

**Every outcome of every route here is recorded, and the record is part of the
write.** Story 1.12 closed the gap this docstring used to describe: a sign-in,
each of the seven ways a sign-in is refused, a lockout refusal, a sign-out, both
password writes and the sessions they revoke all append an entry through
`api.audit` — the product's one write path, and the only file that names the
table. Each entry goes inside the same `with conn.transaction():` as the change
it records, so the two land together or neither does, and an entry that cannot
be written **fails the request** rather than being logged and stepped over.
That is the opposite of how this module treats its other secondary writes (the
swallowed session sweep, the swallowed counter clear, `throttle`'s mirror), and
deliberately: those are tidy-up, and this is what makes an action attributable
at all. `source_ip` reaches each entry through `api.audit.source_ip`, a
dependency that reads a header only when `TRUSTED_PROXY_HEADER` names one and
otherwise records the TCP peer — never a raw client-supplied header (AD-4).
What still leaves no durable trace is the *application* log's silence about the
address a failed sign-in submitted: that is recorded in the audit log, which has
AD-4's protections, and nowhere else (`api.throttle`).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Annotated
from uuid import UUID

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a handler's
# annotations at runtime to build its dependency graph, so a name that exists
# only for the type checker fails at import with a bare NameError.
import psycopg
from argon2.exceptions import InvalidHashError
from fastapi import APIRouter, Cookie, Depends, Response, status
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field
from shared_schema.errors import ApiError
from shared_schema.passwords import (
    MAX_PASSWORD_LENGTH,
    hash_password,
    password_rule_violation,
    verify_dummy_password,
    verify_password,
)
from shared_schema.user import User

from api import anomaly, audit
from api.audit import AuditAction
from api.db import get_connection, get_pool
from api.dependencies import (
    AUTH_CHALLENGE,
    NO_STORE,
    PASSWORD_CHANGE_REQUIRED,
    SET_A_PASSWORD_FIRST,
    UNAUTHORIZED,
    current_user,
    not_signed_in,
    require_claimed_user,
)
from api.sessions import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    delete_expired_sessions,
    delete_session,
    delete_sessions_for_user,
    issue_session,
    set_session_cookie,
)
from api.throttle import AttemptState, attempt_state, clear_failures, record_failure

logger = logging.getLogger("rocell.api.auth")

router = APIRouter(tags=["auth"])

#: The one thing a rejected sign-in is ever told. It names neither the field
#: that was wrong nor whether the account exists — EXPERIENCE.md's State
#: Patterns make that explicit for a deactivated account, and the same silence
#: covers the other three states.
INVALID_CREDENTIALS = "Email or password is incorrect."

#: `details.reason` on a `login_failed` entry — the seven ways this endpoint
#: refuses a sign-in, each of which answers the caller identically.
#:
#: Six of them go through `_count_and_refuse`, which is the single funnel that
#: makes "a failure is counted and recorded" a property of one function rather
#: than of six `raise` statements agreeing with each other. `MALFORMED_ADDRESS`
#: is the seventh and is written outside it, for the reason below.
#:
#: **They exist because the response cannot tell them apart and an operator
#: must be able to.** "Ten failures against an address that is not an account"
#: and "ten failures against a real one" are the same `401` to the caller and
#: entirely different events to whoever reads the log, and no other trace in
#: the product distinguishes them.
#:
#: `MALFORMED_ADDRESS` is the one that never reaches the counter: its key *is*
#: the string Postgres cannot hold, so nothing is counted and only the entry
#: records the attempt (with a `NULL` `target_email`, for the same reason).
REASON_UNKNOWN_ACCOUNT = "unknown_account"
REASON_WRONG_PASSWORD = "wrong_password"
REASON_CORRUPT_DIGEST = "corrupt_digest"
REASON_DEACTIVATED = "deactivated"
REASON_CREDENTIAL_EXPIRED = "credential_expired"
REASON_ACCOUNT_VANISHED = "account_vanished"
REASON_MALFORMED_ADDRESS = "malformed_address"

#: Why every session of a user went, on a `sessions_revoked` entry. Two causes
#: today: the routine rotation that rides with a password write, and the
#: silent revocation `set_password` performs when it discovers the temporary
#: credential lapsed — which is a security event in its own right and left no
#: trace at all before Story 1.12.
CAUSE_PASSWORD_WRITTEN = "password_written"
CAUSE_CREDENTIAL_EXPIRED = "credential_expired"

#: The longest address the endpoint will look at. Longer than RFC 5321's 254,
#: so it refuses only what is certainly not an address, and short enough that
#: the lookup is never handed a megabyte to index.
MAX_EMAIL_LENGTH = 320

#: The envelope code for a password this endpoint will not set, whichever rule
#: it broke. The *message* names the rule (EXPERIENCE.md:87) — a single code
#: with a rule-naming message is what lets `apps/web` branch once and still show
#: the user what to fix.
WEAK_PASSWORD = "weak_password"

#: The account already has a password of its own. Story 1.7 owns the signed-in
#: self-service change, and it needs a current password this endpoint
#: deliberately does not ask for.
PASSWORD_CHANGE_NOT_REQUIRED = "password_change_not_required"

#: FR-4's lockout, and the **one** rejection this endpoint is allowed to word
#: differently from `INVALID_CREDENTIALS`.
#:
#: That is not a hole in the identical-rejection rule, because the branch is
#: reachable in exactly the same way for an address with an account and for one
#: without: `api.throttle`'s counter is keyed on the address the caller
#: submitted, so ten failures against an invented address produce this same
#: response at the same attempt. It therefore distinguishes *how many times you
#: have failed*, which the caller already knows, and not *whether this account
#: exists*, which is the thing the rule protects.
#:
#: Distinct from `unauthorized` because the client's answer is different:
#: retyping the password will not help, so the screen must not mark either
#: field invalid or wipe what was typed. EXPERIENCE.md's Login-lockout row
#: requires the different message.
ACCOUNT_LOCKED = "account_locked"

#: What a locked-out caller is told. EXPERIENCE.md's register — short, factual,
#: no exclamation mark — and deliberately **naming no duration**: the same row
#: forbids a countdown, and the progressive delay has already been telling this
#: caller for four attempts that something is slowing them down. The
#: `Retry-After` header carries the number for a machine; nothing renders it.
#:
#: It says "this account" and not "your account": the address may well not be
#: one, and the sentence has to be true either way.
ACCOUNT_LOCKED_MESSAGE = "Too many sign-in attempts. This account is temporarily locked."

#: The self-service change's own refusal: the caller is signed in, but the
#: `current_password` they submitted is not the one behind the stored digest.
#:
#: **Deliberately not `unauthorized`, and deliberately not a `401`.** The session
#: is fine — it is the field that was mistyped — and `apps/web`'s `apiRequest`
#: fires `notifyUnauthorized` on *status* 401, which `SessionProvider` answers by
#: dropping the shell to the login screen. Answering 401 here would therefore
#: sign a user out for mistyping a box, and hand them a login form that wants the
#: very password they have just failed to remember. `403` with a code of its own
#: is a refusal no observer watches, which is exactly what is wanted: the screen
#: marks the current-password field invalid and nothing else moves.
#:
#: It is also not `WEAK_PASSWORD`: nothing is wrong with the *new* password, and
#: the field the screen has to mark and focus is the other one.
INVALID_CURRENT_PASSWORD = "invalid_current_password"

#: The two states above, as the sentences the caller is shown.
ALREADY_CLAIMED = "This account already has a password of its own."
PASSWORD_REUSES_TEMPORARY = "The new password must be different from the temporary one."

#: What a wrong `current_password` is told. EXPERIENCE.md's register — short,
#: factual, no exclamation mark — and it names the field that was wrong, because
#: this endpoint takes two and the user has to know which one to retype.
CURRENT_PASSWORD_WRONG = "Your current password is incorrect."

#: A `WEAK_PASSWORD` *message*, not a code of its own, for exactly the reason
#: `PASSWORD_REUSES_TEMPORARY` is one: it is a rule about one account's stored
#: digest rather than about the string, so `shared_schema.passwords` cannot
#: decide it — and a client that already branches on `weak_password` and renders
#: the sentence needs nothing new to show it.
PASSWORD_UNCHANGED = "The new password must be different from your current one."

#: The point past which a submitted password stops being a password and becomes
#: a payload. Deliberately far above `MAX_PASSWORD_LENGTH` (128) rather than
#: equal to it: everything between the real rule and this ceiling has to reach
#: the handler, because only the handler can answer with the sentence that names
#: the rule — request validation would answer the generic "not in the expected
#: shape" that EXPERIENCE.md:87 forbids for a rejected password.
#:
#: 4 KiB is the smallest round number that no passphrase manager will ever
#: produce. It bounds what gets *worked on*, not what gets received: pydantic's
#: `max_length` runs after Starlette has read the whole body and after JSON
#: parsing, so a megabyte-sized body is buffered and decoded either way. A real
#: body-size limit belongs at the edge, and there is none yet. What this ceiling
#: does buy is that nothing past it reaches a `verify_password` or a
#: `hash_password`, and nothing is hashed for a candidate it admits and the
#: rules refuse — `password_rule_violation` runs first and costs one `len()`.
MAX_PASSWORD_FIELD_LENGTH = 4096

#: `credential_expired` fails **closed**: a `must_change_password` row whose
#: `temp_credential_expires_at` is NULL counts as expired, not as unexpired.
#: The column is nullable and `must_change_password` defaults true, so that row
#: shape is reachable — through an admin insert that forgets the expiry, or a
#: restored dump. Reading NULL as "no deadline" would give exactly those rows a
#: temporary credential that never dies, and AGENTS.md Policy gives them 72
#: hours without exception. Story 1.4's reissue path is how such a row is
#: recovered; it is not something login should quietly tolerate.
#:
#: `WHERE lower(email)`, not `WHERE email`, although the column is already
#: stored lowercase. `users` carries exactly one index on the address —
#: `users_email_lower_key ON users (lower(email))` — and an expression index
#: only serves the expression it was built on: the planner will not rewrite
#: `email = $1` into it on the strength of the CHECK constraint. Written the
#: other way this query sequentially scans `users` on every sign-in attempt, on
#: the one endpoint anybody can reach without a credential.
_SELECT_CREDENTIAL = """
SELECT id, password_hash, active, must_change_password, temp_credential_expires_at,
       (temp_credential_expires_at IS NULL OR temp_credential_expires_at <= now())
           AS credential_expired
  FROM users
 WHERE lower(email) = %s
"""

#: FR-10 — the Administrator's user list shows when each account last signed
#: in, and this is the only thing in the product that sets it. `updated_at` is
#: set by hand because `users` carries no BEFORE UPDATE trigger (DW-17); the
#: column's DEFAULT applies to inserts only, so leaving it out here would let
#: `updated_at` fall permanently behind `last_login_at`.
_RECORD_LOGIN = """
UPDATE users
   SET last_login_at = now(),
       updated_at = now()
 WHERE id = %s
RETURNING id, name, email, role, active, must_change_password,
          temp_credential_expires_at, last_login_at, locked_until,
          created_at, updated_at
"""


class LoginRequest(BaseModel):
    """The login body.

    `extra="forbid"`: a field this endpoint does not read is a caller with a
    different idea of the contract, and silently discarding it is how a
    `remember_me` or a `role` gets sent for a year before anyone notices it
    does nothing.

    Both fields are bounded here rather than in the handler. The password's
    ceiling is `MAX_PASSWORD_LENGTH` — the same one `verify_password` enforces
    — so an oversized candidate is refused by validation and **nothing is
    hashed for it**. On an unauthenticated endpoint backed by a 64 MiB KDF,
    that is the difference between a login attempt and a CPU-exhaustion vector.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


def _is_addressable(email: str) -> bool:
    """Whether the address can be handed to Postgres as a text parameter at all.

    A C string has no way to carry a NUL byte, so Postgres text cannot hold
    one and psycopg raises rather than sending it. That raise would escape as a
    500 — the one input class this endpoint answers differently from every
    other, which is exactly the shape of signal the identical-rejection rule
    exists to remove. Control characters go with it: none of them appears in an
    address, and the check is cheaper than the query it precedes.

    The other `str` psycopg cannot encode is one holding a lone surrogate, and
    it is deliberately **not** checked here: this endpoint never sees one,
    because the request body is parsed by pydantic's JSON reader, which refuses
    a lone surrogate escape outright and answers 422 before the handler runs.
    That is a boundary this function depends on without owning, so it is pinned
    by a test (`test_login.py`) rather than guarded twice — a second check here
    would be unreachable code asserting a failure that cannot arrive.
    """
    return not any(character < " " or character == "\x7f" for character in email)


def _rejected() -> ApiError:
    """The one rejection, for every way a sign-in can fail.

    One constructor, so the paths cannot drift apart — in status, in code, in
    message *or* in headers. See the module docstring.
    """
    return ApiError(
        UNAUTHORIZED,
        INVALID_CREDENTIALS,
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={**AUTH_CHALLENGE, **NO_STORE},
    )


def _locked(retry_after: int) -> ApiError:
    """The lockout refusal. Beside `_rejected()`, and deliberately not part of it.

    `429`, not `401`: nothing is wrong with the credential — it was not even
    looked at — and a `401` would send `apps/web` to re-ask for one, which is
    the opposite of what has to happen. It carries no `WWW-Authenticate`
    challenge for the same reason: there is no credential that would work right
    now.

    `Retry-After` is machine-facing. RFC 9110 defines it on a 429, a client that
    reads it can back off properly, and `apps/web` deliberately does not render
    it — EXPERIENCE.md forbids a countdown on the login screen.

    `NO_STORE` like every other response from this module: a shared shop-floor
    tablet behind a caching proxy must not serve one person's lockout to the
    next.
    """
    return ApiError(
        ACCOUNT_LOCKED,
        ACCOUNT_LOCKED_MESSAGE,
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(retry_after), **NO_STORE},
    )


def _locked_until_iso(state: AttemptState) -> str | None:
    """When the lock this refusal cites lapses, as ISO 8601, for `details`.

    A separate function rather than an expression at each of the two lockout
    gates: `locked_until` is `None`-able on the dataclass even though both
    call sites have already checked `state.locked`, and a type-checker-pleasing
    conditional written twice is a conditional that can be written differently
    twice.
    """
    return None if state.locked_until is None else state.locked_until.isoformat()


def _count_and_refuse(
    conn: psycopg.Connection,
    email_key: str,
    *,
    reason: str,
    source_ip: str | None,
    user_id: UUID | None = None,
) -> ApiError:
    """Record this failed attempt and build the refusal it has earned.

    Every rejection path in `login` below goes through here, so "a failure is
    counted" and "a failure is *recorded*" are both properties of the one place
    the refusal is constructed rather than of six `raise` statements agreeing
    with each other — the same argument `_rejected()` itself is built on.

    Returns rather than raises, so every call site still reads `raise ...` and
    a path that forgot to raise is a visible mistake rather than a silently
    continued handler.

    **The six causes that reach here are indistinguishable to the caller and
    distinct in the log** — `malformed_address` is the seventh refusal and is
    recorded by `login` itself, because its key is the one string Postgres
    cannot hold. `reason` is the whole difference: the response is
    byte-identical across all of them (that is the module's first rule), and
    the audit entry says which one it was. That asymmetry is the point — the refusal leaks
    nothing about whether the address is an account, and the record explains
    everything to somebody who is allowed to read it.

    **A counter write that fails does not fail the sign-in; an audit write that
    fails does.** The two are not the same kind of write. The counter is FR-4's
    rate limit and a fault in it fails in the safe direction — the attempt goes
    uncounted, the rejection stands, and it is logged. The audit entry is the
    record of record (FR-20, NFR4): an attempt that happened with nothing
    written down is the state Story 1.12 exists to prevent, so
    `psycopg.Error` propagates out of `audit.record` and `api.main` answers
    500. Ordered counter-then-entry so that `details.locked_until` can carry
    the lock this very attempt wrote.
    """
    locked_until: datetime | None = None
    try:
        state = record_failure(conn, email_key)
    except psycopg.Error:
        logger.warning(
            "the failed-attempt counter could not be written; the rejection itself stands",
            exc_info=True,
        )
        state = None
    else:
        locked_until = state.locked_until

    details: dict[str, object] = {"reason": reason}
    if locked_until is not None:
        # The attempt that crossed the threshold carries the lock it wrote.
        # One event, one row: a second `login_refused_locked` entry here would
        # claim a refusal that has not happened yet — this attempt was refused
        # for `reason`, and the *next* one is the one the lock turns away.
        details["locked_until"] = locked_until.isoformat()

    audit.record(
        conn,
        action=AuditAction.LOGIN_FAILED,
        actor_id=user_id,
        actor_email=None if user_id is None else email_key,
        target_id=user_id,
        target_email=email_key,
        source_ip=source_ip,
        details=details,
    )

    if state is not None and state.locked:
        return _locked(state.retry_after())
    return _rejected()


class _SignInVanished(Exception):
    """The user row disappeared between the credential read and the login write.

    Raised and caught inside `login` alone. It exists because that failure is
    discovered *inside* the sign-in transaction, and the failure has to be
    counted like every other — but a `record_failure` issued in there would be
    rolled back by the very `raise` that reports it. Unwinding the transaction
    first and counting afterwards is the only order that leaves both the
    transaction clean and the attempt recorded.
    """


def _weak_password(rule: str) -> ApiError:
    """Refuse a password, naming the rule it broke.

    `422`, matching the shape of every other body the request contract refuses,
    and one code for every rule so a client branches once. The rule is in the
    message because EXPERIENCE.md:87 requires the screen to say which one
    failed — "length, reuse of the temporary password" — and never a generic
    "invalid password".
    """
    return ApiError(
        WEAK_PASSWORD,
        rule,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        headers=NO_STORE,
    )


@router.post("/auth/login", response_model=User)
def login(
    payload: LoginRequest,
    response: Response,
    pool: Annotated[ConnectionPool, Depends(get_pool)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
    rocell_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Verify a credential, issue a session, and return the signed-in `User`.

    Defined as `def`, not `async def`: psycopg is a synchronous driver and
    Argon2id verification is CPU-bound for ~100ms. FastAPI runs a sync endpoint
    in its threadpool, so neither blocks the event loop; an `async def` around
    the same calls would block every other request in the process.

    **This is the one handler in the product that takes the pool rather than a
    connection**, and the reason is FR-4's delay. `Depends(get_connection)`
    checks a connection out before the body runs and returns it in the
    dependency's teardown, so a `time.sleep` anywhere in here would hold one for
    the whole ladder. `api.db` caps the pool at `POOL_MAX_SIZE` (10) with a
    `POOL_TIMEOUT_SECONDS` (10s) wait, so ten throttled sign-ins sleeping at
    once would empty the pool and every other request in the product — not just
    login — would start failing on pool acquisition. An attacker primes that
    with five cheap failures per address, which makes the throttle itself the
    denial of service it exists to prevent.

    So the body takes two short-lived connections with the sleep *between*
    them: the counter read in the first, the credential work and the sign-in in
    the second. Nothing is checked out while this handler waits.
    """
    response.headers.update(NO_STORE)

    # Lowercased before the lookup so the parameter matches `lower(email)`, the
    # expression the one index on the column is built on. `users.email` is
    # stored lowercase already (CHECK (email = lower(email))), so this changes
    # which rows match not at all and which plan runs completely.
    email = payload.email.strip().lower()

    if not _is_addressable(email):
        # A NUL byte cannot survive a Postgres text parameter: psycopg refuses
        # it and the driver's error would leave this endpoint answering 500 for
        # one class of input and 401 for every other. Nothing that contains one
        # is an address, so it is refused here — through the same decoy work and
        # the same rejection, so it stays indistinguishable like the rest.
        #
        # Uncounted, and necessarily so: the counter's key *is* this string, and
        # it is the one string that cannot be sent to Postgres at all. Nothing is
        # lost by it — an attacker who appends a NUL to every guess never reaches
        # the credential check either, so the attempts this skips are attempts
        # that could not have succeeded.
        #
        # **Recorded, though**, on a connection taken for this one statement.
        # The counter cannot hold this string and neither can `target_email`
        # (a `text` column cannot carry a NUL byte either), so the entry names
        # the reason and nothing else — which is still the difference between
        # "somebody is probing with malformed input" and silence. It is also
        # the one path that now does *more* database work than it used to
        # rather than less, so the timing discipline above is unharmed.
        verify_dummy_password(payload.password)
        with pool.connection() as conn:
            audit.record(
                conn,
                action=AuditAction.LOGIN_FAILED,
                source_ip=source_ip,
                details={"reason": REASON_MALFORMED_ADDRESS},
            )
        raise _rejected()

    # FR-4, before anything is spent on the credential. Read from the counter
    # keyed on the address *as submitted* — see `api.throttle` for why it is
    # never keyed on `users.id`.
    #
    # Its own connection, given back at the end of this block. Everything this
    # handler does between here and the credential read is arithmetic on
    # `state`, and holding a connection through it is what the docstring above
    # refuses to do.
    with pool.connection() as conn:
        state = attempt_state(conn, email)

        if state.locked:
            # Refused outright, and refused *here*: no Argon2id work, no counter
            # write, no sleep, and no credential read. A locked address costs the
            # server one indexed lookup however many times it is tried, which is
            # the point of locking it — and a correct password gets this same
            # answer, because the lock wins over the credential.
            #
            # One entry, and it is its own action rather than a seventh
            # `login_failed` reason: nothing was verified and nothing was
            # counted, so calling it a failed sign-in would inflate the very
            # number an operator reads this log to judge. Autocommit, like the
            # counter write it deliberately does not make.
            audit.record(
                conn,
                action=AuditAction.LOGIN_REFUSED_LOCKED,
                target_email=email,
                source_ip=source_ip,
                details={"locked_until": _locked_until_iso(state)},
            )
            raise _locked(state.retry_after())

    # The progressive delay, paid *before* the credential is read or hashed, so
    # it is a delay on processing the attempt rather than on answering it, and
    # paid **outside** both connection blocks — see the docstring.
    #
    # `time.sleep` in a sync handler: FastAPI runs this endpoint in its
    # threadpool, so the event loop is untouched, and with no connection held
    # the only resource this occupies is one of Starlette's 40 threadpool
    # workers. `MAX_DELAY` still caps the ladder, and is still worth having —
    # it bounds how long an attacker can pin a worker — but it is no longer
    # standing between a throttled attempt and the connection pool, and it is
    # not an answer to DW-34, which remains open for the threadpool/pool size
    # mismatch on its own terms.
    #
    # A `Retry-After` refusal instead would be a different behaviour, not a
    # delayed one, and epics.md 1.6 asks for a delay.
    #
    # Paid on a *correct* credential too. Skipping it there would make the delay
    # a password oracle: a fast answer on the sixth attempt would mean the
    # guess was right before the session cookie ever arrived.
    delay = state.delay()
    if delay:
        time.sleep(delay.total_seconds())

    with pool.connection() as conn:
        if delay:
            # The state above was read before the sleep, so on a delayed attempt
            # it is up to `MAX_DELAY` old — and the attempts that put this one on
            # the ladder in the first place are, by definition, still arriving.
            # One of them can write the lock while this request is asleep, and
            # without this re-read that request would go on to spend a full
            # Argon2id verify on a locked address and, if the credential happened
            # to be correct, be issued a session and then *delete the counter row
            # the lock lives in* — ending everyone else's lockout with it. The
            # matrix is unambiguous that the lock wins over the credential, so it
            # has to be re-asked after the wait rather than before it.
            #
            # Only on a delayed attempt: an undelayed one acts on a state read
            # microseconds earlier, which is the same window every other
            # statement in this handler already runs in, and paying a second
            # lookup on every ordinary sign-in to close it would buy nothing.
            state = attempt_state(conn, email)
            if state.locked:
                # The same refusal as the gate above, reached after the sleep,
                # and recorded the same way.
                audit.record(
                    conn,
                    action=AuditAction.LOGIN_REFUSED_LOCKED,
                    target_email=email,
                    source_ip=source_ip,
                    details={"locked_until": _locked_until_iso(state)},
                )
                raise _locked(state.retry_after())

        return _authenticate(conn, response, payload, email, source_ip, rocell_session)


def _authenticate(
    conn: psycopg.Connection,
    response: Response,
    payload: LoginRequest,
    email: str,
    source_ip: str | None,
    rocell_session: str | None,
) -> User:
    """The credential half of `login`, on a connection taken after the delay.

    Split out for one reason: `login` must not hold a connection across its
    sleep, and a second `with pool.connection()` block wrapping the whole of
    this would re-indent it under a context manager that has nothing to do with
    what it is doing. The ordering inside is unchanged from Story 1.3 —
    `_SELECT_CREDENTIAL`, the verify, the `active` and `credential_expired`
    checks, `_RECORD_LOGIN`, `issue_session`, the swallowed sweep — and every
    rejection is still the one `_rejected()` builds.
    """
    row = conn.execute(_SELECT_CREDENTIAL, (email,)).fetchone()

    if row is None:
        # No account: spend the same Argon2id work a real verify would, so the
        # response time does not tell the caller the address is unknown (DW-24).
        verify_dummy_password(payload.password)
        raise _count_and_refuse(conn, email, reason=REASON_UNKNOWN_ACCOUNT, source_ip=source_ip)

    try:
        verified = verify_password(row["password_hash"], payload.password)
    except InvalidHashError:
        # The column holds something `shared_schema.passwords` did not write.
        # `verify_password` raises rather than returning False on purpose, so a
        # data-integrity fault is never reported as a wrong password — but
        # letting it out of *this* endpoint answers 500 where every other
        # address answers 401, and that difference tells a caller the account
        # exists. Logged at error level so the fault is loud where it belongs,
        # and answered with the one rejection like everything else.
        logger.error("users.password_hash is not an Argon2id digest for user %s", row["id"])
        # `verify_password` parses the stored digest before it hashes anything,
        # so this branch has spent none of the ~100ms every other rejection
        # costs. Left as it is, a corrupt row answers measurably faster than a
        # wrong password — which tells a caller the account exists, the one
        # thing the identical-rejection rule is for. The decoy pays the
        # difference.
        verify_dummy_password(payload.password)
        raise _count_and_refuse(
            conn,
            email,
            reason=REASON_CORRUPT_DIGEST,
            source_ip=source_ip,
            user_id=row["id"],
        ) from None

    if not verified:
        raise _count_and_refuse(
            conn,
            email,
            reason=REASON_WRONG_PASSWORD,
            source_ip=source_ip,
            user_id=row["id"],
        )

    # Both checks below come *after* a real verify, so they cost the same as a
    # wrong password by construction — no decoy is needed on these two paths.
    if not row["active"]:
        raise _count_and_refuse(
            conn,
            email,
            reason=REASON_DEACTIVATED,
            source_ip=source_ip,
            user_id=row["id"],
        )

    # AGENTS.md Policy gives an admin-issued temporary credential 72 hours,
    # without exception, and this endpoint is the only place a credential is
    # ever presented. Leaving the check to Story 1.4 — which owns the
    # forced-change *screen* — would ship a window in which an expired
    # credential authenticates.
    if row["must_change_password"] and row["credential_expired"]:
        raise _count_and_refuse(
            conn,
            email,
            reason=REASON_CREDENTIAL_EXPIRED,
            source_ip=source_ip,
            user_id=row["id"],
        )

    try:
        with conn.transaction():
            user_row = conn.execute(_RECORD_LOGIN, (row["id"],)).fetchone()
            if user_row is None:
                # Deleted between the credential read and this write. Rare, and
                # the alternative is `User.model_validate(None)` raising a 500
                # after the password has already been verified — an answer no
                # other outcome of this endpoint gives. Reported out of the
                # transaction rather than refused inside it, so the failure can
                # be counted like every other: see `_SignInVanished`.
                raise _SignInVanished
            # The cookie this request arrived with is about to be overwritten,
            # so its row would otherwise stay live and unreachable until one of
            # its two deadlines caught it: the browser can no longer present it,
            # logout only revokes the cookie it is given, and nothing in the
            # product revokes a user's sessions in bulk on their behalf. Signing
            # in again is the one moment the old token is still in hand, so it
            # is spent here. This ends exactly the session this browser was
            # holding, and no other device is touched.
            delete_session(conn, rocell_session)
            raw_token = issue_session(conn, row["id"])
            # FR-20's entry, inside the sign-in's own transaction — not beside
            # it. A session issued with no record of who signed in is the one
            # state the log exists to prevent, and a write that can be rolled
            # back independently of the thing it records is a log that
            # disagrees with the table it describes. Actor and target are the
            # same person here: a sign-in is somebody acting on their own
            # account, and writing both columns rather than leaving `target`
            # null keeps "every entry names who it was about" true for the
            # read Story 1.13 builds.
            #
            # Not on a savepoint, unlike `clear_failures` below. That one is
            # guarded because a fault in a *counter* must not fail a correct
            # password; this one is guarded by nothing on purpose — see the
            # module docstring.
            audit.record(
                conn,
                action=AuditAction.LOGIN_SUCCEEDED,
                actor_id=user_row["id"],
                actor_email=user_row["email"],
                target_id=user_row["id"],
                target_email=user_row["email"],
                source_ip=source_ip,
            )
            # Story 3.7 / FR-22: checked on every successful sign-in, in the
            # same transaction as the sign-in it describes — a flag and the
            # login it names commit or roll back together, `LOGIN_SUCCEEDED`'s
            # own reasoning just above. Only a *successful* sign-in counts
            # toward this baseline (a failed attempt or a lockout is FR-4's
            # `throttle.py` mechanism, a different signal). `anomaly.py` never
            # writes the audit log itself and never decides to refuse — a `True`
            # here changes nothing about the session about to be issued; it
            # only adds one more entry recording that it was.
            #
            # **Guarded, unlike `LOGIN_SUCCEEDED` above.** This is a purely
            # additive, non-critical signal — epics.md's own "a flag never
            # blocks the action that produced it" — so a transient fault
            # computing or recording it must never sink an otherwise-valid,
            # already-authenticated sign-in. `record_failure`'s own pattern:
            # a nested `conn.transaction()` (a SAVEPOINT) so a failure here
            # unwinds only this check, never the sign-in already committed to
            # the outer transaction, and `psycopg.Error` is swallowed and
            # logged rather than left to fail the request.
            try:
                with conn.transaction():
                    if anomaly.check_and_flag(conn, user_row["id"], "login"):
                        audit.record(
                            conn,
                            action=AuditAction.LOGIN_ANOMALY_FLAGGED,
                            actor_id=user_row["id"],
                            actor_email=user_row["email"],
                            target_id=user_row["id"],
                            target_email=user_row["email"],
                            source_ip=source_ip,
                        )
            except psycopg.Error:
                logger.warning(
                    "the anomaly check could not be completed; the sign-in itself stands",
                    exc_info=True,
                )
            # The run of failures ends here, in the same transaction as the
            # sign-in that ended it: a session issued while the counter still
            # held nine failures would leave the next mistyped password locking
            # an account whose owner has just proved they are its owner. If the
            # transaction unwinds, the count stands — which is the safe
            # direction.
            #
            # On a savepoint, because this is the last counter write in the
            # product that could still fail a request. `record_failure`, the
            # status mirror and both sweeps all swallow `psycopg.Error` so a
            # fault in the counter never decides the response; unguarded here,
            # a statement timeout or a lost connection on this one `DELETE`
            # would roll back the whole block and answer 500 to a *correct*
            # password, leaving the user with no cookie and the count still at
            # nine — strictly worse than the outcome below, which keeps the
            # session and leaves the count exactly where the unguarded version
            # would have left it too. The nested `conn.transaction()` is a
            # SAVEPOINT: it unwinds the delete alone and the sign-in above
            # commits.
            try:
                with conn.transaction():
                    clear_failures(conn, email)
            except psycopg.Error:
                logger.warning(
                    "the failure counter could not be cleared; the sign-in itself stands",
                    exc_info=True,
                )
    except _SignInVanished:
        # The transaction has already rolled back, so the counter write below is
        # the first statement of a fresh autocommit sequence and will not be
        # undone with it. The audit entry rides on that same property: written
        # here rather than inside the block that has just unwound, so the one
        # refusal discovered mid-transaction is recorded like the other five.
        raise _count_and_refuse(
            conn,
            email,
            reason=REASON_ACCOUNT_VANISHED,
            source_ip=source_ip,
            user_id=row["id"],
        ) from None

    # The token leaves in the cookie and nowhere else — never in this body,
    # never anywhere page script can read it (AGENTS.md Policy, AD-3). Set
    # before the sweep below, because the session is already committed: every
    # statement from here on is riding on a sign-in that has happened.
    set_session_cookie(response, raw_token)

    # Housekeeping, not policy, and deliberately outside the transaction above:
    # `lookup_session` already refuses an expired row, so this only stops the
    # table growing one dead row per sign-in. Run inside the login transaction
    # it would hold the delete's row locks until the sign-in committed, and two
    # concurrent logins sweeping the same backlog would serialise on them.
    #
    # Swallowed on failure for the same reason it is out here: the sign-in is
    # committed, and a deadlock or a statement timeout in a table tidy-up must
    # not turn it into a 500 that leaves the user holding no cookie and the row
    # behind it live for seven days. Logged, because a sweep that keeps failing
    # is a table that keeps growing.
    try:
        delete_expired_sessions(conn)
    except psycopg.Error:
        logger.warning("expired-session sweep failed; the sign-in itself stands", exc_info=True)

    return User.model_validate(user_row)


@router.get("/auth/session", response_model=User)
def read_session(user: Annotated[User, Depends(current_user)]) -> User:
    """Who the caller is, re-read from Postgres on every call (AD-3).

    This is what makes a role change or a deactivation take effect on the very
    next request: nothing here trusts anything recorded when the session was
    issued.

    Deliberately **not** gated by `require_claimed_user`. A user on a temporary
    credential gets a `200` here carrying `must_change_password: true`, and that
    is how `apps/web` learns to render the forced-change screen at all — gating
    it would leave the front end with a 403 and no way to know why.
    """
    return user


#: Who the session that has just been revoked belonged to, for the entry's
#: actor snapshot (AD-10 wants an address beside every id).
#:
#: A second statement rather than a join inside `sessions._DELETE_SESSION`,
#: because that module owns statements against `sessions` and this one is a
#: read of `users` — and because the delete has to report *whether* it deleted
#: whatever the user turns out to be. It runs only on the path that actually
#: revoked something, so an idempotent second `POST /auth/logout` costs nothing
#: extra.
#:
#: A `None` here is a user deleted between the delete and this read, which
#: `ON DELETE CASCADE` makes vanishingly unlikely; the entry is still written,
#: with the id and no address, because "somebody signed out" is true either
#: way.
_SELECT_ACTOR = """
SELECT email
  FROM users
 WHERE id = %s
"""


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
    rocell_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Response:
    """End this session. Idempotent — a second call is still `204`.

    Only *this* session. Signing out on a phone must not sign the same person
    out of the desktop they left open in the back office. Ending every session
    of a user is not a surface anybody drives: it happens through Story 1.11's
    deactivation, by the cascade and the `active` check in the lookup.

    Not named by Story 1.3's acceptance clauses and delivered anyway: issuing a
    session with no revocation path leaves clearing browser cookies as the only
    way out, `delete_session` is the counterpart of `issue_session` in the same
    module, and no later epic story delivers it.

    **An entry is written only when a session actually went.** A `204` for a
    cookie that names nothing revoked nothing, and a row saying otherwise would
    be the log recording an event that did not happen — which is a worse defect
    in an audit log than a missing one, because it cannot be told from a real
    one. `delete_session` reports what it removed, which is also how this route
    learns who to name without declaring `current_user`: it deliberately does
    not, because it must stay reachable with a dead cookie.
    """
    # One unit of work on an otherwise autocommit connection: the revocation
    # and the record of it commit together or neither does. An audit failure
    # therefore takes the sign-out with it and answers 500 — the caller
    # retrying an idempotent `204` costs nothing, and a session ended with
    # nothing written down is the gap this story closes.
    with conn.transaction():
        revoked_user_id = delete_session(conn, rocell_session)
        if revoked_user_id is not None:
            actor = conn.execute(_SELECT_ACTOR, (revoked_user_id,)).fetchone()
            audit.record(
                conn,
                action=AuditAction.LOGGED_OUT,
                actor_id=revoked_user_id,
                actor_email=None if actor is None else actor["email"],
                target_id=revoked_user_id,
                target_email=None if actor is None else actor["email"],
                source_ip=source_ip,
            )

    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(NO_STORE))
    clear_session_cookie(response)
    return response


class PasswordChangeRequest(BaseModel):
    """The forced-change body: one field, and deliberately only one.

    **No `current_password`.** The caller proved it at sign-in minutes ago and
    is holding the session it issued; asking for it again would be Story 1.7's
    contract, not this one. **No confirm field either** — DESIGN.md:219
    specifies a single-field form, and a second box with no rule behind it is
    another thing to type for no enforcement.

    `extra="forbid"`, like `LoginRequest`: a field this endpoint does not read
    is a caller with a different idea of the contract.

    **Neither length rule is enforced here**, and that is the point. Validation
    answers `422 validation_error` — "the request was not in the expected
    shape" — which is exactly the generic rejection EXPERIENCE.md:87 forbids for
    a password. Both bounds are the handler's, so an empty candidate and a
    129-character one are each answered by `password_rule_violation` with the
    sentence that names the rule they broke. `LoginRequest` bounds its password
    for the opposite reason: there the rules do not apply at all, and the
    ceiling is the only thing standing between an unauthenticated caller and a
    64 MiB hash.

    Nothing is hashed for an oversized candidate here either. The rule check
    runs before both the reuse verify and `hash_password`, so a string this
    model accepts and the rules refuse costs one `len()`.

    `MAX_PASSWORD_FIELD_LENGTH` is therefore not a password rule; it is the
    point past which a body stops being a password at all.
    """

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(max_length=MAX_PASSWORD_FIELD_LENGTH)


#: The digest, for the one rule this endpoint decides that `shared_schema`
#: cannot — the new password must not be the temporary one — and the deadline
#: the credential is still under. Read by id, from the session the caller
#: already presented.
#:
#: `credential_expired` is `_SELECT_CREDENTIAL`'s expression verbatim, and fails
#: **closed** for the same reason: a `must_change_password` row with a NULL
#: `temp_credential_expires_at` counts as expired, not as having no deadline.
#: Written the other way, the one row shape an admin insert is most likely to
#: produce by mistake would get a temporary credential that never dies.
_SELECT_CREDENTIAL_STATE = """
SELECT password_hash,
       (temp_credential_expires_at IS NULL OR temp_credential_expires_at <= now())
           AS credential_expired
  FROM users
 WHERE id = %s
"""

#: The claim, in one statement. `must_change_password` and
#: `temp_credential_expires_at` are cleared together: the expiry is what login
#: checks for an unclaimed row, and leaving it set would arm a deadline against
#: an account that no longer has a temporary credential to expire.
#:
#: `updated_at` is set by hand — `users` carries no BEFORE UPDATE trigger
#: (DW-17), and the column's DEFAULT applies to inserts only.
#:
#: The `RETURNING` list is `_RECORD_LOGIN`'s, exactly: it is the eleven-column
#: shape `User.model_validate` wants, and the two must not drift.
#:
#: `AND must_change_password` is what makes "the credential works exactly once"
#: a property of the *statement* rather than of the sequence of checks in front
#: of it. The 409 guard below reads a `User` fetched by a separate query, so two
#: posts arriving together on one session both pass it — and without this
#: predicate both would write, the second revoking the session the first had
#: just issued. With it, the loser matches no row, `RETURNING` is empty, and the
#: handler answers the same 409 it would have answered a second later.
_SET_PASSWORD = """
UPDATE users
   SET password_hash = %s,
       must_change_password = false,
       temp_credential_expires_at = NULL,
       updated_at = now()
 WHERE id = %s
   AND must_change_password
RETURNING id, name, email, role, active, must_change_password,
          temp_credential_expires_at, last_login_at, locked_until,
          created_at, updated_at
"""


def _already_claimed() -> ApiError:
    """The account has a password of its own. Story 1.7 owns changing that one.

    Raised from two places that are the same answer arriving at different
    moments: the guard that reads the session's `User`, and the `UPDATE` whose
    `AND must_change_password` matched nothing because another request got
    there first.
    """
    return ApiError(
        PASSWORD_CHANGE_NOT_REQUIRED,
        ALREADY_CLAIMED,
        status_code=status.HTTP_409_CONFLICT,
        headers=NO_STORE,
    )


@router.post("/auth/password", response_model=User)
def set_password(
    payload: PasswordChangeRequest,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
) -> User:
    """Exchange an admin-issued temporary credential for a real password.

    Authenticated, and deliberately **not** gated by `require_claimed_user` —
    gating the escape hatch on having already escaped would leave the account
    unreachable forever. It is the only ungated route that writes anything;
    `GET /auth/session` and `POST /auth/logout` are the other two exemptions and
    both are read-or-revoke. The allowlist and the reason for each live in
    `tests/test_forced_change_gate.py`.

    Sync, not `async def`: psycopg is a synchronous driver and the Argon2id hash
    below is CPU-bound for ~100ms. FastAPI runs a sync endpoint in its
    threadpool; an `async def` around the same calls would block every other
    request in the process.

    **This endpoint writes two audit entries, and the second is not a
    formality.** `password_claimed` records the change; `sessions_revoked`
    records what the change did to every other device, carrying
    `details.count`. They are two rows because they are two events an operator
    asks different questions about, and both go inside the write's own
    transaction, so a claim with no record of the revocation it performed
    cannot exist. There is a **third** entry on a path that is not a success at
    all: a temporary credential discovered lapsed here revokes every session
    silently before answering `401`, and that revocation is a security event in
    its own right — it now carries `details.cause = credential_expired` rather
    than leaving no trace whatsoever.
    """
    response.headers.update(NO_STORE)

    if not user.must_change_password:
        # Story 1.7's endpoint, not this one: a claimed account's own change
        # takes a current password and makes its own decision about
        # re-authentication. Answering here would be a password change on a
        # live session with nothing proved.
        raise _already_claimed()

    row = conn.execute(_SELECT_CREDENTIAL_STATE, (user.id,)).fetchone()
    if row is None:
        # Deleted between the session lookup and this read. The session is gone
        # with it; saying so is the honest answer and the cookie goes too.
        raise not_signed_in()

    if row["credential_expired"]:
        # AGENTS.md line 18 gives an admin-issued temporary credential 72 hours
        # without exception, and login is not the only place that deadline has
        # to hold. A session lives for seven days (`SESSION_ABSOLUTE_LIFETIME`),
        # so a user who signs in at hour 1 and comes back at hour 100 is refused
        # at login and — without this check — could still claim the account
        # here, through the session the credential issued while it was alive.
        # That is the 72 hours turned into eleven days by the session that rode
        # out of them.
        #
        # Every session of this user goes, not merely this browser's: they were
        # all issued on a credential that is now dead, and one of them may be on
        # a device whose holder saw the note it was written on. The way back is
        # a reissue — `make reseed-admin` for the seeded Administrator — which
        # is also what the 401 tells any client that reads only the status.
        with conn.transaction():
            revoked = delete_sessions_for_user(conn, user.id)
            # The silent revocation, made loud where it belongs. Nothing about
            # this is visible to the user — they get the same `401` a dead
            # cookie gets — and before Story 1.12 nothing about it was visible
            # to anybody: no row changed, so not even `updated_at` moved. In
            # the same transaction as the delete it describes.
            audit.record(
                conn,
                action=AuditAction.SESSIONS_REVOKED,
                actor_id=user.id,
                actor_email=user.email,
                target_id=user.id,
                target_email=user.email,
                source_ip=source_ip,
                details={"cause": CAUSE_CREDENTIAL_EXPIRED, "count": revoked},
            )
        raise not_signed_in()

    # The length rules, in their one statement (`shared_schema.passwords`), and
    # checked before the reuse verify below so a too-short password costs no
    # Argon2id work at all. This is also where an empty or oversized candidate
    # is answered — the request model deliberately bounds neither, so that both
    # get the sentence naming the rule rather than a generic 422.
    violation = password_rule_violation(payload.new_password)
    if violation is not None:
        raise _weak_password(violation)

    # The one rule that costs a verify, and the only one that needs the stored
    # digest: EXPERIENCE.md:87 names exactly two — length, and reuse of the
    # temporary password. Reuse of an *older* password is not checked, and
    # deliberately: a history rule needs a history table, a retention policy and
    # a decision about how many, none of which this epic asks for.
    #
    # `InvalidHashError` is left to propagate. It means the column holds
    # something `shared_schema.passwords` did not write — and such an account
    # cannot sign in at all, so it cannot reach this line. Swallowing it here
    # would let a corrupt digest be silently overwritten, destroying the
    # evidence of a data-integrity fault.
    if verify_password(row["password_hash"], payload.new_password):
        raise _weak_password(PASSWORD_REUSES_TEMPORARY)

    # Hashed before the transaction opens. ~100ms of CPU inside an open
    # transaction is ~100ms of held row locks on `users` for no benefit.
    new_hash = hash_password(payload.new_password)

    with conn.transaction():
        user_row = conn.execute(_SET_PASSWORD, (new_hash, user.id)).fetchone()
        if user_row is None:
            # `AND must_change_password` matched nothing: either a concurrent
            # post claimed the account a moment ago, or the row was deleted.
            # Both mean this request must not write, and the transaction unwinds
            # having written nothing.
            raise _already_claimed()
        # Credential rotation, in the same transaction as the digest it
        # rotates: the temporary credential has just stopped being trusted, and
        # any session issued on it — including one opened on another device by
        # whoever saw the note it was written on — goes with it. Not a
        # session-management surface; this is one user acting on their own
        # account.
        revoked = delete_sessions_for_user(conn, user.id)
        # Issued inside the same transaction, so the caller is never left
        # holding a revoked cookie: either the whole change lands or none of it
        # does.
        raw_token = issue_session(conn, user.id)
        # Two entries, in the order the two events happened, in the
        # transaction that performed them. `user_row` rather than `user` for
        # the snapshot: the address is read back from the write, so an entry
        # cannot describe a row the statement did not actually touch.
        audit.record(
            conn,
            action=AuditAction.PASSWORD_CLAIMED,
            actor_id=user_row["id"],
            actor_email=user_row["email"],
            target_id=user_row["id"],
            target_email=user_row["email"],
            source_ip=source_ip,
        )
        # `count` is the number of devices this signed out, including the
        # caller's own cookie — which is why the fresh token above exists.
        # It is the only record of that, anywhere.
        audit.record(
            conn,
            action=AuditAction.SESSIONS_REVOKED,
            actor_id=user_row["id"],
            actor_email=user_row["email"],
            target_id=user_row["id"],
            target_email=user_row["email"],
            source_ip=source_ip,
            details={"cause": CAUSE_PASSWORD_WRITTEN, "count": revoked},
        )

    # The token leaves in the cookie and nowhere else (AGENTS.md Policy, AD-3).
    set_session_cookie(response, raw_token)

    return User.model_validate(user_row)


class PasswordSelfChangeRequest(BaseModel):
    """The self-service change's body: the current password, and the new one.

    **`current_password` is the whole difference from `PasswordChangeRequest`.**
    That body deliberately omits it because the caller proved it at sign-in
    minutes ago and is holding the session it issued — a temporary credential is
    exchanged once, under a gate, and asking for it again would be a second
    hurdle in front of the only door the account has. This body is the opposite
    case: the account is claimed, the session may be hours old, and the thing
    being replaced is a password its owner chose. Proving the current one is the
    only thing standing between a borrowed unlocked phone and a permanent
    takeover of the account, so it is required and it is checked first.

    **No confirm field, no reveal toggle, no strength meter** — the same three
    absences the forced-change form documents, for the same reasons: none is
    specified anywhere, and a second box with no rule behind it is another thing
    to type for no enforcement.

    `extra="forbid"`, like every other body in this module: a field this endpoint
    does not read is a caller with a different idea of the contract.

    **Neither field carries a minimum**, and the new one carries no password
    rule — because validation answers `422 validation_error`, "the request was
    not in the expected shape", which is exactly the generic rejection
    EXPERIENCE.md:87 forbids for a password. Both bounds are the handler's, so an
    empty candidate and a
    129-character one are each answered by `password_rule_violation` with the
    sentence naming the rule they broke. `MAX_PASSWORD_FIELD_LENGTH` is not a
    password rule; it is the point past which a body stops being a password at
    all, and nothing past it reaches a `verify_password` or a `hash_password`.
    """

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(max_length=MAX_PASSWORD_FIELD_LENGTH)
    new_password: str = Field(max_length=MAX_PASSWORD_FIELD_LENGTH)


#: The stored digest, for the one thing this endpoint proves before it does
#: anything else. Read by id, from the session the caller already presented.
#:
#: No `credential_expired` expression, unlike `_SELECT_CREDENTIAL_STATE`: the
#: route declares `require_claimed_user`, so by the time this runs the account is
#: known not to be on a temporary credential and there is no 72-hour deadline
#: left to check. A row that *is* on one never reaches this statement.
_SELECT_PASSWORD_HASH = """
SELECT password_hash
  FROM users
 WHERE id = %s
"""

#: Whether the row is still there, re-read when the write matched nothing. Its
#: only job is to tell "the account was deleted" from "an Administrator reissued
#: a temporary credential a microsecond ago", which are the only two ways
#: `_CHANGE_PASSWORD` can return no row — so row existence is the whole question
#: and `1` is the whole answer. Reading `must_change_password` back would look
#: more careful and be less true: the flag it returns is the flag *now*, which is
#: a third instant, and a value read after the fact cannot say why a statement in
#: the past refused. `_CHANGE_PASSWORD`'s own predicate is what decides that.
_SELECT_ROW_EXISTS = """
SELECT 1
  FROM users
 WHERE id = %s
"""

#: The self-service change, in one statement.
#:
#: `must_change_password` and `temp_credential_expires_at` are **not** touched,
#: and that is the difference from `_SET_PASSWORD`: this account has no temporary
#: credential to clear, so writing either column would be inventing state. The
#: flag is false here by the gate's own guarantee and stays false.
#:
#: `updated_at` is set by hand — `users` carries no BEFORE UPDATE trigger
#: (DW-17), and the column's DEFAULT applies to inserts only.
#:
#: `AND NOT must_change_password` is the same trick `_SET_PASSWORD`'s
#: `AND must_change_password` plays, in mirror image. `require_claimed_user` read
#: the flag through a separate query some microseconds earlier; an Administrator
#: reissuing a temporary credential in that window would otherwise have this
#: request overwrite the credential they had just issued. With the predicate, the
#: loser matches no row, `RETURNING` is empty, and the handler answers the gate's
#: own 403 — making "the gate's fact is still true at the moment of the write" a
#: property of the statement rather than of a check taken earlier.
#:
#: The `RETURNING` list is `_RECORD_LOGIN`'s and `_SET_PASSWORD`'s, character for
#: character: it is the eleven-column shape `User.model_validate` wants, and the
#: three must not drift. Repeated rather than shared through a constant because
#: `tests/test_source_guards.py` forbids a statement assembled from a value;
#: `tests/test_self_service_password_change.py` is what holds the three lists
#: together instead.
_CHANGE_PASSWORD = """
UPDATE users
   SET password_hash = %s,
       updated_at = now()
 WHERE id = %s
   AND NOT must_change_password
RETURNING id, name, email, role, active, must_change_password,
          temp_credential_expires_at, last_login_at, locked_until,
          created_at, updated_at
"""


def _invalid_current_password() -> ApiError:
    """The submitted `current_password` is not the one behind the stored digest.

    Beside `_weak_password`, and deliberately not part of it: nothing is wrong
    with the new password — it has not even been looked at — so the field the
    screen marks and focuses is the other one.

    `403`, never `401`. See `INVALID_CURRENT_PASSWORD` for why a 401 here would
    sign the user out of a session that is perfectly good.
    """
    return ApiError(
        INVALID_CURRENT_PASSWORD,
        CURRENT_PASSWORD_WRONG,
        status_code=status.HTTP_403_FORBIDDEN,
        headers=NO_STORE,
    )


def _password_change_required() -> ApiError:
    """The gate's refusal, raised from inside the write rather than in front of it.

    Built from `api.dependencies`' own code and sentence rather than restating
    either, so the two answers to "this account is on a temporary credential"
    cannot drift apart. It is constructed here instead of routed through
    `require_claimed_user` because that dependency takes a whole `User` and this
    branch has re-read exactly one column — building a `User` to throw it away
    would be a second full query for a case that never happens.
    """
    return ApiError(
        PASSWORD_CHANGE_REQUIRED,
        SET_A_PASSWORD_FIRST,
        status_code=status.HTTP_403_FORBIDDEN,
        headers=NO_STORE,
    )


@router.post("/auth/password/change", response_model=User)
def change_password(
    payload: PasswordSelfChangeRequest,
    response: Response,
    user: Annotated[User, Depends(require_claimed_user)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    source_ip: Annotated[str | None, Depends(audit.source_ip)],
) -> User:
    """FR-5 — a signed-in user replaces the password they already chose.

    **A separate path from `/auth/password`, not a second method on it.** Three
    guards in this repository address a route by `(method, path)` or by path
    alone — `tests/test_forced_change_gate.py`'s allowlist, the exact path set in
    `tests/test_no_registration.py`, and whatever counter DW-40 eventually brings
    — and two contracts sharing one path would have to be taught the distinction
    in all three, where the one that forgot would fail open. `PUT` is wrong on
    its own terms as well: this is not idempotent, because a replay cannot prove
    a current password that is no longer current.

    **It declares `require_claimed_user`**, so a user still holding an
    admin-issued temporary credential is refused `403 password_change_required`
    and sent to `POST /auth/password`, which is the route for that account.
    Answering both from one place would make the forced change skippable.

    **The current password is proved before anything else happens.** Before the
    new password's rules are read, before the two are compared, and before
    `hash_password`. Both orderings would "work"; this one is the only one where
    a caller who cannot prove the current password learns nothing about the new
    one and gets no decision at all out of an endpoint they have not
    authenticated to. The cost is one Argon2id verify on a request that was going
    to be refused anyway.

    **The change revokes every session of its user and issues the caller a fresh
    one**, inside the same transaction as the digest write — `POST /auth/password`
    exactly. The reason people change a password they already chose is that they
    think somebody else has it, and a change that leaves that somebody's session
    alive has not done the thing the user asked for. The caller's own browser is
    handed a new token in the same response, so the change does not bounce them
    to the login screen.

    Nothing else is cleared. `login_attempts` and `users.locked_until` are
    untouched: a lock is a property of the address under attack, not of the
    credential, and letting a signed-in user clear it would hand an attacker a
    way to reset the ladder (DW-57 is the related reissue gap).

    Sync, not `async def`, for the reason `set_password` is: psycopg is a
    synchronous driver and the verify and hash below are CPU-bound for ~100ms
    each. FastAPI runs a sync endpoint in its threadpool.

    **Two audit entries on success, exactly as `POST /auth/password` writes
    two** — `password_changed`, then `sessions_revoked` with `details.count` —
    both inside the write's own transaction. And **one on the refusal**: a
    wrong `current_password` appends `password_change_refused`, naming the
    signed-in caller as the actor. That entry is deliberately not shaped like a
    `login_failed`: nothing about the *session* is in question, the caller is
    already known, and DW-72 is the reason it exists at all — this endpoint
    admits unlimited `current_password` guessing (it is not throttled, DW-40)
    and before Story 1.12 a run of guesses left no record anywhere. It is now
    the one place such a run is visible.

    DW-40 — "a second Argon2id-backed
    endpoint the gate cannot close" — becomes a third with this route: it costs
    one verify plus one hash per call, it is deliberately not throttled (Story
    1.6 is scoped to login by epics.md), and closing it is still a decision about
    what a counter would be keyed on.
    """
    response.headers.update(NO_STORE)

    row = conn.execute(_SELECT_PASSWORD_HASH, (user.id,)).fetchone()
    if row is None:
        # Deleted between the session lookup and this read. The session is gone
        # with it; saying so is the honest answer and the cookie goes too.
        raise not_signed_in()

    # First, and before anything is spent on the candidate. `InvalidHashError`
    # is left to propagate for the reason `set_password` leaves it: it means the
    # column holds something `shared_schema.passwords` did not write, such an
    # account cannot sign in at all so it cannot reach this line, and swallowing
    # it would let a corrupt digest be silently overwritten.
    if not verify_password(row["password_hash"], payload.current_password):
        # DW-72: unlimited guessing at this field, and until now no record of
        # it anywhere. Written on the autocommit connection — nothing was
        # changed, so there is no transaction for it to belong to — and it
        # still fails the request if it cannot be written, because a guess
        # that left no trace is the whole defect.
        #
        # The submitted password is **not** recorded, in any form. The address
        # a failed *sign-in* submits is, because there nothing else identifies
        # the attempt; here the actor is already named by their session.
        audit.record(
            conn,
            action=AuditAction.PASSWORD_CHANGE_REFUSED,
            actor_id=user.id,
            actor_email=user.email,
            target_id=user.id,
            target_email=user.email,
            source_ip=source_ip,
            details={"reason": REASON_WRONG_PASSWORD},
        )
        raise _invalid_current_password()

    # The length rules, in their one statement (`shared_schema.passwords`). This
    # is also where an empty or oversized candidate is answered — the request
    # model deliberately bounds neither, so that both get the sentence naming the
    # rule rather than a generic 422.
    violation = password_rule_violation(payload.new_password)
    if violation is not None:
        raise _weak_password(violation)

    # The twin of `PASSWORD_REUSES_TEMPORARY`, and it costs nothing extra: the
    # current password has just been proved correct against the stored digest, so
    # a plain string comparison against it is equivalent to a second verify and
    # spends no hash. A history rule — "not any of your last five" — is
    # deliberately not here: that needs a history table, a retention policy and a
    # decision about how many, none of which this epic asks for.
    if payload.new_password == payload.current_password:
        raise _weak_password(PASSWORD_UNCHANGED)

    # Hashed before the transaction opens. ~100ms of CPU inside an open
    # transaction is ~100ms of held row locks on `users` for no benefit.
    new_hash = hash_password(payload.new_password)

    with conn.transaction():
        user_row = conn.execute(_CHANGE_PASSWORD, (new_hash, user.id)).fetchone()
        if user_row is None:
            # `AND NOT must_change_password` matched nothing. Exactly two things
            # produce that, and they are different answers: the row is gone, or
            # an Administrator reissued a temporary credential in the
            # microseconds since the gate ran. One re-read tells them apart, and
            # neither writes — the transaction unwinds having done nothing.
            if conn.execute(_SELECT_ROW_EXISTS, (user.id,)).fetchone() is None:
                raise not_signed_in()
            # The row is still there, so `AND NOT must_change_password` is what
            # refused it: the account is back on a temporary credential and
            # belongs on `POST /auth/password`. That is an inference from the
            # predicate, not a second reading of the flag — see
            # `_SELECT_ROW_EXISTS` for why re-reading it would answer a different
            # question than the one being asked.
            raise _password_change_required()
        # The password may be being changed *because* somebody else has it. Every
        # session of this user goes with it, in the same transaction as the digest
        # — a device left signed in is exactly what the user is trying to close.
        revoked = delete_sessions_for_user(conn, user.id)
        # Issued inside the same transaction, so the caller is never left holding
        # a revoked cookie: either the whole change lands or none of it does.
        raw_token = issue_session(conn, user.id)
        # `set_password`'s two entries, for the same two events. `user_row`
        # rather than `user`, so the snapshot is read back from the write.
        audit.record(
            conn,
            action=AuditAction.PASSWORD_CHANGED,
            actor_id=user_row["id"],
            actor_email=user_row["email"],
            target_id=user_row["id"],
            target_email=user_row["email"],
            source_ip=source_ip,
        )
        audit.record(
            conn,
            action=AuditAction.SESSIONS_REVOKED,
            actor_id=user_row["id"],
            actor_email=user_row["email"],
            target_id=user_row["id"],
            target_email=user_row["email"],
            source_ip=source_ip,
            details={"cause": CAUSE_PASSWORD_WRITTEN, "count": revoked},
        )

    # The token leaves in the cookie and nowhere else (AGENTS.md Policy, AD-3).
    set_session_cookie(response, raw_token)

    return User.model_validate(user_row)
