"""`POST /auth/password` — the forced change itself.

Story 1.4's first half. The endpoint is the only way an admin-issued temporary
credential ever stops being one, so the assertions here are about what the
database looks like afterwards, not only about the status code: a `200` that
left `must_change_password` set, or left the expiry armed, or left the old
cookie working, is the failure this story exists to prevent and it looks exactly
like success from the outside.

Every password is generated at runtime, here and in `conftest.make_user`.
AGENTS.md Policy forbids a committed credential in a fixture as firmly as in
source.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from api import auth
from api.auth import (
    ALREADY_CLAIMED,
    MAX_PASSWORD_FIELD_LENGTH,
    PASSWORD_CHANGE_NOT_REQUIRED,
    WEAK_PASSWORD,
)
from api.dependencies import NO_SESSION, UNAUTHORIZED
from api.sessions import SESSION_COOKIE_NAME, delete_sessions_for_user, issue_session
from fastapi.testclient import TestClient
from shared_schema.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PASSWORD_RULES,
    verify_password,
)

LOGIN = "/auth/login"
PASSWORD = "/auth/password"
SESSION = "/auth/session"

#: `conftest.make_user`, which returns a `conftest.Account`. A conftest is not
#: an importable module under pytest's importlib mode, so the factory is typed
#: by its shape rather than by that class.
MakeUser = Callable[..., Any]


def a_password(length: int = MIN_PASSWORD_LENGTH + 8) -> str:
    """A password of exactly `length` characters, never the same one twice."""
    return secrets.token_urlsafe(length * 2)[:length]


def _unclaimed(make_user: MakeUser) -> Any:
    """An account holding a valid, unexpired, unclaimed temporary credential."""
    return make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
        name="Kasun Perera",
    )


def _signed_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


def _stored(conn: psycopg.Connection, user_id: Any) -> dict[str, Any]:
    row = conn.execute(
        "SELECT password_hash, must_change_password, temp_credential_expires_at, updated_at "
        "FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()
    assert row is not None
    return dict(row)


def _session_count(conn: psycopg.Connection, user_id: Any) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM sessions WHERE user_id = %s", (user_id,)
    ).fetchone()
    assert row is not None
    return int(row["n"])


# --- The change succeeds ------------------------------------------------------


def test_a_forced_change_clears_the_flag_and_the_expiry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 200
    body = response.json()
    assert body["must_change_password"] is False
    assert body["temp_credential_expires_at"] is None
    assert body["email"] == account.email

    stored = _stored(conn, account.id)
    assert stored["must_change_password"] is False
    # Cleared together with the flag. The expiry is what login checks for an
    # unclaimed row, and leaving it armed points a 72-hour deadline at an
    # account that no longer has a temporary credential to expire.
    assert stored["temp_credential_expires_at"] is None


def test_the_stored_digest_is_replaced(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)
    before = _stored(conn, account.id)["password_hash"]
    new_password = a_password()

    client.post(PASSWORD, json={"new_password": new_password})

    after = _stored(conn, account.id)["password_hash"]
    assert after != before
    assert verify_password(after, new_password) is True
    assert verify_password(after, account.password) is False


def test_updated_at_advances(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # `users` carries no BEFORE UPDATE trigger (DW-17) and the column's DEFAULT
    # applies to inserts only, so the statement has to set this by hand. Without
    # the assertion, dropping it from the UPDATE changes nothing visible.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    before = _stored(conn, account.id)["updated_at"]

    client.post(PASSWORD, json={"new_password": a_password()})

    assert _stored(conn, account.id)["updated_at"] > before


def test_exactly_one_session_survives_the_change(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The temporary credential travelled by whatever channel an Administrator
    # used. Every session issued on it goes when it does — including one opened
    # on a device its owner cannot reach — and the caller is handed a fresh one
    # so the change does not bounce them to the login screen.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    other_device = TestClient(client.app, base_url="https://testserver")
    _signed_in(other_device, account)
    assert _session_count(conn, account.id) == 2

    client.post(PASSWORD, json={"new_password": a_password()})

    assert _session_count(conn, account.id) == 1


def test_the_cookie_held_before_the_change_stops_working(
    client: TestClient, make_user: MakeUser
) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)
    stale = TestClient(client.app, base_url="https://testserver")
    stale.cookies.set(SESSION_COOKIE_NAME, client.cookies[SESSION_COOKIE_NAME])

    client.post(PASSWORD, json={"new_password": a_password()})

    assert stale.get(SESSION).status_code == 401


def test_the_caller_is_still_signed_in_afterwards(client: TestClient, make_user: MakeUser) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)
    before = client.cookies[SESSION_COOKIE_NAME]

    response = client.post(PASSWORD, json={"new_password": a_password()})

    # A new token, in a fresh cookie, on the same response that revoked the old
    # one — the caller's own browser must not be the casualty of the rotation.
    assert response.cookies[SESSION_COOKIE_NAME] != before
    session = client.get(SESSION)
    assert session.status_code == 200
    assert session.json()["must_change_password"] is False


def test_the_new_cookie_carries_every_required_flag(
    client: TestClient, make_user: MakeUser
) -> None:
    # AGENTS.md Policy, in full, on the one other response that sets a cookie.
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": a_password()})

    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=strict" in header.replace("samesite", "SameSite")
    assert "Path=/" in header


def test_the_old_password_no_longer_signs_in_and_the_new_one_does(
    client: TestClient, make_user: MakeUser
) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)
    new_password = a_password()
    client.post(PASSWORD, json={"new_password": new_password})

    fresh = TestClient(client.app, base_url="https://testserver")
    refused = fresh.post(LOGIN, json={"email": account.email, "password": account.password})
    accepted = fresh.post(LOGIN, json={"email": account.email, "password": new_password})

    assert refused.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["must_change_password"] is False


def test_the_response_is_never_stored(client: TestClient, make_user: MakeUser) -> None:
    # The body carries a signed-in user's name, address and role.
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.headers["cache-control"] == "no-store"


def test_no_password_material_reaches_the_response(client: TestClient, make_user: MakeUser) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)
    new_password = a_password()

    response = client.post(PASSWORD, json={"new_password": new_password})

    assert "password_hash" not in response.text
    assert new_password not in response.text


# --- The rules, each naming itself --------------------------------------------


@pytest.mark.parametrize(
    ("length", "rule"),
    [(1, "too_short"), (MIN_PASSWORD_LENGTH - 1, "too_short")],
)
def test_a_short_password_is_refused_naming_the_length_rule(
    client: TestClient, make_user: MakeUser, length: int, rule: str
) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": a_password(length)})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == WEAK_PASSWORD
    # The rule, not "invalid password" (EXPERIENCE.md:87). `apps/web` renders
    # this sentence verbatim.
    assert body["message"] == PASSWORD_RULES[rule]
    assert str(MIN_PASSWORD_LENGTH) in body["message"]


def test_the_minimum_length_itself_is_accepted(client: TestClient, make_user: MakeUser) -> None:
    # The boundary is inclusive, and it is the boundary the endpoint and
    # `hash_password` have to agree about — a password the API accepted and the
    # hasher refused would be a 500 after the check said yes.
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": a_password(MIN_PASSWORD_LENGTH)})

    assert response.status_code == 200


def test_an_oversized_password_is_refused_naming_the_length_rule(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Not a validation failure. "The request was not in the expected shape" is
    # the generic rejection EXPERIENCE.md:87 forbids for a password, so the
    # request model deliberately does not enforce this bound and the handler
    # answers with the sentence naming it.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    before = _stored(conn, account.id)

    response = client.post(PASSWORD, json={"new_password": a_password(MAX_PASSWORD_LENGTH + 1)})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == WEAK_PASSWORD
    assert body["message"] == PASSWORD_RULES["too_long"]
    assert str(MAX_PASSWORD_LENGTH) in body["message"]
    # Refused before anything is hashed: the rule check precedes both the reuse
    # verify and `hash_password`, so this costs one `len()`.
    assert _stored(conn, account.id)["password_hash"] == before["password_hash"]


def test_an_empty_password_is_refused_naming_the_rule(
    client: TestClient, make_user: MakeUser
) -> None:
    # The third of the three rules, and the other one the request model used to
    # swallow into a generic 422.
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": ""})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == WEAK_PASSWORD
    assert body["message"] == PASSWORD_RULES["empty"]


def test_an_absurd_body_is_refused_by_validation(client: TestClient, make_user: MakeUser) -> None:
    # The ceiling is not a password rule; it is the point past which a body has
    # stopped being a password. Past it the generic 422 is the honest answer,
    # and the endpoint never measures a megabyte against a length rule.
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": "x" * (MAX_PASSWORD_FIELD_LENGTH + 1)})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_every_length_between_the_rule_and_the_ceiling_names_the_rule(
    client: TestClient, make_user: MakeUser
) -> None:
    # The gap the old bound hid: a 500-character candidate is refusable by the
    # rule that exists, and must not fall through to "the request was not in
    # the expected shape".
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": a_password(500)})

    assert response.json()["error"]["message"] == PASSWORD_RULES["too_long"]


def test_the_maximum_length_itself_is_accepted(client: TestClient, make_user: MakeUser) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": a_password(MAX_PASSWORD_LENGTH)})

    assert response.status_code == 200


def test_reusing_the_temporary_password_is_refused_naming_the_reuse(
    client: TestClient, make_user: MakeUser
) -> None:
    # The one rule that costs an Argon2id verify, and the second of the two
    # EXPERIENCE.md:87 names.
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": account.password})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == WEAK_PASSWORD
    assert "temporary" in body["message"].lower()
    assert "invalid" not in body["message"].lower()


@pytest.mark.parametrize(
    "candidate",
    ["short", "reuse"],
)
def test_a_refused_password_writes_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, candidate: str
) -> None:
    # The digest, the flag and the session all survive a rejection. A refusal
    # that had already revoked the session would strand the user on a screen
    # they can no longer submit from.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    before = _stored(conn, account.id)
    new_password = a_password(1) if candidate == "short" else account.password

    response = client.post(PASSWORD, json={"new_password": new_password})

    assert response.status_code == 422
    after = _stored(conn, account.id)
    assert after["password_hash"] == before["password_hash"]
    assert after["must_change_password"] is True
    assert after["temp_credential_expires_at"] == before["temp_credential_expires_at"]
    assert after["updated_at"] == before["updated_at"]
    assert _session_count(conn, account.id) == 1
    assert client.get(SESSION).status_code == 200


def test_a_rejection_is_never_stored(client: TestClient, make_user: MakeUser) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json={"new_password": a_password(1)})

    assert response.headers["cache-control"] == "no-store"


# --- Who may call it ----------------------------------------------------------


def test_a_claimed_account_is_refused_with_a_conflict(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Story 1.7 owns the signed-in self-service change, and it asks for a
    # current password this endpoint deliberately does not take. Answering here
    # would be a password change on a live session with nothing proved.
    account = make_user(must_change_password=False)
    _signed_in(client, account)
    before = _stored(conn, account.id)

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == PASSWORD_CHANGE_NOT_REQUIRED
    assert body["message"] == ALREADY_CLAIMED
    # `api_error_handler` builds a fresh response from `ApiError.headers`, so the
    # `NO_STORE` that `current_user` puts on the injected response never reaches
    # a rejection. Every other refusal on this endpoint is pinned; without this
    # line the 409 — which names a specific signed-in account's state — is the
    # one that could lose the header and stay green.
    assert response.headers["cache-control"] == "no-store"
    assert _stored(conn, account.id)["password_hash"] == before["password_hash"]


def test_no_cookie_is_refused(client: TestClient, conn: psycopg.Connection) -> None:
    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 401
    assert response.json()["error"] == {"code": UNAUTHORIZED, "message": NO_SESSION}
    count = conn.execute("SELECT count(*) AS n FROM sessions").fetchone()
    assert count is not None
    assert count["n"] == 0


def test_an_unknown_token_is_refused_and_the_stale_cookie_cleared(
    client: TestClient, make_user: MakeUser
) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)
    client.cookies.set(SESSION_COOKIE_NAME, "not-a-token")

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 401
    # A cookie the server no longer honours is worse than no cookie.
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]


def test_a_deactivated_owner_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # FR-13 / AD-3: deactivation takes effect on the very next request, and the
    # forced-change endpoint is not an exception to it.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    conn.execute("UPDATE users SET active = false WHERE id = %s", (account.id,))

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 401
    assert _stored(conn, account.id)["must_change_password"] is True


# --- The request contract -----------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"password": "a-long-enough-password"},
        {"new_password": None},
        # `extra="forbid"`: a field this endpoint does not read is a caller with
        # a different idea of the contract, and Story 1.7's `current_password`
        # is exactly the field that would otherwise be sent and ignored.
        {"new_password": "a-long-enough-password", "current_password": "whatever"},
    ],
)
def test_a_malformed_body_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, body: dict[str, Any]
) -> None:
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post(PASSWORD, json=body)

    assert response.status_code == 422
    assert _stored(conn, account.id)["must_change_password"] is True


def test_a_malformed_body_is_not_echoed_back(client: TestClient, make_user: MakeUser) -> None:
    # The envelope has no field for per-field detail, and echoing the submitted
    # value would put a password candidate in a response body.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    candidate = a_password()

    response = client.post(PASSWORD, json={"new_password": candidate, "extra": candidate})

    assert response.status_code == 422
    assert candidate not in response.text


def test_the_session_endpoint_still_reports_the_flag_while_it_is_set(
    client: TestClient, make_user: MakeUser
) -> None:
    # Deliberately ungated: this is how `apps/web` learns to show the change
    # screen at all. Gating it would leave the front end with a 403 and no way
    # to know what to render.
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.get(SESSION)

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True


def test_logout_still_works_while_the_flag_is_set(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # A user must always be able to leave, including one who cannot yet reach
    # anything else.
    account = _unclaimed(make_user)
    _signed_in(client, account)

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert _session_count(conn, account.id) == 0


# --- The 72 hours hold here too, not only at login ---------------------------


def test_an_expired_credential_cannot_claim_the_account(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # A session outlives the credential that issued it: seven days against 72
    # hours. Sign in at hour 1, come back at hour 100, and login refuses — but
    # the session from hour 1 is still valid, so without a deadline check *here*
    # the account could still be claimed through it, turning AGENTS.md line 18's
    # 72 hours into eleven days.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    before = _stored(conn, account.id)
    conn.execute(
        "UPDATE users SET temp_credential_expires_at = now() - interval '1 hour' WHERE id = %s",
        (account.id,),
    )

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 401
    after = _stored(conn, account.id)
    assert after["must_change_password"] is True
    assert after["password_hash"] == before["password_hash"]
    # The credential is dead, so the sessions riding on it go with it. The way
    # back is a reissue, not a retry.
    assert _session_count(conn, account.id) == 0


def test_an_expired_credential_with_no_expiry_at_all_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Fails closed, exactly as login does: a `must_change_password` row with a
    # NULL expiry is expired, not deadline-free. The row shape is reachable
    # through an admin insert that forgets the column, and reading NULL the
    # other way would hand exactly those rows an immortal temporary credential.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    conn.execute("UPDATE users SET temp_credential_expires_at = NULL WHERE id = %s", (account.id,))

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 401
    assert _stored(conn, account.id)["must_change_password"] is True


def test_the_deadline_is_checked_before_the_password_is_judged(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # A dead credential is refused as a dead credential, not as a weak password.
    # The other order would tell the caller their password was too short when
    # the truth is that no password would have worked.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    conn.execute(
        "UPDATE users SET temp_credential_expires_at = now() - interval '1 hour' WHERE id = %s",
        (account.id,),
    )

    response = client.post(PASSWORD, json={"new_password": "short"})

    assert response.status_code == 401


# --- The claim happens exactly once ------------------------------------------


def test_the_update_itself_refuses_an_already_claimed_row(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The 409 guard reads a `User` fetched by a separate query, so it cannot be
    # the whole answer: between that read and the write, another request on the
    # same session can claim the account. `AND must_change_password` on the
    # UPDATE is what makes "once" a property of the statement — this drives that
    # predicate directly by clearing the flag underneath a request that has
    # already passed the guard.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    before = _stored(conn, account.id)

    original = auth.password_rule_violation

    def claim_it_first(candidate: str) -> str | None:
        # Runs after the guard and before the write, which is the window the
        # predicate exists to close.
        conn.execute("UPDATE users SET must_change_password = false WHERE id = %s", (account.id,))
        return original(candidate)

    # `monkeypatch`, not a hand-rolled try/finally: it restores on the teardown
    # paths a `finally` inside the test body does not cover, and it needs no
    # `type: ignore` to assign over a module-level function.
    monkeypatch.setattr(auth, "password_rule_violation", claim_it_first)

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == PASSWORD_CHANGE_NOT_REQUIRED
    # Nothing written: the transaction unwound, so the loser of the race did not
    # overwrite the winner's digest or revoke the session it had just issued.
    assert _stored(conn, account.id)["password_hash"] == before["password_hash"]
    assert _session_count(conn, account.id) == 1


def test_a_second_post_on_the_fresh_cookie_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The duplicate request a real browser produces: a double submit, a retried
    # POST, a second tab replaying the same action. The first change succeeds
    # and hands back a working cookie, so the second arrives *authenticated* —
    # and must be refused on the flag this endpoint reads per request, not
    # quietly rotate a password a moment after the account was claimed.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    assert client.post(PASSWORD, json={"new_password": a_password()}).status_code == 200
    claimed = _stored(conn, account.id)

    response = client.post(PASSWORD, json={"new_password": a_password()})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == PASSWORD_CHANGE_NOT_REQUIRED
    # And the session the first change issued is still the caller's: a refusal
    # here must not cost them the password they just set.
    assert _stored(conn, account.id)["password_hash"] == claimed["password_hash"]
    assert _session_count(conn, account.id) == 1
    assert client.get(SESSION).status_code == 200


def test_a_row_that_disappears_before_the_credential_read_is_refused(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `set_password` reads the credential state in a second query, after the
    # session lookup that produced the `User`. A row deleted in between leaves
    # `fetchone()` with `None`, and the handler answers 401 rather than reading
    # a column off it. Nothing else in this suite can reach that branch — the
    # `sessions` foreign key cascades, so a user deleted before the request even
    # starts is refused earlier, at the session lookup — so the statement itself
    # is narrowed here to the one thing it cannot return in a test: no row.
    account = _unclaimed(make_user)
    _signed_in(client, account)
    monkeypatch.setattr(
        auth, "_SELECT_CREDENTIAL_STATE", auth._SELECT_CREDENTIAL_STATE + " AND false"
    )

    response = client.post(PASSWORD, json={"new_password": a_password()})

    # Not a 500 with a traceback: the caller is on a screen with no sign-out
    # control, so the answer has to be the one that sends them back to login,
    # and the cookie the server can no longer honour has to go with it.
    assert response.status_code == 401
    assert response.json()["error"] == {"code": UNAUTHORIZED, "message": NO_SESSION}
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]


# --- The revocation is scoped to one user ------------------------------------


def test_another_users_sessions_are_untouched(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The property that matters most about a `DELETE ... WHERE user_id = %s`,
    # and the one a single-account test cannot see at all: dropping the
    # predicate would sign the whole company out every time somebody set a
    # password.
    changer = _unclaimed(make_user)
    bystander = make_user(must_change_password=False, name="Nimali Silva")
    _signed_in(client, changer)
    onlooker = TestClient(client.app, base_url="https://testserver")
    _signed_in(onlooker, bystander)

    assert client.post(PASSWORD, json={"new_password": a_password()}).status_code == 200

    assert _session_count(conn, bystander.id) == 1
    still_signed_in = onlooker.get(SESSION)
    assert still_signed_in.status_code == 200
    assert still_signed_in.json()["email"] == bystander.email


def test_deleting_a_users_sessions_reports_how_many_went(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The documented return value, which nothing else reads. A helper that
    # silently returned 0 would satisfy every other assertion in this file.
    account = make_user()
    other = make_user()
    issue_session(conn, account.id)
    issue_session(conn, account.id)
    issue_session(conn, other.id)

    assert delete_sessions_for_user(conn, account.id) == 2
    assert delete_sessions_for_user(conn, account.id) == 0
    assert _session_count(conn, other.id) == 1
