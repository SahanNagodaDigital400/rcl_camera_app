"""The authorization dependencies every authenticated route is built from.

Two of them, and the difference between them is the whole of Story 1.4's gate:

* `current_user` — there is a usable session, so we know who this is. Says
  nothing about what they may do.
* `require_claimed_user` — `current_user`, and the account is *claimed*: its
  admin-issued temporary credential has already been exchanged for a real
  password. **Every route that serves real data declares this one.** AGENTS.md
  line 18: never grant further access on a temporary credential before the
  forced change.

**Why a dependency and a route-table test rather than middleware.** Middleware
would have to know which paths are exempt by matching strings, and three routes
*must* stay reachable while the flag is set: `GET /auth/session` is how the
front end learns to show the change screen at all, `POST /auth/logout` is how a
user leaves, and `POST /auth/password` is the change itself. A path list inside
middleware is a second copy of the routing table, and it drifts the day someone
adds a route. Declaring the requirement where the route is declared puts it
where it is read, and `tests/test_forced_change_gate.py` inverts it: the
allowlist is written down once, in a test, and everything else has to opt in.
That is what makes `lookup_session`'s obligation enforceable rather than
aspirational.

**Neither of these queries `sessions`.** Both go through
`api.sessions.lookup_session`, the one lookup AD-3 permits — which is also why
a role change or a deactivation takes effect on the very next request rather
than at the next sign-in. `tests/test_source_guards.py` enforces the absence of
a second query.

The 401 primitives live here rather than in `api.auth` because both modules
need them and `auth` imports this one: two copies of a `WWW-Authenticate`
challenge or a `no-store` header are two things that drift.
"""

from __future__ import annotations

from typing import Annotated

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a dependency's
# annotations at runtime to build its graph, so a name that exists only for the
# type checker fails at import with a bare NameError.
import psycopg
from fastapi import Cookie, Depends, Response, status
from shared_schema.errors import ApiError
from shared_schema.user import User

from api.db import get_connection
from api.sessions import SESSION_COOKIE_NAME, cleared_cookie_headers, lookup_session

#: The envelope code for "you are not signed in" — and, at `POST /auth/login`,
#: for "that credential is wrong". One code, because a client's answer to both
#: is the same: show the sign-in screen.
UNAUTHORIZED = "unauthorized"

#: Not signed in, as opposed to "these credentials are wrong". Distinct wording
#: because it is a distinct situation and no account is being probed by it: the
#: caller is a browser with no cookie, not someone guessing a password.
NO_SESSION = "Not signed in."

#: Every authenticated response carries a signed-in user's name, address and
#: role, and `GET /auth/session` is a plain GET — heuristically cacheable by any
#: intermediary and by the service worker this PWA will eventually ship. A
#: cached identity served to the next person on a shared shop-floor tablet is
#: the whole failure mode; `no-store` is what stops it being written down at
#: all.
#:
#: Applied by `current_user` itself, not only by the handlers that remember to:
#: a header most authenticated responses carry is a header the next one will be
#: written without.
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

#: The gate's own code. Distinct from `unauthorized` on purpose: the caller *is*
#: signed in, the cookie is good, and re-sending them to the login screen would
#: loop them straight back here.
#:
#: Nothing in `apps/web` branches on it yet, because no route declares the gate
#: yet — Story 1.4 adds no surface that serves real data. Its TypeScript twin
#: exists for the first gated surface, which Epic 2 brings, and the parity test
#: over the two spellings is what keeps them one code until then.
PASSWORD_CHANGE_REQUIRED = "password_change_required"

#: What the gate says. Names the one thing that clears it, in EXPERIENCE.md's
#: register — short, factual, no exclamation mark — because a client that is not
#: this app's front end has only this sentence to go on.
SET_A_PASSWORD_FIRST = "Set a new password before you can use the rest of the app."


def not_signed_in() -> ApiError:
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


def current_user(
    response: Response,
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    rocell_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """The signed-in `User`, re-read from Postgres on this request (AD-3).

    Raises the one 401 for every way a session can be unusable — no cookie, an
    unknown token, an expired row, a deactivated owner. `lookup_session` does
    not distinguish them and neither does this: the caller's answer to all four
    is to sign in again.

    Authorization is *not* decided here. This says who the caller is; what they
    may do is `require_claimed_user` below and, later, a role check.
    """
    # Set on the injected response, so every route built on this dependency is
    # uncacheable whether or not its handler remembered to say so. The error
    # path carries its own copy, because a raised `ApiError` is rendered by an
    # exception handler that never sees this object.
    response.headers.update(NO_STORE)

    user = lookup_session(conn, rocell_session)
    if user is None:
        raise not_signed_in()
    return user


def require_claimed_user(user: Annotated[User, Depends(current_user)]) -> User:
    """`current_user`, refused while the account is still on a temporary credential.

    **Every route that serves real data declares this** (AGENTS.md line 18).
    The exceptions are written down in `tests/test_forced_change_gate.py`'s
    allowlist with a reason each, and that test fails on any route outside it
    that does not declare this dependency — so the requirement is not a
    convention a future route can forget.

    `403`, not `401`: the session is valid and the credential is not in
    question. A 401 would send `apps/web` to the login screen, where signing in
    again returns the same flag and the same refusal.
    """
    if user.must_change_password:
        raise ApiError(
            PASSWORD_CHANGE_REQUIRED,
            SET_A_PASSWORD_FIRST,
            status_code=status.HTTP_403_FORBIDDEN,
            headers=NO_STORE,
        )
    return user
