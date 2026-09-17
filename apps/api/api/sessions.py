"""Sessions: the cookie, the rows behind it, and the one lookup AD-3 requires.

AD-3 fixes three things and this module is all three of them:

* sessions are **rows in Postgres**, not a second stateful dependency;
* they are validated through **one shared lookup function**, never a bespoke
  per-route check; and
* that lookup **re-reads `role` and `active` from Postgres on every call**, so a
  role change (FR-12) or a deactivation (FR-13) takes effect on the very next
  request rather than at the next login.

`lookup_session` is that function. Every authenticated route in the product —
Story 1.4's forced-change gate, every Epic 2 catalogue endpoint, every admin
screen — calls it and nothing else. A second implementation anywhere is the
divergence AD-3 names.

**Why SHA-256 here and Argon2id for passwords.** A password is low-entropy and
human-chosen, so it needs a deliberately slow KDF. A session token is 256 bits
of `secrets.token_urlsafe` output: there is no dictionary to run against it,
and the only thing hashing at rest buys is that a database read does not yield
usable cookies. A fast one-way digest does that completely, while Argon2id at
the pinned 64 MiB cost would be paid on *every authenticated request* instead
of once per login. Different threat, different primitive; both are one-way.

**Not in scope here.** Story 1.5 owns session lifetime behaviour — the 12-hour
idle window, sliding renewal, listing a user's sessions, bulk revocation. The
7-day absolute bound below is the only lifetime this story fixes, because a
session has to expire at *something* the day it is first issued.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from shared_schema.user import User
from starlette.responses import Response

if TYPE_CHECKING:  # pragma: no cover - typing only
    import psycopg

#: The cookie's name. Prefixed so it cannot collide with anything else served
#: from the same origin, and deliberately not `session`, which every framework
#: in existence also calls its cookie.
SESSION_COOKIE_NAME = "rocell_session"

#: 32 bytes — 256 bits — of CSPRNG output, URL-safe so it needs no encoding on
#: the way into a cookie.
TOKEN_BYTES = 32

#: The absolute bound from the brief's security addendum: a session older than
#: this is rejected however active its owner has been. The *idle* window is
#: Story 1.5's and is deliberately not implemented here.
SESSION_ABSOLUTE_LIFETIME = timedelta(days=7)

#: Cookie attributes, in one place so every response that sets or clears the
#: cookie agrees about them.
#:
#: `Secure` is mandated by AGENTS.md Policy without a development exemption.
#: Browsers treat `http://localhost` and `http://127.0.0.1` as trustworthy
#: origins, so the Vite dev proxy still works over plain HTTP (DW-4) — on the
#: development machine. A phone reaching that dev server across the LAN by IP
#: is not a trustworthy origin and will discard this cookie without a word, so
#: handset testing needs a real TLS origin; README.md says so where a developer
#: will look for it. Not a reason to drop the flag.
#: `SameSite=Strict` means the cookie is not sent on any cross-site navigation
#: — for an internal tool nobody links into from elsewhere, that costs nothing
#: and closes CSRF at the transport.
COOKIE_PATH = "/"
COOKIE_SAMESITE = "strict"

_INSERT_SESSION = """
INSERT INTO sessions (user_id, token_hash, expires_at)
VALUES (%s, %s, now() + %s)
"""

#: The one authenticated read in the product. Three conditions, all in SQL so
#: none of them can be forgotten by a caller:
#:
#:   s.expires_at > now()  the absolute bound, enforced by the database clock
#:                         rather than the application's
#:   u.active              a deactivated user's live session stops working on
#:                         the next request (AGENTS.md Policy, FR-13)
#:
#: `role` comes back from this query every time. Nothing is cached at login.
_SELECT_SESSION = """
SELECT u.id, u.name, u.email, u.role, u.active, u.must_change_password,
       u.temp_credential_expires_at, u.last_login_at, u.created_at, u.updated_at
  FROM sessions s
  JOIN users u ON u.id = s.user_id
 WHERE s.token_hash = %s
   AND s.expires_at > now()
   AND u.active
"""

_DELETE_SESSION = "DELETE FROM sessions WHERE token_hash = %s"

#: Every session a user holds, on any device. Used by the forced password
#: change and nothing else — see `delete_sessions_for_user`.
_DELETE_USER_SESSIONS = "DELETE FROM sessions WHERE user_id = %s"

#: How many dead rows one sign-in will clear. A sign-in adds one row, so any
#: bound above 1 drains a backlog rather than merely keeping pace; a bound at
#: all is what stops a single unlucky login paying to delete everything that
#: accumulated during an outage.
EXPIRED_SWEEP_LIMIT = 100

#: Bounded and lock-skipping, both on purpose. `FOR UPDATE SKIP LOCKED` means
#: two sign-ins arriving together take disjoint rows instead of one waiting on
#: the other's locks, and the `LIMIT` caps what any one of them pays for. The
#: `id IN (...)` form is what carries a LIMIT into a DELETE, which SQL has no
#: direct syntax for.
#:
#: Keyed on the primary key rather than on `ctid`. The `ctid` form is the one
#: usually reached for, and it is safe only while nothing ever `UPDATE`s a
#: session row: an update moves the tuple, so the ctid the subquery captured
#: names a different row by the time the DELETE runs — and VACUUM hands the
#: slot out again. Story 1.5 owns sliding renewal, which is exactly an
#: `UPDATE sessions SET expires_at = ...`, so the hazard is one story away and
#: the primary key costs nothing to use instead.
_DELETE_EXPIRED = """
DELETE FROM sessions
 WHERE id IN (
     SELECT id
       FROM sessions
      WHERE expires_at <= now()
      FOR UPDATE SKIP LOCKED
      LIMIT %s
 )
