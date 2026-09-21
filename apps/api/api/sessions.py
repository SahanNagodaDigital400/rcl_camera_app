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

**A session is bounded twice** (Story 1.5, FR-3), and the two bounds are two
different columns on purpose:

* `SESSION_ABSOLUTE_LIFETIME` — 7 days, read from `issued_at`, which is written
  once at INSERT and updated by nothing in the product. No amount of activity
  moves it.
* `SESSION_IDLE_TIMEOUT` — 12 hours since the last authenticated request, read
  from `last_seen_at`, which `lookup_session` slides forward as a side effect
  of authenticating (throttled by `SESSION_TOUCH_INTERVAL`).

Keeping them apart is the security property, not a stylistic choice: the
renewal path writes `last_seen_at` and can therefore never extend the ceiling.
See the migration `20260917T1400_track_session_activity.up.sql`.

**Not in scope here.** *Session listing* — showing a user which devices hold a
session — is in no story at all. *Administrator-initiated revocation* is not a
surface either: Story 1.11's deactivation ends every session of a user through
`sessions.user_id`'s `ON DELETE CASCADE` and the `u.active` condition below,
which is what AGENTS.md Policy requires, and no story asks for more.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta
from uuid import UUID

# Imported for real rather than under `TYPE_CHECKING`: the renewal below
# catches `psycopg.Error`, which is a runtime reference, not an annotation.
import psycopg
from shared_schema.user import User
from starlette.responses import Response

#: Named as `api.auth`'s is — an explicit `rocell.` prefix rather than
#: `__name__` — so the two auth-path loggers sit under one parent and a
#: deployment can filter or raise the level of both with one rule.
logger = logging.getLogger("rocell.api.sessions")

#: The cookie's name. Prefixed so it cannot collide with anything else served
#: from the same origin, and deliberately not `session`, which every framework
#: in existence also calls its cookie.
SESSION_COOKIE_NAME = "rocell_session"

#: 32 bytes — 256 bits — of CSPRNG output, URL-safe so it needs no encoding on
#: the way into a cookie.
TOKEN_BYTES = 32

#: The absolute bound from the brief's security addendum: a session older than
#: this is rejected however active its owner has been. One of **two** bounds —
#: `SESSION_IDLE_TIMEOUT` below is the other — and the one measured from
#: `issued_at`, the column nothing ever updates.
SESSION_ABSOLUTE_LIFETIME = timedelta(days=7)

#: The idle bound from FR-3: a session unused for this long stops working even
#: though its absolute ceiling is days away. 12 hours is the figure the
#: requirement names, and the shape it is chosen for is a shop-floor shift —
#: long enough that nobody is signed out mid-shift or between a morning and an
#: afternoon of the same day, short enough that a phone left in a drawer on
#: Friday is not a live credential on Monday.
SESSION_IDLE_TIMEOUT = timedelta(hours=12)

#: How stale `last_seen_at` has to be before authenticating writes it again.
#:
#: Without a throttle every authenticated request is a write, which for a scan
#: -heavy PWA turns a read path into one `UPDATE` per request and one dead
#: tuple per request behind it. With it, the cost is bounded to one write a
#: minute per active session.
#:
#: A minute is two orders of magnitude below the 12-hour window it protects, so
#: the error it introduces — a session can die up to `SESSION_TOUCH_INTERVAL`
#: early — is 0.14% of that window and invisible to anyone. Raising it towards
#: the window itself is what would be wrong: at an interval close to 12 hours a
#: user active throughout could still be signed out.
SESSION_TOUCH_INTERVAL = timedelta(minutes=1)

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

#: The one authenticated read in the product. Every condition is in SQL so none
#: of them can be forgotten by a caller:
#:
#:   s.expires_at > now()            the row's own deadline, enforced by the
#:                                   database clock rather than the
#:                                   application's
#:   s.issued_at + %s > now()        the **absolute** bound, read from the
#:                                   immutable column rather than from
#:                                   `expires_at`. Belt and braces with the
#:                                   line above today, because `issue_session`
#:                                   writes `expires_at = now() + 7 days` — and
#:                                   deliberately so: this is the condition the
#:                                   renewal path cannot reach, whatever a
#:                                   later change does to `expires_at`.
#:   s.last_seen_at > now() - %s     the **idle** bound. This is the one
#:                                   activity slides, and the only one.
#:   u.active                        a deactivated user's live session stops
#:                                   working on the next request (AGENTS.md
#:                                   Policy, FR-13)
#:
#: `role` comes back from this query every time. Nothing is cached at login.
#:
#: `u.locked_until` is selected because `User` carries it (FR-4's admin-facing
#: status) and this model is `extra="forbid"` — a column missing here is a 500
#: on every authenticated request, not a missing field. It is **not** a
#: condition: a live session is not ended by a lockout. FR-4 blocks *attempts*;
#: Story 1.11's deactivation is what ends sessions, and `api.throttle` reads
#: `login_attempts` rather than this column for every decision it makes.
#:
#: The two trailing columns are not `User` fields and must not reach it —
#: `User` is `extra="forbid"`. `lookup_session` pops them off the row. They are
#: here rather than in a second query because AD-3 permits exactly one read of
#: this table, and because deciding "does this need a touch" in SQL uses the
#: database clock the bounds above are already measured against.
_SELECT_SESSION = """
SELECT u.id, u.name, u.email, u.role, u.active, u.must_change_password,
       u.temp_credential_expires_at, u.last_login_at, u.locked_until,
       u.created_at, u.updated_at,
       s.id AS session_id,
       (s.last_seen_at <= now() - %s) AS needs_touch
  FROM sessions s
  JOIN users u ON u.id = s.user_id
 WHERE s.token_hash = %s
   AND s.expires_at > now()
   AND s.issued_at + %s > now()
   AND s.last_seen_at > now() - %s
   AND u.active
"""

