"""`POST /auth/logout` — revoking one session, and only that one.

Signing out on a phone must not sign the same person out of the desktop they
left open in the back office. Revoking *every* session of a user is Story 1.5's
job and is not what this endpoint does.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg
from api.sessions import SESSION_COOKIE_NAME, hash_token
from fastapi.testclient import TestClient

LOGIN = "/auth/login"
LOGOUT = "/auth/logout"
SESSION = "/auth/session"

MakeUser = Callable[..., Any]


def _sign_in(client: TestClient, account: Any) -> str:
    assert (
        client.post(LOGIN, json={"email": account.email, "password": account.password}).status_code
        == 200
    )
    return client.cookies[SESSION_COOKIE_NAME]


def test_logging_out_deletes_the_row(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    raw = _sign_in(client, account)

    response = client.post(LOGOUT)

    assert response.status_code == 204
    assert not response.content
    remaining = conn.execute(
        "SELECT count(*) AS n FROM sessions WHERE token_hash = %s", (hash_token(raw),)
    ).fetchone()
    assert remaining is not None
    assert remaining["n"] == 0


def test_logging_out_clears_the_cookie(client: TestClient, make_user: MakeUser) -> None:
    account = make_user()
    _sign_in(client, account)

    header = client.post(LOGOUT).headers["set-cookie"]

    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "max-age=0" in header.lower()
    # The clearance carries the same attributes as the cookie it replaces: a
    # deletion written with a different Path leaves the original in place.
    assert "httponly" in header.lower()
    assert "secure" in header.lower()
    assert "path=/" in header.lower()


def test_the_session_stops_working_immediately(client: TestClient, make_user: MakeUser) -> None:
    account = make_user()
    raw = _sign_in(client, account)
    client.post(LOGOUT)

    # Re-presenting the token the browser was just told to forget.
    client.cookies.set(SESSION_COOKIE_NAME, raw)

    assert client.get(SESSION).status_code == 401


def test_logging_out_is_idempotent(client: TestClient, make_user: MakeUser) -> None:
    account = make_user()
    _sign_in(client, account)

    assert client.post(LOGOUT).status_code == 204
    assert client.post(LOGOUT).status_code == 204


def test_logging_out_without_a_cookie_is_still_204(client: TestClient) -> None:
    # Nothing to revoke is not an error, and answering 401 here would tell a
    # caller whether their cookie was real.
    assert client.post(LOGOUT).status_code == 204


def test_other_sessions_of_the_same_user_survive(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    first = _sign_in(client, account)
    client.cookies.clear()
    second = _sign_in(client, account)

    # Sign out of the second only.
    client.post(LOGOUT)

    rows = conn.execute(
        "SELECT token_hash FROM sessions WHERE user_id = %s", (account.id,)
    ).fetchall()
    assert [row["token_hash"] for row in rows] == [hash_token(first)]
    assert hash_token(second) not in [row["token_hash"] for row in rows]


def test_another_users_session_is_untouched(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    mine = make_user()
    theirs = make_user()
    _sign_in(client, theirs)
    client.cookies.clear()
    _sign_in(client, mine)

    client.post(LOGOUT)

    remaining = conn.execute(
        "SELECT count(*) AS n FROM sessions WHERE user_id = %s", (theirs.id,)
    ).fetchone()
    assert remaining is not None
    assert remaining["n"] == 1
