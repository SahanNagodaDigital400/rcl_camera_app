"""`POST /auth/login`, `GET /auth/session`, `POST /auth/logout`.

The whole of Story 1.3's HTTP surface. Three things about it are load-bearing:

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

**Not here.** Failed-attempt counters, progressive delay and lockout are Story
1.6 over AD-8's Postgres counters — this file adds none of them. The forced
password change is Story 1.4: login *issues* a session for a
`must_change_password` user and reports the flag; gating on it is 1.4's. And
none of this is audited yet — AGENTS.md Policy requires the append-only audit
log to cover logins, and that log arrives with Story 1.12, which owes this
endpoint its entries. Until then a sign-in leaves only `last_login_at` behind.
"""

from __future__ import annotations

import logging
from typing import Annotated

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a handler's
# annotations at runtime to build its dependency graph, so a name that exists
# only for the type checker fails at import with a bare NameError.
import psycopg
from argon2.exceptions import InvalidHashError
from fastapi import APIRouter, Cookie, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field
from shared_schema.errors import ApiError
from shared_schema.passwords import MAX_PASSWORD_LENGTH, verify_dummy_password, verify_password
from shared_schema.user import User

from api.db import get_connection
from api.sessions import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    cleared_cookie_headers,
    delete_expired_sessions,
    delete_session,
    issue_session,
    lookup_session,
    set_session_cookie,
)

logger = logging.getLogger("rocell.api.auth")

router = APIRouter(tags=["auth"])

#: The one thing a rejected sign-in is ever told. It names neither the field
#: that was wrong nor whether the account exists — EXPERIENCE.md's State
#: Patterns make that explicit for a deactivated account, and the same silence
#: covers the other three states.
INVALID_CREDENTIALS = "Email or password is incorrect."

UNAUTHORIZED = "unauthorized"

#: Not signed in, as opposed to "these credentials are wrong". Distinct wording
#: because it is a distinct situation and no account is being probed by it: the
#: caller is a browser with no cookie, not someone guessing a password.
NO_SESSION = "Not signed in."

#: The longest address the endpoint will look at. Longer than RFC 5321's 254,
#: so it refuses only what is certainly not an address, and short enough that
#: the lookup is never handed a megabyte to index.
MAX_EMAIL_LENGTH = 320

#: Both success responses carry a signed-in user's name, address and role, and
#: `GET /auth/session` is a plain GET — heuristically cacheable by any
#: intermediary and by the service worker this PWA will eventually ship. A
#: cached identity served to the next person on a shared shop-floor tablet is
#: the whole failure mode; `no-store` is what stops it being written down at
#: all.
#:
#: Carried by every auth response, not only the two that return a body. A
#: rejection and a logout both say something about who is *not* signed in here
#: any more, a 204 is cacheable by default, and — the reason that outlasts the
#: others — a header three of five responses carry is a header the sixth will
#: be written without.
NO_STORE = {"cache-control": "no-store"}

#: RFC 9110 requires a `WWW-Authenticate` challenge on a 401, and both
#: `shared_schema.errors.ApiError` and `api.main`'s handlers exist partly to
#: carry it. `Session` rather than `Basic`: a `Basic` challenge makes the
#: browser open its own credential dialog over this app's login screen, which
#: is a worse experience *and* a phishing surface. No browser acts on an
#: unknown scheme, which is exactly what is wanted — the scheme names how to
#: authenticate for a client that reads it, and changes nothing for one that
#: does not.
AUTH_CHALLENGE = {"WWW-Authenticate": 'Session realm="rocell"'}

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
          temp_credential_expires_at, last_login_at, created_at, updated_at
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


def _not_signed_in() -> ApiError:
    """No usable session. Carries the cookie clearance so a stale one goes.

    A cookie the server no longer honours is worse than no cookie: the browser
    keeps sending it, every request costs a lookup that can only fail, and the
    user sees a sign-in screen while holding a credential. It is cleared on the
    way out.
    """
    return ApiError(
        UNAUTHORIZED,
        NO_SESSION,
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={**AUTH_CHALLENGE, **NO_STORE, **cleared_cookie_headers()},
    )


@router.post("/auth/login", response_model=User)
def login(
    payload: LoginRequest,
    response: Response,
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    rocell_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Verify a credential, issue a session, and return the signed-in `User`.

    Defined as `def`, not `async def`: psycopg is a synchronous driver and
    Argon2id verification is CPU-bound for ~100ms. FastAPI runs a sync endpoint
    in its threadpool, so neither blocks the event loop; an `async def` around
    the same calls would block every other request in the process.
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
        verify_dummy_password(payload.password)
        raise _rejected()

    row = conn.execute(_SELECT_CREDENTIAL, (email,)).fetchone()

    if row is None:
        # No account: spend the same Argon2id work a real verify would, so the
        # response time does not tell the caller the address is unknown (DW-24).
        verify_dummy_password(payload.password)
        raise _rejected()

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
        raise _rejected() from None

    if not verified:
        raise _rejected()

    # Both checks below come *after* a real verify, so they cost the same as a
    # wrong password by construction — no decoy is needed on these two paths.
    if not row["active"]:
        raise _rejected()

    # AGENTS.md Policy gives an admin-issued temporary credential 72 hours,
    # without exception, and this endpoint is the only place a credential is
    # ever presented. Leaving the check to Story 1.4 — which owns the
    # forced-change *screen* — would ship a window in which an expired
    # credential authenticates.
    if row["must_change_password"] and row["credential_expired"]:
        raise _rejected()

    with conn.transaction():
        user_row = conn.execute(_RECORD_LOGIN, (row["id"],)).fetchone()
        if user_row is None:
            # Deleted between the credential read and this write. Rare, and the
            # alternative is `User.model_validate(None)` raising a 500 after the
            # password has already been verified — an answer no other outcome of
            # this endpoint gives.
            raise _rejected()
        # The cookie this request arrived with is about to be overwritten, so
        # its row would otherwise stay live and unreachable for the rest of its
        # seven days: the browser can no longer present it, logout only revokes
        # the cookie it is given, and revoking a user's sessions in bulk is
        # Story 1.5's. Signing in again is the one moment the old token is still
        # in hand, so it is spent here. Not bulk revocation — this ends exactly
        # the session this browser was holding, and no other device is touched.
        delete_session(conn, rocell_session)
        raw_token = issue_session(conn, row["id"])

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
def read_session(
    response: Response,
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    rocell_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Who the caller is, re-read from Postgres on every call (AD-3).

    This is what makes a role change or a deactivation take effect on the very
    next request: nothing here trusts anything recorded when the session was
    issued.
    """
    response.headers.update(NO_STORE)

    user = lookup_session(conn, rocell_session)
    if user is None:
        raise _not_signed_in()
    return user


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    rocell_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Response:
    """End this session. Idempotent — a second call is still `204`.

    Only *this* session. Signing out on a phone must not sign the same person
    out of the desktop they left open in the back office; revoking every
    session of a user is Story 1.5's.

    Not named by Story 1.3's acceptance clauses and delivered anyway: issuing a
    session with no revocation path leaves clearing browser cookies as the only
    way out, `delete_session` is the counterpart of `issue_session` in the same
    module, and no later epic story delivers it.
    """
    delete_session(conn, rocell_session)

    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(NO_STORE))
    clear_session_cookie(response)
    return response