#: Slide the idle window forward. Not a counter, and therefore not AD-8's
#: read-then-write: `last_seen_at = now()` depends on nothing that was read, so
#: two concurrent touches write near-identical values and losing one entirely
#: costs a window extended a minute later. AD-8's `UPDATE ... RETURNING` rule
#: exists for values derived from their own previous state, where a lost update
#: is a correctness bug.
#:
#: Folding this into `_SELECT_SESSION` as an `UPDATE ... RETURNING` would write
#: on *every* authenticated request — a statement cannot conditionally skip its
#: own write and still return the row — which is exactly the cost
#: `SESSION_TOUCH_INTERVAL` exists to avoid.
#:
#: **Every liveness condition is re-asserted here.** The row is read and then
#: written in two statements, so it can die in between — expire, be revoked by
#: a sign-in elsewhere, or go idle under a clock skew. Without these the touch
#: would resurrect it: `last_seen_at = now()` on an idle-dead row makes the
#: next request succeed. With them the `UPDATE` matches nothing and the next
#: request is the 401 it should have been. `u.active` is not repeated because
#: this statement touches `sessions` alone and a deactivated owner is refused
#: by the SELECT on every request regardless.
_TOUCH_SESSION = """
UPDATE sessions
   SET last_seen_at = now()
 WHERE id = %s
   AND expires_at > now()
   AND issued_at + %s > now()
   AND last_seen_at > now() - %s
"""

_DELETE_SESSION = "DELETE FROM sessions WHERE token_hash = %s"