"""


def generate_token() -> str:
    """A fresh session token: 256 bits of CSPRNG output, URL-safe."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    """The value stored in `sessions.token_hash` for a given cookie value.

    SHA-256, hex-encoded. See the module docstring for why this is not Argon2id.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_session(conn: psycopg.Connection, user_id: UUID) -> str:
    """Create a session row for `user_id` and return the raw token for the cookie.

    The raw token is returned and never stored: what lands in the table is its
    digest, so a database read yields nothing that can be presented as a cookie.
    """
    raw_token = generate_token()
    conn.execute(_INSERT_SESSION, (user_id, hash_token(raw_token), SESSION_ABSOLUTE_LIFETIME))
    return raw_token


def lookup_session(conn: psycopg.Connection, raw_token: str | None) -> User | None:
    """The one session lookup in the service (AD-3). `None` means not signed in.

    `role` and `active` come from this query, not from anything recorded when
    the session was issued — that is the whole point of the rule, and it is why
    an Administrator's edit takes effect on the next request.

    An expired row and a deactivated owner are both `None` here rather than
    distinct outcomes: every caller's answer to either is the same 401, and a
    lookup that distinguished them would invite a route to explain the
    difference to the client.

    **A `User` this returns may still carry `must_change_password = true`**, and
    that is deliberate: login issues a session for an unclaimed temporary
    credential, and `GET /auth/session` reporting the flag is how `apps/web`
    learns to show the forced-change screen at all. Gating it here would break
    that endpoint, so the gate is one layer up.

    That gate is `api.dependencies.require_claimed_user` (Story 1.4), and it is
    the thing every route serving real data declares — AGENTS.md Policy: never
    grant further access on an admin-issued temporary credential before the
    forced change. The obligation is not left to whoever reads this docstring:
    `tests/test_forced_change_gate.py` walks `create_app()`'s route table and
    fails on any route outside a written-down allowlist that does not declare
    it, so a route added later cannot serve an unclaimed account by omission.
    """
    if not raw_token:
        return None

    row = conn.execute(_SELECT_SESSION, (hash_token(raw_token),)).fetchone()
    return None if row is None else User.model_validate(row)


def delete_session(conn: psycopg.Connection, raw_token: str | None) -> None:
    """Revoke one session. Deleting a token that is not there is not an error."""
    if not raw_token:
        return
    conn.execute(_DELETE_SESSION, (hash_token(raw_token),))


def delete_sessions_for_user(conn: psycopg.Connection, user_id: UUID) -> int:
    """Revoke every session this user holds, anywhere. Returns how many went.

    Credential rotation, not session management. It exists for one caller: the
    forced password change, where the temporary credential the sessions were
    issued on has just stopped being trusted. A temporary credential travels by
    whatever channel an Administrator used — spoken, written on a note,
    messaged — so a session opened by someone who saw it has to go with it,
    including one on a device the user cannot reach.

    Story 1.5 owns session *management*: listing a user's sessions, sliding
    renewal, an Administrator revoking someone else's. This is neither of
    those; it is one user, acting on their own account, in the same transaction
    that replaces their digest.
    """
    return conn.execute(_DELETE_USER_SESSIONS, (user_id,)).rowcount


def delete_expired_sessions(conn: psycopg.Connection, limit: int = EXPIRED_SWEEP_LIMIT) -> int:
    """Remove rows past their absolute expiry, up to `limit`. Returns how many went.

    `lookup_session` already refuses an expired row, so this changes no
    behaviour — it keeps the table from growing without bound one dead row per
    sign-in. Called on the login path, where a row has just been added, and
    deliberately *outside* that path's transaction: holding a sweep's row locks
    until a sign-in commits is how two concurrent logins end up queueing behind
    each other.
    """
    return conn.execute(_DELETE_EXPIRED, (limit,)).rowcount


def set_session_cookie(response: Response, raw_token: str) -> None:
    """Put the session token in the response's cookie, with every flag set.

    AGENTS.md Policy: HTTP-only, Secure, SameSite=Strict, and nowhere else —
    not in the response body, not in `localStorage`, not readable by page
    script.
    """
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=int(SESSION_ABSOLUTE_LIFETIME.total_seconds()),
        path=COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite=COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response) -> None:
    """Expire the session cookie in the browser.

    The same attribute set as `set_session_cookie`: a cookie is identified by
    name, domain and path, so a deletion written with a different `Path` leaves
    the original in place and the user stays signed in with a token the server
    has already forgotten.
    """
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite=COOKIE_SAMESITE,
    )


def cleared_cookie_headers() -> dict[str, str]:
    """`clear_session_cookie` as a header dict, for an error that is raised.

    `ApiError` is rendered by an exception handler that builds its own response,
    so a cookie set on the injected `Response` never reaches the client. The
    headers ride on the error instead — built through the same helper above, so
    the attributes cannot drift between the two paths.
    """
    probe = Response()
    clear_session_cookie(probe)
    return {"set-cookie": probe.headers["set-cookie"]}
