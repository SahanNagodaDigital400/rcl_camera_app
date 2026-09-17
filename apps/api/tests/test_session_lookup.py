"""`GET /auth/session` — the one shared lookup, and what it refuses.

AD-3's rule has two halves. The first is that sessions live in Postgres and are
validated in one place; the second, and the one a test can actually pin, is
that `role` and `active` are **re-read on every request**. The last test in
this file is that property: an Administrator changes a row in Postgres and the
very next request reflects it, with no new login. Cache either value at login
and everything else here still passes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from api.sessions import (
    SESSION_ABSOLUTE_LIFETIME,
    SESSION_COOKIE_NAME,
    SESSION_IDLE_TIMEOUT,
    hash_token,
    lookup_session,
)
from fastapi.testclient import TestClient
from shared_schema.user import Role

LOGIN = "/auth/login"
SESSION = "/auth/session"

MakeUser = Callable[..., Any]


def _sign_in(client: TestClient, account: Any) -> str:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200
    return client.cookies[SESSION_COOKIE_NAME]


def test_a_signed_in_caller_reads_their_own_user(client: TestClient, make_user: MakeUser) -> None:
    account = make_user(name="Nadeesha Silva")
    _sign_in(client, account)

    response = client.get(SESSION)

    assert response.status_code == 200
    assert response.json()["email"] == account.email
    assert response.json()["name"] == "Nadeesha Silva"


def test_no_cookie_is_not_signed_in(client: TestClient) -> None:
    response = client.get(SESSION)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    # RFC 9110 requires a challenge on a 401. `Session`, not `Basic`: a `Basic`
    # challenge opens the browser's own credential dialog over this app's
    # login screen, which is both a worse experience and a phishing surface.
    assert response.headers["www-authenticate"] == 'Session realm="rocell"'


def test_the_challenge_rides_alongside_the_cookie_clearance(client: TestClient) -> None:
    # Two headers on one response, built from two different places. Adding the
    # challenge with `=` rather than merging would have dropped the clearance.
    client.cookies.set(SESSION_COOKIE_NAME, "stale")

    response = client.get(SESSION)

    assert response.headers["www-authenticate"] == 'Session realm="rocell"'
    assert response.headers["set-cookie"].startswith(f"{SESSION_COOKIE_NAME}=")


def test_an_unknown_token_is_not_signed_in(client: TestClient, make_user: MakeUser) -> None:
    # A token that was never issued must not be distinguishable from one that
    # expired: both are simply "no session".
    make_user()
    client.cookies.set(SESSION_COOKIE_NAME, "not-a-token-this-service-ever-issued")

    assert client.get(SESSION).status_code == 401


def test_a_stale_cookie_is_cleared_on_the_way_out(client: TestClient) -> None:
    # A cookie the server no longer honours costs a lookup on every request and
    # leaves the user holding a credential the product has forgotten.
    client.cookies.set(SESSION_COOKIE_NAME, "stale")

    response = client.get(SESSION)

    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "Max-Age=0" in header or "max-age=0" in header.lower()


def test_an_expired_row_is_rejected(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    raw = _sign_in(client, account)

    conn.execute(
        "UPDATE sessions SET expires_at = now() - interval '1 second' WHERE token_hash = %s",
        (hash_token(raw),),
    )

    assert client.get(SESSION).status_code == 401


def test_a_deactivated_owner_loses_a_live_session(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AGENTS.md Policy: deactivating a user must never leave a session live —
    # revoked immediately, not merely blocked at the next login.
    account = make_user()
    _sign_in(client, account)
    assert client.get(SESSION).status_code == 200

    conn.execute("UPDATE users SET active = false WHERE id = %s", (account.id,))

    assert client.get(SESSION).status_code == 401


def test_deleting_a_user_takes_their_sessions_with_them(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The ON DELETE CASCADE on sessions.user_id, from the other side: no
    # orphaned row survives to be looked up.
    account = make_user()
    _sign_in(client, account)

    conn.execute("DELETE FROM users WHERE id = %s", (account.id,))

    remaining = conn.execute(
        "SELECT count(*) AS n FROM sessions WHERE user_id = %s", (account.id,)
    ).fetchone()
    assert remaining is not None
    assert remaining["n"] == 0
    assert client.get(SESSION).status_code == 401


def test_a_role_change_takes_effect_on_the_very_next_request(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The AD-3 property that matters. Nothing is cached at login, so FR-12's
    # role edit lands without the user signing in again.
    account = make_user(role=Role.STAFF)
    _sign_in(client, account)
    assert client.get(SESSION).json()["role"] == Role.STAFF.value

    conn.execute("UPDATE users SET role = %s WHERE id = %s", (Role.ADMIN.value, account.id))

    assert client.get(SESSION).json()["role"] == Role.ADMIN.value


def test_the_lookup_reads_the_row_rather_than_the_token(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # `lookup_session` called directly, with no HTTP in the way: the shared
    # function is what every future authenticated route will use, so it has to
    # hold up on its own.
    account = make_user()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, now() + %s)",
        (account.id, hash_token("a-raw-token"), timedelta(days=1)),
    )

    assert lookup_session(conn, "a-raw-token") is not None
    assert lookup_session(conn, "another-raw-token") is None
    assert lookup_session(conn, None) is None
    assert lookup_session(conn, "") is None


def test_the_lookup_refuses_a_row_that_has_already_expired(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (account.id, hash_token("expired-token"), datetime.now(UTC) - timedelta(seconds=1)),
    )

    assert lookup_session(conn, "expired-token") is None


def test_the_lookup_refuses_a_row_idle_past_the_window(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The second of a session's two bounds (Story 1.5). `expires_at` is days
    # away and the owner is active, so the idle condition is the only thing
    # that can refuse this row.
    account = make_user()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at, last_seen_at) "
        "VALUES (%s, %s, now() + %s, now() - %s)",
        (
            account.id,
            hash_token("idle-token"),
            SESSION_ABSOLUTE_LIFETIME,
            SESSION_IDLE_TIMEOUT + timedelta(minutes=1),
        ),
    )

    assert lookup_session(conn, "idle-token") is None


def test_the_lookup_returns_exactly_the_user_contract_and_nothing_else(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # `_SELECT_SESSION` selects two columns that are not `User` fields —
    # `session_id` and `needs_touch` — so the lookup can decide whether to
    # slide the window without a second read of the table (AD-3). `User` is
    # `extra="forbid"`: leave either on the row and every authenticated request
    # in the product raises. Asserted over the keys rather than by catching an
    # error, so a *third* column added later is caught by name.
    account = make_user()
    _sign_in(client, account)

    user = lookup_session(conn, client.cookies[SESSION_COOKIE_NAME])

    assert user is not None
    assert set(user.model_dump().keys()) == {
        "id",
        "name",
        "email",
        "role",
        "active",
        "must_change_password",
        "temp_credential_expires_at",
        "last_login_at",
        "created_at",
        "updated_at",
    }