#: Every session a user holds, on any device. Two callers, and only two — the
#: forced password change and Story 1.11's deactivation. See
#: `delete_sessions_for_user`.
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
#: slot out again. That `UPDATE` has now arrived — `_TOUCH_SESSION` above runs
#: on most authenticated requests — so the hazard this note predicted is live,
#: and the primary-key form stays for exactly the reason it was chosen.
#:
#: **Both** deaths are swept, because both make a row unreachable: past its
#: absolute expiry, or idle longer than the window. A row that is idle-dead
#: but not yet absolutely expired would otherwise sit in the table for the
#: remainder of its seven days with nothing able to use it.
#:
#: That `OR` costs the `sessions_expires_at_idx`: a disjunction across two
#: columns, only one of which is indexed, is a sequential scan. The `LIMIT`
#: does not rescue it — it bounds the rows returned, not the rows read, so on
#: a sweep that finds little this reads the whole table. Accepted knowingly:
#: the table holds roughly one row per live session for an internal tool with
#: tens of staff, and it is swept on every sign-in so a backlog never builds.
#: The bet is on the row count. Measure it before adding an index on
#: `last_seen_at`, which would be paid on every touch instead.
_DELETE_EXPIRED = """
DELETE FROM sessions
 WHERE id IN (
     SELECT id
       FROM sessions
      WHERE expires_at <= now()
         OR last_seen_at <= now() - %s
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

    An absolutely-expired row, one idle past `SESSION_IDLE_TIMEOUT`, a revoked
    one and a deactivated owner are all `None` here rather than distinct
    outcomes: every caller's answer to any of them is the same 401, and a
    lookup that distinguished them would invite a route to explain the
    difference to the client.

    **Authenticating slides the idle window.** A successful lookup whose row
    has not been written for `SESSION_TOUCH_INTERVAL` writes `last_seen_at`
    forward, so a user working through a shift is never signed out. Only that
    column moves: the 7-day ceiling is read from `issued_at`, which nothing
    writes, so no amount of activity can push it.

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

    row = conn.execute(
        _SELECT_SESSION,
        (
            SESSION_TOUCH_INTERVAL,
            hash_token(raw_token),
            SESSION_ABSOLUTE_LIFETIME,
            SESSION_IDLE_TIMEOUT,
        ),
    ).fetchone()
    if row is None:
        return None

    # `User` is `extra="forbid"`, so the two bookkeeping columns cannot be left
    # on the row. `pop` rather than a comprehension: the row is a mutable
    # `dict` (`api.db` sets `dict_row`), and building a second one would be a
    # place for a column added later to be silently dropped.
    session_id = row.pop("session_id")
    if row.pop("needs_touch"):
        _touch_session(conn, session_id)

    return User.model_validate(row)


def _touch_session(conn: psycopg.Connection, session_id: UUID) -> None:
    """Slide one session's idle window forward. Never fails the request.

    The caller authenticated and the lookup succeeded; this is the tidy-up
    write that follows. A deadlock, a statement timeout or a read-only replica
    must not turn a valid request into a 500 — it fails in the safe direction,
    the window simply does not extend, and the session dies 12 hours after its
    last *successful* touch rather than living on untracked.

    Logged, because a touch that keeps failing is a product that signs everyone
    out at lunchtime with nothing in the API's logs to say why. `login`'s sweep
    established exactly this handling for exactly this reason.
    """
    try:
        conn.execute(
            _TOUCH_SESSION,
            (session_id, SESSION_ABSOLUTE_LIFETIME, SESSION_IDLE_TIMEOUT),
        )
    except psycopg.Error:
        logger.warning("session renewal failed; the request itself stands", exc_info=True)


def delete_session(conn: psycopg.Connection, raw_token: str | None) -> None:
    """Revoke one session. Deleting a token that is not there is not an error."""
    if not raw_token:
        return
    conn.execute(_DELETE_SESSION, (hash_token(raw_token),))


def delete_sessions_for_user(conn: psycopg.Connection, user_id: UUID) -> int:
    """Revoke every session this user holds, anywhere. Returns how many went.

    Revocation, not session management, and it has exactly two callers.

    **The forced password change** (`api.auth`), where the temporary credential
    the sessions were issued on has just stopped being trusted. A temporary
    credential travels by whatever channel an Administrator used — spoken,
    written on a note, messaged — so a session opened by someone who saw it has
    to go with it, including one on a device the user cannot reach. That is one
    user acting on their own account, in the same transaction that replaces
    their digest.

    **Story 1.11's deactivation** (`api.users.deactivate_user`), where an
    Administrator is taking somebody else's access away. This docstring used to
    predict that 1.11 would *not* need a function like this one — that `u.active`
    in `_SELECT_SESSION` and the `ON DELETE CASCADE` on `sessions.user_id` would
    be the whole of it — and that was half wrong. The `ON DELETE CASCADE` does
    carry a *delete*: the row goes and its sessions go with it, and
    `api.users.delete_user` calls nothing here. A *deactivation* has no cascade
    behind it, only a flag. `u.active` makes the target's very next request a
    `401` the instant the flag lands, which is FR-13's literal clause, but it
    leaves the rows in the table — and a later reactivation would bring every
    still-unexpired one of them back to life, handing back sessions the
    Administrator believed they had revoked. AGENTS.md line 18 says *revoke*,
    not *refuse*, so the deactivation deletes them here, in its own transaction,
    and reactivation has nothing to resurrect.

    Still not a session-management surface. Listing a user's sessions is in no
    story, and neither is revoking one of them: this ends all of them or none.
    """
    return conn.execute(_DELETE_USER_SESSIONS, (user_id,)).rowcount


def delete_expired_sessions(conn: psycopg.Connection, limit: int = EXPIRED_SWEEP_LIMIT) -> int:
    """Remove rows no session can be resumed from, up to `limit`. Returns how many went.

    Both deaths, not only the absolute one: a row past `expires_at` and a row
    idle longer than `SESSION_IDLE_TIMEOUT` are equally unusable, and sweeping
    only the first would leave an idle-dead row occupying the table for the
    rest of its seven days.

    `lookup_session` already refuses both, so this changes no behaviour — it
    keeps the table from growing without bound one dead row per sign-in. Called
    on the login path, where a row has just been added, and deliberately
    *outside* that path's transaction: holding a sweep's row locks until a
    sign-in commits is how two concurrent logins end up queueing behind each
    other.
    """
    return conn.execute(_DELETE_EXPIRED, (SESSION_IDLE_TIMEOUT, limit)).rowcount


def set_session_cookie(response: Response, raw_token: str) -> None:
    """Put the session token in the response's cookie, with every flag set.

    AGENTS.md Policy: HTTP-only, Secure, SameSite=Strict, and nowhere else —
    not in the response body, not in `localStorage`, not readable by page
    script.

    `max_age` is the **absolute** lifetime, not the idle window, and that is
    deliberate. The idle bound is a server-side condition on a row; the cookie's
    job is to keep presenting the token for as long as the session could still
    be alive. Setting `max_age` to 12 hours would have the browser discard a
    perfectly live session at noon on a day its owner used it all morning —
    every touch slides the row and nothing slides the cookie.
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
