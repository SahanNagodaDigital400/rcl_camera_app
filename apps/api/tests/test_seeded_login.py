"""The 1.2 → 1.3 composition: the seeded Administrator can actually sign in.

Story 1.3's acceptance clause opens "Given an account exists — either the
Administrator seeded in Story 1.2, or one an Administrator later created". Every
other test in this package creates its account with a direct `INSERT`, which
proves the endpoint and proves nothing about the seed. This file applies the
**full** migration set — `rocell_infra.seed` hashing the password through
`shared_schema.passwords`, exactly as `make migrate` does — and then signs in
through the HTTP endpoint.

That is the one thing the shared hashing module exists for: if the seed's
Argon2id parameters and the login verifier's ever drift, the seeded account
simply never works and nothing raises. This is what raises.

The credentials are generated at runtime and never leave the process. AGENTS.md
Policy forbids a committed credential in a fixture as firmly as in source.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import psycopg
import pytest
from api.db import DATABASE_URL
from api.main import create_app
from api.sessions import SESSION_COOKIE_NAME, hash_token
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from rocell_infra import migrate
from rocell_infra.config import SEED_ADMIN_EMAIL, SEED_ADMIN_NAME, SEED_ADMIN_PASSWORD
from shared_schema.passwords import MIN_PASSWORD_LENGTH
from shared_schema.user import Role

LOGIN = "/auth/login"
SESSION = "/auth/session"

SEEDED_EMAIL = "ops@rocell.lk"
SEEDED_NAME = "Rocell Operations"


@pytest.fixture
def seed_password(monkeypatch: pytest.MonkeyPatch) -> str:
    """The seeded Administrator's password, generated for this test alone."""
    password = secrets.token_urlsafe(32)[: MIN_PASSWORD_LENGTH + 12]
    monkeypatch.setenv(SEED_ADMIN_EMAIL, SEEDED_EMAIL)
    monkeypatch.setenv(SEED_ADMIN_PASSWORD, password)
    monkeypatch.setenv(SEED_ADMIN_NAME, SEEDED_NAME)
    return password


@pytest.fixture
def seeded_url(database_url: str, seed_password: str) -> str:
    """This test's database with **every** migration applied, seed included."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        applied = migrate.up(conn)

    # The whole shipped set, not a filtered plan: the point of this file is
    # that the seed migration ran.
    assert len(applied) == len(migrate.discover_migrations())
    return database_url


@pytest.fixture
def seeded_client(seeded_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(DATABASE_URL, seeded_url)
    with TestClient(create_app(), base_url="https://testserver") as client:
        yield client


@pytest.fixture
def seeded_conn(seeded_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(seeded_url, autocommit=True, row_factory=dict_row) as conn:
        yield conn


def test_the_seeded_administrator_signs_in(
    seeded_client: TestClient, seeded_conn: psycopg.Connection, seed_password: str
) -> None:
    response = seeded_client.post(LOGIN, json={"email": SEEDED_EMAIL, "password": seed_password})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == SEEDED_EMAIL
    assert body["name"] == SEEDED_NAME
    assert body["role"] == Role.ADMIN.value
    assert body["active"] is True
    # Story 1.4 gates on this. The seeded credential is an admin-issued
    # temporary one, so even the very first sign-in is unclaimed.
    assert body["must_change_password"] is True
    assert body["temp_credential_expires_at"] is not None
    # FR-4's status, on an account that has never failed a sign-in. Null rather
    # than absent: the key is part of the contract on every body, and Story
    # 1.9's user list reads it to decide whether to show "Locked".
    assert body["locked_until"] is None

    rows = seeded_conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert len(rows) == 1
    assert rows[0]["token_hash"] == hash_token(seeded_client.cookies[SESSION_COOKIE_NAME])


def test_the_seeded_credential_is_verified_through_the_shared_hasher(
    seeded_client: TestClient, seed_password: str
) -> None:
    # The failure this guards against is silent: if the seed's Argon2id
    # parameters and the verifier's drift apart, the account simply never
    # works. A near-miss password must be refused and the real one accepted,
    # against a digest this process did not write itself.
    wrong = seeded_client.post(LOGIN, json={"email": SEEDED_EMAIL, "password": seed_password + "x"})
    assert wrong.status_code == 401

    right = seeded_client.post(LOGIN, json={"email": SEEDED_EMAIL, "password": seed_password})
    assert right.status_code == 200


def test_the_seeded_administrator_reads_their_own_session(
    seeded_client: TestClient, seed_password: str
) -> None:
    seeded_client.post(LOGIN, json={"email": SEEDED_EMAIL, "password": seed_password})

    response = seeded_client.get(SESSION)

    assert response.status_code == 200
    assert response.json()["role"] == Role.ADMIN.value


def test_signing_in_records_the_seeded_administrators_last_login(
    seeded_client: TestClient, seeded_conn: psycopg.Connection, seed_password: str
) -> None:
    # FR-10, and the thing `20260917T1210_seed_administrator.down.sql` reads to
    # decide whether the account has been claimed.
    before = seeded_conn.execute("SELECT last_login_at FROM users").fetchone()
    assert before is not None
    assert before["last_login_at"] is None

    seeded_client.post(LOGIN, json={"email": SEEDED_EMAIL, "password": seed_password})

    after = seeded_conn.execute("SELECT last_login_at FROM users").fetchone()
    assert after is not None
    assert after["last_login_at"] is not None


def test_the_seeded_address_is_matched_whatever_case_it_is_typed_in(
    seeded_client: TestClient, seed_password: str
) -> None:
    response = seeded_client.post(
        LOGIN, json={"email": SEEDED_EMAIL.upper(), "password": seed_password}
    )

    assert response.status_code == 200
