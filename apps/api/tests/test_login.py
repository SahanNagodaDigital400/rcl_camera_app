"""`POST /auth/login` — the credential path, and the four identical rejections.

The rejection tests are the point of this file. Story 1.3's acceptance clause
is that a caller cannot tell an unknown address from a wrong password, and
EXPERIENCE.md extends that to a deactivated account; AGENTS.md adds the
72-hour ceiling on a temporary credential. Four code paths, one response —
asserted here field by field, including headers, because "they both return 401"
is exactly the level of similarity that lets a message drift apart later.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from api import auth
from api.auth import INVALID_CREDENTIALS
from api.sessions import (
    EXPIRED_SWEEP_LIMIT,
    SESSION_ABSOLUTE_LIFETIME,
    SESSION_COOKIE_NAME,
    hash_token,
)
from fastapi.testclient import TestClient
from shared_schema.passwords import ARGON2ID_PREFIX, MAX_PASSWORD_LENGTH
from shared_schema.user import Role

LOGIN = "/auth/login"

#: `conftest.make_user`, which returns a `conftest.Account`. A conftest is not
#: an importable module under pytest's importlib mode, so the factory is typed
#: by its shape rather than by that class.
MakeUser = Callable[..., Any]


def _sessions(conn: psycopg.Connection, user_id: Any) -> list[dict[str, Any]]:
    return conn.execute("SELECT * FROM sessions WHERE user_id = %s", (user_id,)).fetchall()


def _cookie_attributes(response: httpx.Response) -> str:
    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    return header


def test_a_correct_credential_signs_in(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user(name="Kasun Perera")

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == account.email
    assert body["name"] == "Kasun Perera"
    assert body["role"] == Role.STAFF.value
    assert len(_sessions(conn, account.id)) == 1


def test_the_address_is_matched_case_insensitively(client: TestClient, make_user: MakeUser) -> None:
    # `users.email` is stored lowercase and uniqueness is over `lower(email)`.
    # People do not type case consistently, and an address that works in one
    # casing and not another is indistinguishable from a wrong password.
    account = make_user()

    response = client.post(
        LOGIN, json={"email": account.email.upper(), "password": account.password}
    )

    assert response.status_code == 200


def test_surrounding_whitespace_in_the_address_is_ignored(
    client: TestClient, make_user: MakeUser
) -> None:
    # A phone keyboard's autocomplete appends a space more often than not.
    account = make_user()

    response = client.post(
        LOGIN, json={"email": f"  {account.email}  ", "password": account.password}
    )

    assert response.status_code == 200


def test_the_response_body_satisfies_the_shared_user_contract(
    client: TestClient, make_user: MakeUser
) -> None:
    account = make_user()

    body = client.post(LOGIN, json={"email": account.email, "password": account.password}).json()

    assert set(body) == {
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


def test_no_password_material_reaches_the_response(client: TestClient, make_user: MakeUser) -> None:
    # `password_hash` is absent from the shared `User` by construction, and
    # this is the one endpoint that reads the column. Asserted over the raw
    # text, not the parsed keys: a digest smuggled into any field would pass a
    # key-set check.
    account = make_user()

    text = client.post(LOGIN, json={"email": account.email, "password": account.password}).text

    assert ARGON2ID_PREFIX not in text
    assert "password_hash" not in text
    assert account.password not in text


def test_the_session_cookie_carries_every_required_flag(
    client: TestClient, make_user: MakeUser
) -> None:
    account = make_user()

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    header = _cookie_attributes(response).lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=strict" in header
    assert "path=/" in header
    # The *value*, not just the attribute. `max-age=` alone passes for
    # `Max-Age=7`, which expires the cookie seconds after sign-in while the row
    # behind it stays valid for a week: the browser stops sending a session the
    # server is still honouring, and the only symptom is staff bounced to the
    # login screen for no reason the server can see.
    assert f"max-age={int(SESSION_ABSOLUTE_LIFETIME.total_seconds())}" in header


def test_the_cookie_value_is_not_what_is_stored(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The whole point of hashing at rest: a database read must not yield a
    # usable cookie.
    account = make_user()

    client.post(LOGIN, json={"email": account.email, "password": account.password})

    raw = client.cookies[SESSION_COOKIE_NAME]
    row = _sessions(conn, account.id)[0]
    assert row["token_hash"] != raw
    assert row["token_hash"] == hash_token(raw)


def test_the_token_appears_in_no_response_body(client: TestClient, make_user: MakeUser) -> None:
    account = make_user()

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert client.cookies[SESSION_COOKIE_NAME] not in response.text


def test_the_session_expires_within_the_absolute_bound(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()

    client.post(LOGIN, json={"email": account.email, "password": account.password})

    row = _sessions(conn, account.id)[0]
    assert row["expires_at"] > datetime.now(UTC)
    assert row["expires_at"] <= datetime.now(UTC) + timedelta(days=7)


def test_the_session_lifetime_is_the_week_the_addendum_specifies(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Written with literals rather than with `SESSION_ABSOLUTE_LIFETIME`, on
    # purpose: every other assertion about the lifetime derives its expectation
    # from the constant, so all of them track it wherever it goes. Shorten it to
    # five minutes and the suite stays green while staff are bounced back to the
    # login screen on a schedule nobody chose. Only a bound written independently
    # of the value under test can say that.
    account = make_user()

    client.post(LOGIN, json={"email": account.email, "password": account.password})

    rows = _sessions(conn, account.id)
    assert len(rows) == 1
    issued = rows[0]["expires_at"]
    assert issued >= datetime.now(UTC) + timedelta(days=6, hours=23)
    assert issued <= datetime.now(UTC) + timedelta(days=7)


def test_last_login_at_advances(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # FR-10: an Administrator sees each account's last sign-in, and this
    # endpoint is the only thing in the product that sets it.
    account = make_user()
    before = conn.execute(
        "SELECT last_login_at, updated_at FROM users WHERE id = %s", (account.id,)
    ).fetchone()
    assert before is not None
    assert before["last_login_at"] is None

    client.post(LOGIN, json={"email": account.email, "password": account.password})

    after = conn.execute(
        "SELECT last_login_at, updated_at FROM users WHERE id = %s", (account.id,)
    ).fetchone()
    assert after is not None
    assert after["last_login_at"] is not None
    # DW-17: `users` has no BEFORE UPDATE trigger, so the endpoint sets this by
    # hand. Nothing else would catch it forgetting.
    assert after["updated_at"] > before["updated_at"]


def test_an_unclaimed_but_valid_temporary_credential_signs_in(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Story 1.4 owns the forced-change screen. Login's job is to issue the
    # session and report the flag; refusing here would leave 1.4 nothing to
    # gate.
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert len(_sessions(conn, account.id)) == 1


def test_a_second_sign_in_issues_a_second_session(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # A phone and a desktop are two sessions, not one that steals the other.
    account = make_user()
    credential = {"email": account.email, "password": account.password}

    client.post(LOGIN, json=credential)
    client.cookies.clear()
    client.post(LOGIN, json=credential)

    assert len(_sessions(conn, account.id)) == 2


# --- The four identical rejections -------------------------------------------


def _rejection_cases(
    make_user: MakeUser, conn: psycopg.Connection | None = None
) -> dict[str, dict[str, str]]:
    """One credential per way a sign-in can fail, every one refused identically.

    `conn` adds the two cases that need a row the API itself cannot produce: a
    `password_hash` column holding something `shared_schema.passwords` did not
    write, and a temporary credential with no expiry at all.
    """
    unknown = make_user()
    wrong = make_user()
    deactivated = make_user(active=False)
    expired = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    cases = {
        "unknown address": {
            "email": f"nobody-{unknown.email}",
            "password": unknown.password,
        },
        "wrong password": {"email": wrong.email, "password": wrong.password[::-1] + "x"},
        "deactivated account": {"email": deactivated.email, "password": deactivated.password},
        "expired temporary credential": {"email": expired.email, "password": expired.password},
    }

    if conn is None:
        return cases

    # A digest this product did not write. `verify_password` raises
    # `InvalidHashError` rather than returning False, on purpose — a corrupt
    # column is a data-integrity fault, not a wrong password — and an
    # unguarded raise here would answer 500 where every other address answers
    # 401. That difference is an account-existence oracle.
    corrupt = make_user()
    conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", ("not-a-digest", corrupt.id))
    cases["corrupt stored digest"] = {"email": corrupt.email, "password": corrupt.password}

    # `must_change_password` with no expiry. The column is nullable and the
    # flag defaults true, so the row shape is reachable; reading NULL as "no
    # deadline" would give it a temporary credential that never dies, and
    # AGENTS.md gives those 72 hours without exception. Fail closed.
    undated = make_user(must_change_password=True)
    cases["temporary credential with no expiry"] = {
        "email": undated.email,
        "password": undated.password,
    }

    # Postgres text cannot hold a NUL byte, so this address never reaches a
    # query: psycopg refuses to send it. Unguarded that refusal escapes as a
    # 500 — the one input class this endpoint answers differently from every
    # other, which is the shape of signal the whole rule exists to remove.
    embedded_nul = make_user()
    cases["address with an embedded NUL"] = {
        "email": f"{embedded_nul.email}\x00",
        "password": embedded_nul.password,
    }

    # The lone-surrogate address is deliberately *not* here. It is refused a
    # whole layer earlier — by the body parser, as a 422 — so it is not one of
    # the ways a *credential* is rejected, and it cannot be expressed as a
    # Python dict passed to `json=` anyway, because httpx encodes that body
    # itself and refuses the character for the same reason psycopg does. It
    # goes on the wire as the escape a hostile client would actually send, in
    # `test_an_address_carrying_a_lone_surrogate_never_reaches_the_query`.
    return cases


def _comparable_headers(response: httpx.Response) -> dict[str, str]:
    """Every header two rejections must agree about.

    `Date` is the only one dropped: it is the clock's, not the endpoint's, and
    it differs between two responses for reasons that say nothing about the
    account. Everything else — Content-Length included, since equal bodies must
    produce equal lengths — is compared.
    """
    return {k.lower(): v for k, v in response.headers.items() if k.lower() != "date"}


def test_every_rejection_is_indistinguishable(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    responses = {
        label: client.post(LOGIN, json=credential)
        for label, credential in _rejection_cases(make_user, conn).items()
    }

    statuses = {label: response.status_code for label, response in responses.items()}
    bodies = {label: response.json() for label, response in responses.items()}
    headers = {label: _comparable_headers(response) for label, response in responses.items()}

    assert set(statuses.values()) == {401}
    assert list(bodies.values()).count(bodies["wrong password"]) == len(bodies), bodies
    assert list(headers.values()).count(headers["wrong password"]) == len(headers), headers
    # Every way to be refused is covered, not just the four the AC names.
    assert len(responses) == 7


def test_a_rejection_says_nothing_about_which_field_or_which_account(
    client: TestClient, make_user: MakeUser
) -> None:
    account = make_user()

    body = client.post(LOGIN, json={"email": account.email, "password": "wrong-password"}).json()

    assert body == {"error": {"code": "unauthorized", "message": INVALID_CREDENTIALS}}
    lowered = INVALID_CREDENTIALS.lower()
    for leak in ("deactivate", "expire", "not found", "unknown", "no such"):
        assert leak not in lowered
    assert account.email not in str(body)


def test_no_rejection_sets_a_cookie(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    for credential in _rejection_cases(make_user, conn).values():
        response = client.post(LOGIN, json=credential)
        assert "set-cookie" not in {k.lower() for k in response.headers}
        assert SESSION_COOKIE_NAME not in client.cookies


def test_no_rejection_creates_a_session_row(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    for credential in _rejection_cases(make_user, conn).values():
        client.post(LOGIN, json=credential)

    count = conn.execute("SELECT count(*) AS n FROM sessions").fetchone()
    assert count is not None
    assert count["n"] == 0


def test_the_unknown_address_path_spends_a_real_verify(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DW-24's actual mechanism, not just its observable consequence.

    Every other rejection test compares the four *responses*, and all four stay
    identical if the decoy call is deleted — the timing signal it exists to
    remove is invisible to an assertion about bodies and headers. So this one
    asserts the call itself: the no-such-account path must pay the same Argon2id
    work a wrong password pays, and it must pay it with the candidate the
    caller actually submitted rather than a constant.
    """
    calls: list[str] = []

    def recording_decoy(password: str) -> bool:
        calls.append(password)
        return False

    monkeypatch.setattr(auth, "verify_dummy_password", recording_decoy)
    account = make_user()

    client.post(LOGIN, json={"email": f"nobody-{account.email}", "password": account.password})

    assert calls == [account.password]


