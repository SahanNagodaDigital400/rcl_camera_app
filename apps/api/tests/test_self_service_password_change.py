"""`POST /auth/password/change` — the signed-in self-service change (FR-5).

Story 1.7's endpoint, and the mirror image of `test_password_change.py`: that
file is about an account claiming a temporary credential exactly once, this one
is about an account replacing a password it already chose, as often as it likes,
having proved it every time.

Three properties carry most of the weight here, and each of them looks exactly
like success from the outside if it is broken:

* **The current password is proved before anything else happens.** A build that
  checked the new password's rules first would still pass every happy-path
  assertion while handing an unauthenticated decision to a caller who cannot
  prove the account is theirs. `test_a_wrong_current_password_is_refused_before_
  the_new_one_is_judged` and the `hash_password` monkeypatch are what see it.
* **A wrong current password is a `403`, never a `401`.** `apps/web`'s
  `apiRequest` fires its session observer on *status* 401, so a 401 here signs
  the user out for mistyping a box. Nothing else in the suite can see the
  difference between the two statuses.
* **The change revokes every session of its user and reissues the caller's.** A
  password changed because somebody else may know it, with that somebody's
  session left alive, has not done the thing the user asked for.

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
    CURRENT_PASSWORD_WRONG,
    INVALID_CURRENT_PASSWORD,
    MAX_PASSWORD_FIELD_LENGTH,
    PASSWORD_UNCHANGED,
    WEAK_PASSWORD,
)
from api.dependencies import (
    NO_SESSION,
    PASSWORD_CHANGE_REQUIRED,
    SET_A_PASSWORD_FIRST,
    UNAUTHORIZED,
)
from api.sessions import SESSION_COOKIE_NAME
from fastapi.testclient import TestClient
from shared_schema.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PASSWORD_RULES,
    verify_password,
)
from shared_schema.user import User

LOGIN = "/auth/login"
CHANGE = "/auth/password/change"
FORCED = "/auth/password"
SESSION = "/auth/session"

#: `conftest.make_user`, which returns a `conftest.Account`. A conftest is not an
#: importable module under pytest's importlib mode, so the factory is typed by
#: its shape rather than by that class.
MakeUser = Callable[..., Any]


def a_password(length: int = MIN_PASSWORD_LENGTH + 8) -> str:
    """A password of exactly `length` characters, never the same one twice."""
    return secrets.token_urlsafe(length * 2)[:length]


def _signed_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


def _stored(conn: psycopg.Connection, user_id: Any) -> dict[str, Any]:
    row = conn.execute(
        "SELECT password_hash, must_change_password, temp_credential_expires_at, "
        "updated_at, locked_until FROM users WHERE id = %s",
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


def _body(current: str, new: str) -> dict[str, str]:
    return {"current_password": current, "new_password": new}


# --- The change succeeds ------------------------------------------------------


def test_a_correct_current_password_replaces_the_digest(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user(name="Kasun Perera")
    _signed_in(client, account)
    before = _stored(conn, account.id)["password_hash"]
    new_password = a_password()

    response = client.post(CHANGE, json=_body(account.password, new_password))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == account.email
    assert body["must_change_password"] is False

    after = _stored(conn, account.id)["password_hash"]
    assert after != before
    assert verify_password(after, new_password) is True
    assert verify_password(after, account.password) is False


def test_the_body_is_the_whole_user_contract(client: TestClient, make_user: MakeUser) -> None:
    # `response_model=User` is what keeps a digest off the wire, and the closed
    # shape is what makes an extra key a loud failure rather than a quiet drop.
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    assert set(response.json()) == set(User.model_fields)


def test_updated_at_advances(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # `users` carries no BEFORE UPDATE trigger (DW-17) and the column's DEFAULT
    # applies to inserts only, so the statement has to set this by hand. Without
    # the assertion, dropping it from the UPDATE changes nothing visible.
    account = make_user()
    _signed_in(client, account)
    before = _stored(conn, account.id)["updated_at"]

    client.post(CHANGE, json=_body(account.password, a_password()))

    assert _stored(conn, account.id)["updated_at"] > before


def test_the_claimed_flag_and_the_expiry_are_left_alone(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The difference from the forced change: this account has no temporary
    # credential to clear, so writing either column would be inventing state.
    account = make_user()
    _signed_in(client, account)

    client.post(CHANGE, json=_body(account.password, a_password()))

    stored = _stored(conn, account.id)
    assert stored["must_change_password"] is False
    assert stored["temp_credential_expires_at"] is None


def test_the_old_password_stops_working_and_the_new_one_starts(
    client: TestClient, make_user: MakeUser
) -> None:
    # The AC's own wording, and the whole point of the endpoint: immediately,
    # with no sign-out and no re-login between the change and the first attempt.
    account = make_user()
    _signed_in(client, account)
    new_password = a_password()
    assert client.post(CHANGE, json=_body(account.password, new_password)).status_code == 200

    fresh = TestClient(client.app, base_url="https://testserver")
    refused = fresh.post(LOGIN, json={"email": account.email, "password": account.password})
    accepted = fresh.post(LOGIN, json={"email": account.email, "password": new_password})

    assert refused.status_code == 401
    assert accepted.status_code == 200


def test_the_caller_stays_signed_in_on_a_fresh_cookie(
    client: TestClient, make_user: MakeUser
) -> None:
    account = make_user()
    _signed_in(client, account)
    before = client.cookies[SESSION_COOKIE_NAME]

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    # A new token, in a fresh cookie, on the same response that revoked the old
    # one — the caller's own browser must not be the casualty of their own change.
    assert response.cookies[SESSION_COOKIE_NAME] != before
    assert client.get(SESSION).status_code == 200
    # And the token it replaced is *dead*, not merely superseded. Without this,
    # a handler that issued a second session and revoked none would satisfy
    # every other assertion here: the caller would hold a working cookie, and
    # the cookie would be a different string.
    stale = TestClient(client.app, base_url="https://testserver")
    stale.cookies.set(SESSION_COOKIE_NAME, before)
    assert stale.get(SESSION).status_code == 401


def test_the_new_cookie_carries_every_required_flag(
    client: TestClient, make_user: MakeUser
) -> None:
    # AGENTS.md Policy, in full, on the third response in the product that sets a
    # session cookie.
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "Secure" in header
    # Case-folded on both sides. `http.cookies` renders the attribute name as
    # `SameSite` and the value exactly as it was handed in, and neither casing is
    # part of the policy — `SameSite=Strict` is the same cookie. Normalising only
    # the name would pin a rendering detail and call a conformant one a failure.
    assert "samesite=strict" in header.lower()
    assert "Path=/" in header


def test_every_other_device_is_signed_out(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The reason people change a password they already chose is that they think
    # somebody else has it. A change that leaves that somebody's session alive
    # has not done the thing the user asked for.
    account = make_user()
    _signed_in(client, account)
    other_device = TestClient(client.app, base_url="https://testserver")
    _signed_in(other_device, account)
    assert _session_count(conn, account.id) == 2

    assert client.post(CHANGE, json=_body(account.password, a_password())).status_code == 200

    assert _session_count(conn, account.id) == 1
    # The other device finds out on its next request, not at some later sweep.
    assert other_device.get(SESSION).status_code == 401
    assert client.get(SESSION).status_code == 200


def test_another_users_sessions_are_untouched(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The property that matters most about a `DELETE ... WHERE user_id = %s`, and
    # the one a single-account test cannot see at all: dropping the predicate
    # would sign the whole company out every time somebody changed a password.
    changer = make_user()
    bystander = make_user(name="Nimali Silva")
    _signed_in(client, changer)
    onlooker = TestClient(client.app, base_url="https://testserver")
    _signed_in(onlooker, bystander)

    assert client.post(CHANGE, json=_body(changer.password, a_password())).status_code == 200

    assert _session_count(conn, bystander.id) == 1
    assert onlooker.get(SESSION).status_code == 200


def test_the_response_is_never_stored(client: TestClient, make_user: MakeUser) -> None:
    # The body carries a signed-in user's name, address and role.
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    assert response.headers["cache-control"] == "no-store"


def test_no_password_material_reaches_the_response(client: TestClient, make_user: MakeUser) -> None:
    account = make_user()
    _signed_in(client, account)
    new_password = a_password()

    response = client.post(CHANGE, json=_body(account.password, new_password))

    assert "password_hash" not in response.text
    assert new_password not in response.text
    assert account.password not in response.text


def test_the_lock_ladder_is_not_cleared(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # A lock is a property of the address under attack, not of the credential. A
    # signed-in user clearing it would hand an attacker a way to reset the ladder
    # by borrowing an unlocked phone for ten seconds (DW-57 is the related
    # reissue gap).
    account = make_user()
    _signed_in(client, account)
    conn.execute(
        "UPDATE users SET locked_until = %s WHERE id = %s",
        (datetime.now(UTC) + timedelta(minutes=15), account.id),
    )
    before = _stored(conn, account.id)["locked_until"]
    # `login_attempts.locked_until` is the column that *decides* a lockout;
    # `users.locked_until` is the mirror the migration's own header calls
    # reporting-only ("It reports; it never decides"). Set and asserted here
    # because a build that cleared the deciding column would otherwise pass a
    # test named for not clearing the ladder.
    locked_until = datetime.now(UTC) + timedelta(minutes=15)
    conn.execute(
        "INSERT INTO login_attempts (email_key, failure_count, locked_until) VALUES (%s, %s, %s)",
        (account.email, 7, locked_until),
    )

    assert client.post(CHANGE, json=_body(account.password, a_password())).status_code == 200

    assert _stored(conn, account.id)["locked_until"] == before
    row = conn.execute(
        "SELECT failure_count, locked_until FROM login_attempts WHERE email_key = %s",
        (account.email,),
    ).fetchone()
    assert row is not None
    assert row["failure_count"] == 7
    assert row["locked_until"] == locked_until


# --- The current password is proved first -------------------------------------


def test_a_wrong_current_password_is_refused_with_a_forbidden(
    client: TestClient, make_user: MakeUser
) -> None:
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(a_password(), a_password()))

    # `403`, and never `401`: `apps/web`'s `apiRequest` fires its session
    # observer on status 401, so answering 401 here would sign the user out of a
    # perfectly good session for mistyping a field.
    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": INVALID_CURRENT_PASSWORD,
        "message": CURRENT_PASSWORD_WRONG,
    }
    assert response.headers["cache-control"] == "no-store"


def test_a_wrong_current_password_leaves_the_session_alone(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(a_password(), a_password()))

    assert response.status_code == 403
    # No cookie is cleared and no row is deleted or created — a refusal must not
    # cost the user the session they are refusing from, or they cannot retype.
    assert "set-cookie" not in {key.lower() for key in response.headers}
    assert _session_count(conn, account.id) == 1
    assert client.get(SESSION).status_code == 200


def test_a_wrong_current_password_writes_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _signed_in(client, account)
    before = _stored(conn, account.id)

    client.post(CHANGE, json=_body(a_password(), a_password()))

    after = _stored(conn, account.id)
    assert after["password_hash"] == before["password_hash"]
    assert after["updated_at"] == before["updated_at"]


def test_a_wrong_current_password_spends_no_hash(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ordering, driven rather than asserted about. `hash_password` is a 64
    # MiB Argon2id operation and it must not be reachable on a request that has
    # not proved the account is the caller's; making it explode is the only way
    # to see that it was never called, because a call that succeeded would leave
    # the same 403 behind.
    account = make_user()
    _signed_in(client, account)

    def refuse_to_hash(candidate: str) -> str:
        raise AssertionError("hash_password ran on an unproven request")

    monkeypatch.setattr(auth, "hash_password", refuse_to_hash)

    response = client.post(CHANGE, json=_body(a_password(), a_password()))

    assert response.status_code == 403


def test_a_wrong_current_password_is_refused_before_the_new_one_is_judged(
    client: TestClient, make_user: MakeUser
) -> None:
    # Both orderings "work". Only this one refuses to hand a decision about the
    # password policy to a caller who cannot prove the current password — the
    # new password here is four characters and is never assessed.
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(a_password(), "abcd"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == INVALID_CURRENT_PASSWORD


def test_an_empty_current_password_is_refused_as_a_wrong_one(
    client: TestClient, make_user: MakeUser
) -> None:
    # `verify_password` returns False for an empty candidate rather than raising,
    # and the request model deliberately sets no minimum — so this is a wrong
    # current password like any other, not a validation error.
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body("", a_password()))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == INVALID_CURRENT_PASSWORD


# --- The rules, each naming itself --------------------------------------------


@pytest.mark.parametrize(
    ("length", "rule"),
    [(1, "too_short"), (MIN_PASSWORD_LENGTH - 1, "too_short")],
)
def test_a_short_new_password_is_refused_naming_the_length_rule(
    client: TestClient, make_user: MakeUser, length: int, rule: str
) -> None:
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(account.password, a_password(length)))

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == WEAK_PASSWORD
    # The rule, not "invalid password" (EXPERIENCE.md:87). `apps/web` renders this
    # sentence verbatim.
    assert body["message"] == PASSWORD_RULES[rule]


def test_an_empty_new_password_is_refused_naming_the_rule(
    client: TestClient, make_user: MakeUser
) -> None:
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(account.password, ""))

    assert response.status_code == 422
    assert response.json()["error"]["message"] == PASSWORD_RULES["empty"]


def test_an_oversized_new_password_is_refused_naming_the_length_rule(
    client: TestClient, make_user: MakeUser
) -> None:
    # Not a validation failure: the request model deliberately does not enforce
    # this bound, because "the request was not in the expected shape" is the
    # generic rejection EXPERIENCE.md:87 forbids for a password.
    account = make_user()
    _signed_in(client, account)

    response = client.post(
        CHANGE, json=_body(account.password, a_password(MAX_PASSWORD_LENGTH + 1))
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == PASSWORD_RULES["too_long"]


@pytest.mark.parametrize("length", [MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH])
def test_both_length_boundaries_are_accepted(
    client: TestClient, make_user: MakeUser, length: int
) -> None:
    # Inclusive at both ends, and the boundary the endpoint and `hash_password`
    # have to agree about — a password the API accepted and the hasher refused
    # would be a 500 after the check said yes.
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(account.password, a_password(length)))

    assert response.status_code == 200


def test_reusing_the_current_password_is_refused_naming_the_rule(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The twin of the forced change's temporary-reuse rule: about one account's
    # stored digest rather than about the string, so `shared_schema.passwords`
    # cannot decide it, and answered with the same `weak_password` code so a
    # client branches once.
    account = make_user()
    _signed_in(client, account)
    before = _stored(conn, account.id)

    response = client.post(CHANGE, json=_body(account.password, account.password))

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == WEAK_PASSWORD
    assert body["message"] == PASSWORD_UNCHANGED
    assert "invalid" not in body["message"].lower()
    assert _stored(conn, account.id)["password_hash"] == before["password_hash"]


def test_the_reuse_rule_costs_no_second_hash(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The current password has already been proved against the stored digest, so
    # comparing the two strings is equivalent to a second verify and spends
    # nothing. A build that reached for `hash_password` first would be paying 64
    # MiB to learn what `==` already knew.
    account = make_user()
    _signed_in(client, account)

    def refuse_to_hash(candidate: str) -> str:
        raise AssertionError("hash_password ran for a password the rules refused")

    monkeypatch.setattr(auth, "hash_password", refuse_to_hash)

    response = client.post(CHANGE, json=_body(account.password, account.password))

    assert response.status_code == 422


@pytest.mark.parametrize("candidate", ["short", "reuse"])
def test_a_refused_new_password_writes_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, candidate: str
) -> None:
    # The digest and the session both survive a rejection. A refusal that had
    # already revoked the session would strand the user on a screen they can no
    # longer submit from.
    account = make_user()
    _signed_in(client, account)
    before = _stored(conn, account.id)
    new_password = a_password(1) if candidate == "short" else account.password

    response = client.post(CHANGE, json=_body(account.password, new_password))

    assert response.status_code == 422
    after = _stored(conn, account.id)
    assert after["password_hash"] == before["password_hash"]
    assert after["updated_at"] == before["updated_at"]
    assert _session_count(conn, account.id) == 1
    assert client.get(SESSION).status_code == 200


def test_a_rejection_is_never_stored(client: TestClient, make_user: MakeUser) -> None:
    account = make_user()
    _signed_in(client, account)

    response = client.post(CHANGE, json=_body(account.password, a_password(1)))

    assert response.headers["cache-control"] == "no-store"


# --- Who may call it ----------------------------------------------------------


def test_no_cookie_is_refused_as_unauthenticated(
    client: TestClient, conn: psycopg.Connection
) -> None:
    response = client.post(CHANGE, json=_body(a_password(), a_password()))

    assert response.status_code == 401
    assert response.json()["error"] == {"code": UNAUTHORIZED, "message": NO_SESSION}
    assert response.headers["www-authenticate"].startswith("Session")
    # A cookie the server no longer honours is worse than no cookie.
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]
    count = conn.execute("SELECT count(*) AS n FROM sessions").fetchone()
    assert count is not None
    assert count["n"] == 0


def test_a_user_on_a_temporary_credential_is_refused_by_the_gate(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # `require_claimed_user`, declared by the route and deliberately not added to
    # `ALLOWED_WITHOUT_THE_GATE`. An account still holding an admin-issued
    # temporary credential belongs on `POST /auth/password`; answering both from
    # one place would make the forced change skippable.
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _signed_in(client, account)
    before = _stored(conn, account.id)

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": PASSWORD_CHANGE_REQUIRED,
        "message": SET_A_PASSWORD_FIRST,
    }
    assert _stored(conn, account.id)["password_hash"] == before["password_hash"]
    assert _stored(conn, account.id)["must_change_password"] is True


def test_the_forced_change_is_still_the_route_for_an_unclaimed_account(
    client: TestClient, make_user: MakeUser
) -> None:
    # The two endpoints cover every account exactly once, and neither is
    # reachable for the other's state: this is the other half of the pair, and it
    # must keep working while the self-service route refuses the same caller.
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _signed_in(client, account)
    assert client.post(CHANGE, json=_body(account.password, a_password())).status_code == 403

    claimed = client.post(FORCED, json={"new_password": a_password()})

    assert claimed.status_code == 200


def test_a_claimed_account_is_refused_by_the_forced_change(
    client: TestClient, make_user: MakeUser
) -> None:
    # And the reverse, so the pair is pinned from both sides in one place.
    account = make_user()
    _signed_in(client, account)

    response = client.post(FORCED, json={"new_password": a_password()})

    assert response.status_code == 409


def test_a_deactivated_owner_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # FR-13 / AD-3: deactivation takes effect on the very next request, and this
    # endpoint is not an exception to it.
    account = make_user()
    _signed_in(client, account)
    before = _stored(conn, account.id)
    conn.execute("UPDATE users SET active = false WHERE id = %s", (account.id,))

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    assert response.status_code == 401
    assert _stored(conn, account.id)["password_hash"] == before["password_hash"]


def test_an_unknown_token_is_refused_and_the_stale_cookie_cleared(
    client: TestClient, make_user: MakeUser
) -> None:
    account = make_user()
    _signed_in(client, account)
    client.cookies.set(SESSION_COOKIE_NAME, "not-a-token")

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    assert response.status_code == 401
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]


# --- The request contract -----------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"new_password": "a-long-enough-password"},
        {"current_password": "a-long-enough-password"},
        {"current_password": None, "new_password": "a-long-enough-password"},
        # `extra="forbid"`: a field this endpoint does not read is a caller with
        # a different idea of the contract.
        {
            "current_password": "a-long-enough-password",
            "new_password": "another-long-password",
            "confirm_password": "another-long-password",
        },
    ],
)
def test_a_malformed_body_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser, body: dict[str, Any]
) -> None:
    account = make_user()
    _signed_in(client, account)
    before = _stored(conn, account.id)

    response = client.post(CHANGE, json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert _stored(conn, account.id)["password_hash"] == before["password_hash"]


@pytest.mark.parametrize("field", ["current_password", "new_password"])
def test_an_absurd_field_is_refused_by_validation(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    # The ceiling is not a password rule; it is the point past which a body has
    # stopped being a password. Past it the generic 422 is the honest answer, and
    # nothing is hashed or verified for it — the monkeypatch is what proves the
    # second half.
    account = make_user()
    _signed_in(client, account)

    def refuse_to_hash(candidate: str) -> str:
        raise AssertionError("hash_password ran for a body validation refused")

    monkeypatch.setattr(auth, "hash_password", refuse_to_hash)
    body = _body(account.password, a_password())
    body[field] = "x" * (MAX_PASSWORD_FIELD_LENGTH + 1)

    response = client.post(CHANGE, json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_a_malformed_body_is_not_echoed_back(client: TestClient, make_user: MakeUser) -> None:
    # The envelope has no field for per-field detail, and echoing the submitted
    # value would put a password candidate in a response body.
    account = make_user()
    _signed_in(client, account)
    candidate = a_password()

    response = client.post(
        CHANGE,
        json={
            "current_password": account.password,
            "new_password": candidate,
            "extra": candidate,
        },
    )

    assert response.status_code == 422
    assert candidate not in response.text


# --- The write is decided by the statement, not by a check taken earlier ------


def test_a_credential_reissued_between_the_gate_and_the_write_refuses_the_change(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `require_claimed_user` read the flag through a separate query some
    # microseconds earlier, so it cannot be the whole answer: an Administrator
    # reissuing a temporary credential in that window would otherwise have this
    # request overwrite the credential they had just issued.
    # `AND NOT must_change_password` on the UPDATE is what makes "the gate's fact
    # is still true at the moment of the write" a property of the statement, and
    # this drives that predicate directly by setting the flag underneath a
    # request that has already passed the gate.
    account = make_user()
    _signed_in(client, account)
    before = _stored(conn, account.id)

    original = auth.password_rule_violation

    def reissue_first(candidate: str) -> str | None:
        # Runs after the gate and before the write, which is the window the
        # predicate exists to close.
        conn.execute("UPDATE users SET must_change_password = true WHERE id = %s", (account.id,))
        return original(candidate)

    # `monkeypatch`, not a hand-rolled try/finally: it restores on the teardown
    # paths a `finally` inside the test body does not cover.
    monkeypatch.setattr(auth, "password_rule_violation", reissue_first)

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": PASSWORD_CHANGE_REQUIRED,
        "message": SET_A_PASSWORD_FIRST,
    }
    # `_password_change_required()` is built inside the handler rather than
    # routed through `require_claimed_user`, so nothing else proves the two
    # answers to "this account is on a temporary credential" are the same
    # answer. Code, sentence and the no-store header, all three: a refusal is
    # the last response that may sit in a cache.
    assert response.headers["cache-control"] == "no-store"
    # Nothing written: the transaction unwound, so the request did not overwrite
    # the reissued credential or revoke the sessions riding on it.
    after = _stored(conn, account.id)
    assert after["password_hash"] == before["password_hash"]
    assert after["updated_at"] == before["updated_at"]
    assert _session_count(conn, account.id) == 1


def test_a_row_that_disappears_before_the_digest_read_is_refused(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The handler reads the digest in a second query, after the session lookup
    # that produced the `User`. A row deleted in between leaves `fetchone()` with
    # `None`, and the handler answers 401 rather than reading a column off it.
    # Nothing else in this suite can reach that branch — the `sessions` foreign
    # key cascades, so a user deleted before the request starts is refused
    # earlier — so the statement is narrowed here to the one thing it cannot
    # return in a test: no row.
    account = make_user()
    _signed_in(client, account)
    monkeypatch.setattr(auth, "_SELECT_PASSWORD_HASH", auth._SELECT_PASSWORD_HASH + " AND false")

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    assert response.status_code == 401
    assert response.json()["error"] == {"code": UNAUTHORIZED, "message": NO_SESSION}
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]
    # `NO_STORE` is set on `response` before the handler can raise, and the two
    # 403 factories carry it on their own `ApiError`. This is the third arm and
    # the only one that leaves through neither route, so it is the one place the
    # header could be lost without a test noticing — on an endpoint whose 200
    # carries a name, an address and a role.
    assert response.headers["cache-control"] == "no-store"


def test_a_row_that_disappears_before_the_write_is_refused(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The other half of the `RETURNING`-is-empty branch, and the one that decides
    # 401 from 403. Deleting the account for real is what an Administrator doing
    # it mid-request looks like, and it must not be reported as the gate's
    # refusal — the session is genuinely gone with the row.
    account = make_user()
    _signed_in(client, account)

    original = auth.password_rule_violation

    def delete_it_first(candidate: str) -> str | None:
        conn.execute("DELETE FROM users WHERE id = %s", (account.id,))
        return original(candidate)

    monkeypatch.setattr(auth, "password_rule_violation", delete_it_first)

    response = client.post(CHANGE, json=_body(account.password, a_password()))

    assert response.status_code == 401
    assert response.json()["error"] == {"code": UNAUTHORIZED, "message": NO_SESSION}


# --- The three RETURNING lists are one list ----------------------------------


def _returning(statement: str) -> list[str]:
    """The column list a statement's `RETURNING` clause names, in order."""
    _, marker, tail = statement.partition("RETURNING")
    assert marker, "statement has no RETURNING clause"
    columns = [column.strip() for column in tail.split(",")]
    # A naive split is right for three statements that name bare columns and
    # nothing else, and wrong the moment one carries a trailing comment, a
    # second `RETURNING`, or an expression with a comma in it. Checked rather
    # than assumed, so that day fails here — as a parse the helper cannot do —
    # instead of reporting a drift that is really a misread.
    assert all(column.isidentifier() for column in columns), (
        f"RETURNING clause is not a plain column list, so it cannot be compared: {columns}"
    )
    return columns


def test_every_returning_list_in_the_module_is_the_user_contract() -> None:
    # Three statements build a `User` from `RETURNING`, and each one's comment
    # says it matches the other two. Nothing checked it until now: drop a column
    # from one and `User.model_validate` raises a 500 on that path alone — which
    # `test_login.py` or `test_password_change.py` would catch for two of them,
    # and *reordering* one would be caught by nothing at all, because
    # `dict_row` keys by name.
    #
    # Compared as ordered lists, not sets: `model_fields` preserves declaration
    # order, and a statement that agrees on the set and not the order is a
    # statement somebody has edited without reading.
    lists = {
        "_RECORD_LOGIN": _returning(auth._RECORD_LOGIN),
        "_SET_PASSWORD": _returning(auth._SET_PASSWORD),
        "_CHANGE_PASSWORD": _returning(auth._CHANGE_PASSWORD),
    }
    contract = list(User.model_fields)

    assert {name: columns for name, columns in lists.items() if columns != contract} == {}