def test_a_wrong_password_needs_no_decoy(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the same equivalence.

    A wrong password already paid for a real verify, so calling the decoy there
    too would make it cost *twice* what an unknown address costs — the same
    signal, with the sign flipped.
    """
    calls: list[str] = []
    monkeypatch.setattr(auth, "verify_dummy_password", lambda password: calls.append(password))
    account = make_user()

    client.post(LOGIN, json={"email": account.email, "password": "definitely-wrong"})

    assert calls == []


def test_a_deactivated_account_does_not_get_its_last_login_recorded(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user(active=False)

    client.post(LOGIN, json={"email": account.email, "password": account.password})

    row = conn.execute("SELECT last_login_at FROM users WHERE id = %s", (account.id,)).fetchone()
    assert row is not None
    assert row["last_login_at"] is None


# --- Malformed bodies ---------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="empty"),
        pytest.param({"email": "a@b.lk"}, id="no password"),
        pytest.param({"password": "x" * 20}, id="no email"),
        pytest.param({"email": "", "password": "x" * 20}, id="blank email"),
        pytest.param({"email": "a@b.lk", "password": ""}, id="blank password"),
        pytest.param(
            {"email": "a@b.lk", "password": "x" * (MAX_PASSWORD_LENGTH + 1)},
            id="oversized password",
        ),
        pytest.param(
            {"email": "a@b.lk", "password": "x" * 20, "role": "admin"},
            id="an extra field",
        ),
    ],
)
def test_a_malformed_body_is_refused_without_echoing_it(
    client: TestClient, payload: dict[str, str]
) -> None:
    # 422 or 401 are both acceptable answers; what is not is a message naming
    # the offending value back to the caller.
    response = client.post(LOGIN, json=payload)

    assert response.status_code in {401, 422}
    assert set(response.json()) == {"error"}
    for value in payload.values():
        if value:
            assert value not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"email": "a@b.lk", "password": "x" * 20, "role": "admin"}, id="extra field"),
        pytest.param({"email": "a@b.lk", "password": ""}, id="blank password"),
        pytest.param({"email": "", "password": "x" * 20}, id="blank email"),
    ],
)
def test_the_request_contract_itself_refuses_these(
    client: TestClient, payload: dict[str, str]
) -> None:
    # The test above accepts either status, which is right for it — but it means
    # `extra="forbid"` and both `min_length=1` bounds are asserted by nothing.
    # Delete `extra="forbid"` and pydantic silently drops `role`; the handler
    # then looks up an address that does not exist, spends the decoy and answers
    # 401, which that test accepts. The contract widens to accept any field a
    # caller invents, exactly the way `LoginRequest`'s docstring says it must
    # not, with the suite green. So: where it is the *shape* of the body that is
    # wrong, the answer is validation's, and it is pinned here.
    response = client.post(LOGIN, json=payload)

    assert response.status_code == 422


def test_the_challenge_is_on_every_rejection(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # RFC 9110 requires a challenge on a 401, and `ApiError` and `api.main`'s
    # handlers both exist partly to carry one. `Basic` would make the browser
    # open its own credential dialog over the login screen, so the scheme is
    # `Session`.
    for credential in _rejection_cases(make_user, conn).values():
        response = client.post(LOGIN, json=credential)

        assert response.headers["www-authenticate"] == 'Session realm="rocell"'


def test_a_corrupt_stored_digest_is_logged_as_the_fault_it_is(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Answering the caller with the one generic rejection is right; saying
    # nothing at all about a column holding something this product did not
    # write would hide a data-integrity fault forever.
    account = make_user()
    conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", ("not-a-digest", account.id))

    with caplog.at_level(logging.ERROR, logger="rocell.api.auth"):
        response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 401
    assert any(record.levelno == logging.ERROR for record in caplog.records)
    # The account's own credential must not reach the log.
    assert account.password not in caplog.text


def test_an_address_carrying_a_lone_surrogate_never_reaches_the_query(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    r"""The other `str` psycopg cannot encode, and the boundary that stops it.

    `"\ud800"` is six ASCII characters on the wire, so it crosses the network
    without trouble, and Python's own `json.loads` decodes it into a `str` that
    cannot be encoded as UTF-8. Handed to psycopg it raises, and that raise
    would leave this endpoint answering 500 for one class of input and 401 for
    every other — an account-existence oracle in the same costume as the NUL
    byte `_is_addressable` exists for.

    It does not arrive, because pydantic's JSON reader parses this body and
    refuses the escape outright: a shape error, answered 422 with the generic
    validation envelope, decided before any account is looked at and therefore
    the same for an address that exists and one that does not. `auth.py` leans
    on that and says so. Swap the body parser — for orjson, for a framework
    version that hands the handler `json.loads`'s output — and the 500 becomes
    reachable with nothing else failing. This is what notices.

    Posted as raw bytes rather than through `json=`: httpx encodes a dict body
    itself and refuses the character for the same reason psycopg does, so the
    dict form cannot express the request an attacker sends.
    """
    account = make_user()

    def submit(email: str) -> httpx.Response:
        body = json.dumps({"email": email, "password": account.password})
        return client.post(
            LOGIN,
            content=body.replace('{"email": "', '{"email": "\\ud800', 1).encode("ascii"),
            headers={"content-type": "application/json"},
        )

    real = submit(account.email)
    unknown = submit(f"nobody-{account.email}")

    assert real.status_code == 422, real.text
    # Refused for its shape, so it says the same thing either way: the 422 is
    # not a second channel telling a caller which addresses exist.
    assert real.json() == unknown.json()
    assert _comparable_headers(real) == _comparable_headers(unknown)
    count = conn.execute("SELECT count(*) AS n FROM sessions").fetchone()
    assert count is not None
    assert count["n"] == 0


def test_a_corrupt_stored_digest_still_pays_for_the_verify_it_skipped(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `verify_password` parses the stored digest *before* it hashes anything, so
    # `InvalidHashError` is raised having spent none of the ~100ms every other
    # rejection costs. The four responses stay byte-identical either way — the
    # same blind spot `test_the_unknown_address_path_spends_a_real_verify`
    # exists for — while a corrupt row answers measurably faster than a wrong
    # password, which tells a caller the account is there. So the call is
    # asserted, not the response.
    calls: list[str] = []

    def recording_decoy(password: str) -> bool:
        calls.append(password)
        return False

    monkeypatch.setattr(auth, "verify_dummy_password", recording_decoy)
    account = make_user()
    conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", ("not-a-digest", account.id))

    client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert calls == [account.password]


def test_a_temporary_credential_with_no_expiry_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Fails closed. `temp_credential_expires_at` is nullable and
    # `must_change_password` defaults true, so this row shape is reachable —
    # and reading NULL as "no deadline" would give it a temporary credential
    # that never expires, which AGENTS.md forbids without exception.
    account = make_user(must_change_password=True, temp_credential_expires_at=None)

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 401
    count = conn.execute("SELECT count(*) AS n FROM sessions").fetchone()
    assert count is not None
    assert count["n"] == 0


def test_a_claimed_account_with_no_expiry_still_signs_in(
    client: TestClient, make_user: MakeUser
) -> None:
    # The mirror image, and the reason the check is on `must_change_password`
    # rather than on the column alone: every account that has set its own
    # password has a NULL expiry and must still be able to sign in.
    account = make_user(must_change_password=False, temp_credential_expires_at=None)

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200


def test_login_sweeps_sessions_that_have_already_expired(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # `lookup_session` refuses an expired row anyway, so this changes no
    # behaviour — which is exactly why nothing else would notice it becoming a
    # no-op while the table grew one dead row per sign-in forever.
    account = make_user()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (account.id, hash_token("long-dead-token"), datetime.now(UTC) - timedelta(days=1)),
    )
    stale = make_user()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (stale.id, hash_token("another-dead-token"), datetime.now(UTC) - timedelta(seconds=1)),
    )

    client.post(LOGIN, json={"email": account.email, "password": account.password})

    rows = conn.execute("SELECT token_hash, expires_at FROM sessions").fetchall()
    # Every expired row is gone — the other user's too; an expired session
    # belongs to nobody — and the one just issued is the only one left.
    assert len(rows) == 1
    assert rows[0]["expires_at"] > datetime.now(UTC)
    assert rows[0]["token_hash"] == hash_token(client.cookies[SESSION_COOKIE_NAME])


def test_the_sweep_is_bounded_so_one_sign_in_never_drains_a_whole_backlog(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The bound is the entire point of the reworked sweep, and with two dead
    # rows in the table the test above passes whether the LIMIT is 100, 1 or
    # absent. Seed more than the limit and one unlucky sign-in's share becomes
    # observable: it pays for `EXPIRED_SWEEP_LIMIT` rows and no more.
    #
    # What this catches is the bound being *removed* — the LIMIT dropped from
    # the statement, or the sweep quietly rewritten table-wide. It cannot catch
    # the constant being changed, because the expectation is derived from it;
    # that is a deliberate edit rather than the accident worth guarding.
    account = make_user()
    dead = EXPIRED_SWEEP_LIMIT + 5
    with conn.transaction():
        for index in range(dead):
            conn.execute(
                "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (account.id, hash_token(f"dead-{index}"), datetime.now(UTC) - timedelta(days=1)),
            )

    client.post(LOGIN, json={"email": account.email, "password": account.password})

    left = conn.execute("SELECT count(*) AS n FROM sessions WHERE expires_at <= now()").fetchone()
    assert left is not None
    assert left["n"] == dead - EXPIRED_SWEEP_LIMIT


def test_a_failing_sweep_does_not_undo_a_sign_in_that_has_already_committed(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sweep runs after the login transaction commits. Letting its failure
    # out of the handler answers 500 to a sign-in that *happened*: the row is
    # there, `last_login_at` has moved, and the user is left holding no cookie
    # while the session behind it lives out its week unreachable. It is
    # housekeeping; it does not get to fail the request it rides on.
    account = make_user()

    def explode(*_: object, **__: object) -> int:
        raise psycopg.OperationalError("deadlock detected")

    monkeypatch.setattr(auth, "delete_expired_sessions", explode)

    response = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in response.cookies
    assert len(_sessions(conn, account.id)) == 1


def test_the_auth_responses_are_never_stored(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Every response carries something about who is signed in here — a name, an
    # address and a role on the two that return a body, and "not this person"
    # on the rest. A shared shop-floor tablet behind a caching proxy, or this
    # PWA's eventual service worker, would otherwise be free to hand one
    # person's identity, or one person's rejection, to the next. A 204 is
    # cacheable by default, which is the one of these nobody expects.
    account = make_user()

    signed_in = client.post(LOGIN, json={"email": account.email, "password": account.password})
    session = client.get("/auth/session")
    signed_out = client.post("/auth/logout")
    rejected = client.post(LOGIN, json={"email": account.email, "password": "not-the-password"})
    no_session = client.get("/auth/session")

    for response in (signed_in, session, signed_out, rejected, no_session):
        assert response.headers["cache-control"] == "no-store", response.request.url


def test_an_oversized_address_is_refused_before_the_lookup(
    client: TestClient, conn: psycopg.Connection
) -> None:
    # `MAX_EMAIL_LENGTH` is the only thing stopping a megabyte of text reaching
    # the query, and without this the bound could be deleted with the suite
    # still green.
    response = client.post(
        LOGIN,
        json={"email": "a" * (auth.MAX_EMAIL_LENGTH + 1) + "@rocell.lk", "password": "x" * 16},
    )

    assert response.status_code == 422
    count = conn.execute("SELECT count(*) AS n FROM sessions").fetchone()
    assert count is not None
    assert count["n"] == 0


def test_signing_in_again_revokes_the_session_the_browser_was_holding(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The cookie is about to be overwritten, so the row behind it would
    # otherwise stay live and unreachable for the rest of its seven days:
    # nothing can present it and logout only revokes the cookie it is given.
    account = make_user()

    client.post(LOGIN, json={"email": account.email, "password": account.password})
    first = client.cookies[SESSION_COOKIE_NAME]

    client.post(LOGIN, json={"email": account.email, "password": account.password})
    second = client.cookies[SESSION_COOKIE_NAME]

    assert second != first
    rows = _sessions(conn, account.id)
    assert [row["token_hash"] for row in rows] == [hash_token(second)]


def test_another_device_keeps_its_session_when_this_one_signs_in_again(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Only the presented cookie is spent. Revoking every session of a user is
    # Story 1.5's, and signing in on a phone must not sign the same person out
    # of the desktop they left open in the back office.
    account = make_user()
    elsewhere = hash_token("a-session-held-by-another-device")
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
        (account.id, elsewhere, datetime.now(UTC) + timedelta(days=1)),
    )

    client.post(LOGIN, json={"email": account.email, "password": account.password})
    client.post(LOGIN, json={"email": account.email, "password": account.password})

    hashes = {row["token_hash"] for row in _sessions(conn, account.id)}
    assert elsewhere in hashes


# --- Story 1.4's second acceptance clause, end to end ------------------------


def test_an_expired_temporary_credential_cannot_reach_the_change_screen(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The AC: "an unclaimed temporary credential stops working after 72 hours
    # and must be reissued by an Administrator." Login answers the generic
    # rejection, so no session is issued — and with no session there is no
    # forced-change screen to land on and no `POST /auth/password` to call. The
    # only way back is a reissue (`make reseed-admin` for the seeded
    # Administrator, `infra/README.md`).
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    refused = client.post(LOGIN, json={"email": account.email, "password": account.password})

    assert refused.status_code == 401
    assert refused.json()["error"]["message"] == INVALID_CREDENTIALS
    assert _sessions(conn, account.id) == []
    # Nothing to present, so the change endpoint is unreachable too.
    assert (
        client.post("/auth/password", json={"new_password": "a-long-enough-password"}).status_code
        == 401
    )


def test_a_valid_temporary_credential_signs_in_and_completes_the_claim(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The other half of the same clause: inside the window the credential works
    # exactly once — to set a real password — and the account is claimed from
    # then on.
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=71),
    )

    signed_in = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert signed_in.status_code == 200
    assert signed_in.json()["must_change_password"] is True

    claimed = client.post("/auth/password", json={"new_password": f"{account.password}-claimed"})

    assert claimed.status_code == 200
    row = conn.execute(
        "SELECT must_change_password, temp_credential_expires_at FROM users WHERE id = %s",
        (account.id,),
    ).fetchone()
    assert row is not None
    assert row["must_change_password"] is False
    assert row["temp_credential_expires_at"] is None
