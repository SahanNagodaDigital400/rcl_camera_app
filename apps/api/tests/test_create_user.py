"""`POST /admin/users` — FR-11, every row of Story 1.8's I/O matrix.

The authorization half lives in `test_admin_authorization.py`, which holds the
role check to the route *table*. This file is about the write: what it stores,
what it refuses, and the two properties nothing else in the suite can see —
that the row it produces is immediately usable through the front door, and that
its `RETURNING` list has not drifted from the three writers in `api.auth` that
share it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from api import auth, users
from api.auth import MAX_EMAIL_LENGTH, MAX_PASSWORD_FIELD_LENGTH
from api.dependencies import ADMINISTRATOR_REQUIRED, PASSWORD_CHANGE_REQUIRED
from api.users import EMAIL_ALREADY_EXISTS, INVALID_EMAIL, MAX_NAME_LENGTH
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from shared_schema.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, PASSWORD_RULES
from shared_schema.user import TEMP_CREDENTIAL_LIFETIME_HOURS, Role, User

CREATE_USER = "/admin/users"
LOGIN = "/auth/login"
CLAIM = "/auth/password"
SELF_CHANGE = "/auth/password/change"

MakeUser = Callable[..., Any]

#: A password long enough to satisfy `shared_schema.passwords`, assembled at
#: runtime rather than written down. AGENTS.md Policy forbids a committed
#: credential in a fixture as firmly as in source, and a repeated character is
#: the one shape that is obviously not one.
TEMPORARY = "t" * (MIN_PASSWORD_LENGTH + 8)

#: A second one, for the tests that need the two to differ.
REPLACEMENT = "r" * (MIN_PASSWORD_LENGTH + 8)


def _body(**overrides: Any) -> dict[str, Any]:
    """A valid provisioning body, with whatever this test wants changed."""
    submitted: dict[str, Any] = {
        "name": "Nadeesha Silva",
        "email": "nadeesha@rocell.lk",
        "role": Role.STAFF.value,
        "temporary_password": TEMPORARY,
    }
    submitted.update(overrides)
    return submitted


def _sign_in(client: TestClient, email: str, password: str) -> None:
    response = client.post(LOGIN, json={"email": email, "password": password})
    assert response.status_code == 200


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    """A claimed Administrator, signed in on `client`.

    `make_user(role=Role.ADMIN)` already produces one — `must_change_password`
    defaults to `False` there — so no fixture of its own is needed for the role.
    """
    account = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(client, account.email, account.password)
    return account


def _user_count(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT count(*) AS total FROM users").fetchone()
    assert row is not None
    return int(row["total"])


def _rows_for(conn: psycopg.Connection, email: str) -> int:
    row = conn.execute(
        "SELECT count(*) AS total FROM users WHERE lower(email) = %s", (email.strip().lower(),)
    ).fetchone()
    assert row is not None
    return int(row["total"])


# --- Happy path ---------------------------------------------------------------


def test_an_administrator_provisions_a_user(client: TestClient, administrator: Any) -> None:
    response = client.post(CREATE_USER, json=_body())

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Nadeesha Silva"
    assert body["email"] == "nadeesha@rocell.lk"
    assert body["role"] == Role.STAFF.value
    assert body["active"] is True
    assert body["must_change_password"] is True
    assert body["temp_credential_expires_at"] is not None
    assert body["last_login_at"] is None
    # The three columns the statement leaves to the schema rather than naming.
    # `locked_until` is FR-4's lock, which a brand new row has never been near;
    # `created_at` and `updated_at` take their column DEFAULTs, which is what
    # makes DW-17 — `users` has no BEFORE UPDATE trigger, so every *writer* sets
    # `updated_at` by hand — inapplicable to an INSERT. Asserted rather than only
    # argued in a comment, so a writer that started setting one of them by hand
    # has to say so here.
    assert body["locked_until"] is None
    assert body["updated_at"] == body["created_at"]


def test_the_body_is_the_shared_user_contract(client: TestClient, administrator: Any) -> None:
    # `isUser` in the TypeScript twin rejects a body carrying any key beyond the
    # contract — and the eleven keys are also what `User.model_validate` above
    # has already proved. Asserted here because this is the first endpoint whose
    # response describes somebody other than the caller.
    body = client.post(CREATE_USER, json=_body()).json()

    assert set(body) == set(User.model_fields)


def test_the_response_carries_no_digest(client: TestClient, administrator: Any) -> None:
    # `User` has no `password_hash` field at all, so this cannot regress through
    # a serializer change — only through somebody adding the field. It is
    # asserted over the raw text as well as the parsed body, because a digest
    # leaking under a *different* key would still be a digest on the wire.
    response = client.post(CREATE_USER, json=_body())

    assert "password_hash" not in response.json()
    assert "$argon2" not in response.text


def test_the_submitted_password_is_never_echoed(client: TestClient, administrator: Any) -> None:
    # The Administrator typed it and the screen already has it. Putting it back
    # on the wire only puts it wherever the response is written down.
    response = client.post(CREATE_USER, json=_body())

    assert TEMPORARY not in response.text


def test_the_response_is_never_stored(client: TestClient, administrator: Any) -> None:
    response = client.post(CREATE_USER, json=_body())

    assert response.headers["cache-control"] == "no-store"


def test_the_role_is_what_was_submitted(client: TestClient, administrator: Any) -> None:
    # Both roles, because `Role` has two and a handler that hardcoded one would
    # pass every other test in this file.
    staff = client.post(CREATE_USER, json=_body(email="kasun@rocell.lk", role=Role.STAFF.value))
    admin = client.post(CREATE_USER, json=_body(email="dilani@rocell.lk", role=Role.ADMIN.value))

    assert staff.json()["role"] == Role.STAFF.value
    assert admin.json()["role"] == Role.ADMIN.value


def test_the_name_is_stored_stripped(client: TestClient, administrator: Any) -> None:
    body = client.post(CREATE_USER, json=_body(name="  Nadeesha Silva  ")).json()

    assert body["name"] == "Nadeesha Silva"


def test_the_address_is_stored_normalized(client: TestClient, administrator: Any) -> None:
    # `users` carries CHECK (email = lower(email)) and its only unique index is
    # over `lower(email)`, so an address stored in the case somebody typed would
    # be refused by the constraint or missed by every later lookup.
    body = client.post(CREATE_USER, json=_body(email="  Nadeesha@Rocell.LK  ")).json()

    assert body["email"] == "nadeesha@rocell.lk"


def test_a_non_ascii_address_is_folded_by_postgres(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # `users` carries CHECK (email = lower(email)), and `str.lower()` and
    # Postgres's `lower()` are not guaranteed to agree on non-ASCII input — which
    # of them moves depends on the server's collation. Where they disagree, a
    # statement that wrote the Python-folded string would fail its own CHECK, and
    # a `CheckViolation` nothing catches is an unexplained `500` in front of an
    # Administrator who typed an ordinary address. `_INSERT_USER` writes
    # `lower(%s)`, so the stored value is by construction the one the constraint
    # compares against.
    #
    # **This case cannot fail on the suite's own cluster, and that is worth
    # saying rather than leaving to be discovered.** `conftest` builds it with
    # `initdb`'s default, which lands on `C.UTF-8` — a collation whose `lower()`
    # folds ASCII and nothing else, so it can only ever agree with a string
    # Python has already folded. The disagreement this guards against needs a
    # full Unicode collation, which is what production will run on. What holds
    # the fix in place here is therefore the statement-level pin in
    # `test_the_write_folds_the_address_in_postgres` below, in the same register
    # as the two product rules pinned beside it; this case is the end-to-end
    # evidence that folding twice breaks nothing.
    submitted = "\u0130nbox@Rocell.LK"

    response = client.post(CREATE_USER, json=_body(email=submitted))

    assert response.status_code == 201
    # Postgres's own verdict on the string the handler sends it, asked of the
    # same server: a literal here would be this test asserting Python's answer
    # about a column Postgres owns.
    folded = conn.execute("SELECT lower(%s) AS value", (submitted.strip().lower(),)).fetchone()
    assert folded is not None
    assert response.json()["email"] == folded["value"]
    assert _rows_for(conn, folded["value"]) == 1


def test_the_credential_expires_in_seventy_two_hours_by_the_database_clock(
    client: TestClient, administrator: Any
) -> None:
    # Both timestamps come from the same statement's `now()`: `created_at` from
    # the column DEFAULT and the deadline from `now() + make_interval`. Their
    # difference is therefore exactly the lifetime, measured by Postgres and not
    # by this host — which is the property AGENTS.md's 72 hours needs, because a
    # writer whose clock had drifted would otherwise issue a credential that
    # outlived the rule.
    body = client.post(CREATE_USER, json=_body()).json()

    created = _timestamp(body["created_at"])
    expires = _timestamp(body["temp_credential_expires_at"])

    assert expires - created == timedelta(hours=TEMP_CREDENTIAL_LIFETIME_HOURS)


def _timestamp(value: str) -> datetime:
    """An ISO 8601 UTC timestamp from the response, as an instant."""
    return datetime.fromisoformat(value)


def test_the_temporary_credential_lifetime_is_seventy_two_hours() -> None:
    # AGENTS.md Policy: "Never skip the forced password change on an admin-issued
    # temporary credential before granting further access; temporary credentials
    # expire after 72 hours." Every other assertion about the deadline in this
    # repository — the one above, and `infra/tests/test_migrate.py`'s — computes
    # its expectation *from* this constant, so changing it to 168 leaves the
    # whole suite green while the policy quietly stops being true. This is the
    # one place the number itself is written down twice on purpose.
    assert TEMP_CREDENTIAL_LIFETIME_HOURS == 72


def test_the_row_is_never_flagged_without_a_deadline(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # DW-44: a `must_change_password` row with a NULL `temp_credential_expires_at`
    # is permanently unusable — `auth._SELECT_CREDENTIAL` reads NULL as expired,
    # deliberately and fail-closed. `_INSERT_USER` sets both together in one
    # statement, so this writer cannot produce that row at all.
    client.post(CREATE_USER, json=_body())

    row = conn.execute(
        "SELECT must_change_password, temp_credential_expires_at FROM users "
        "WHERE lower(email) = %s",
        ("nadeesha@rocell.lk",),
    ).fetchone()

    assert row is not None
    assert row["must_change_password"] is True
    assert row["temp_credential_expires_at"] is not None


# --- Immediately usable, and gated by Story 1.4 -------------------------------


def test_the_new_user_can_sign_in_immediately(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # The acceptance clause, end to end: no migration, no console command, no
    # database access between the 201 and the sign-in.
    created = client.post(CREATE_USER, json=_body()).json()

    client.post("/auth/logout")
    response = client.post(LOGIN, json={"email": "nadeesha@rocell.lk", "password": TEMPORARY})

    assert response.status_code == 200
    # The same `User`, not merely the same id: the matrix row says the sign-in
    # returns the row that was just written, and an id match alone would hold
    # while the flag, the deadline or the role came back as something else.
    # `last_login_at` and `updated_at` are excluded because signing in is what
    # sets them — that is `_RECORD_LOGIN`'s whole job.
    changed_by_signing_in = {"last_login_at", "updated_at"}
    signed_in = response.json()
    assert {key: value for key, value in signed_in.items() if key not in changed_by_signing_in} == {
        key: value for key, value in created.items() if key not in changed_by_signing_in
    }
    assert signed_in["last_login_at"] is not None


def test_the_new_user_meets_the_forced_change_first(client: TestClient, administrator: Any) -> None:
    # FR-11's "gated by FR-2". `POST /auth/password/change` is the nearest route
    # in the product that declares `require_claimed_user`, so it is what the new
    # user is refused by until the credential is exchanged.
    client.post(CREATE_USER, json=_body())
    client.post("/auth/logout")
    _sign_in(client, "nadeesha@rocell.lk", TEMPORARY)

    refused = client.post(
        SELF_CHANGE, json={"current_password": TEMPORARY, "new_password": REPLACEMENT}
    )

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == PASSWORD_CHANGE_REQUIRED


def test_the_new_user_claims_the_account_through_the_forced_change(
    client: TestClient, administrator: Any
) -> None:
    client.post(CREATE_USER, json=_body())
    client.post("/auth/logout")
    _sign_in(client, "nadeesha@rocell.lk", TEMPORARY)

    claimed = client.post(CLAIM, json={"new_password": REPLACEMENT})

    assert claimed.status_code == 200
    assert claimed.json()["must_change_password"] is False
    assert claimed.json()["temp_credential_expires_at"] is None
    # And the gated route opens on the very next request.
    assert (
        client.post(
            SELF_CHANGE, json={"current_password": REPLACEMENT, "new_password": TEMPORARY}
        ).status_code
        == 200
    )


def test_a_provisioned_administrator_is_an_administrator(
    client: TestClient, administrator: Any
) -> None:
    # The role reaches the row, not just the response body: a provisioned
    # Administrator who claims their credential can provision somebody else.
    client.post(CREATE_USER, json=_body(email="dilani@rocell.lk", role=Role.ADMIN.value))
    client.post("/auth/logout")
    _sign_in(client, "dilani@rocell.lk", TEMPORARY)
    assert client.post(CLAIM, json={"new_password": REPLACEMENT}).status_code == 200

    response = client.post(CREATE_USER, json=_body(email="kasun@rocell.lk"))

    assert response.status_code == 201


# --- Refusals -----------------------------------------------------------------


def test_a_staff_caller_is_refused_and_writes_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user(role=Role.STAFF)
    _sign_in(client, account.email, account.password)
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=_body())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED
    assert _user_count(conn) == before


def test_a_staff_caller_spends_no_hash(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The refusal comes from a dependency, so the handler never runs — and a
    # 64 MiB Argon2id hash is never paid for a request that was refused before
    # it started. Monkeypatched the way `test_login.py` monkeypatches the decoy
    # verify: the only way to observe work that is *not* done.
    hashed: list[str] = []
    monkeypatch.setattr(users, "hash_password", lambda password: hashed.append(password) or "x")

    account = make_user(role=Role.STAFF)
    _sign_in(client, account.email, account.password)
    client.post(CREATE_USER, json=_body())

    assert hashed == []


def test_an_administrator_on_a_temporary_credential_is_refused_by_the_gate(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The ordering that matters: `require_administrator` chains on
    # `require_claimed_user`, so the gate answers first and an Administrator
    # holding a credential that arrived on a note cannot use it to issue a
    # second one. Chained on `current_user` instead, this would be a 201.
    account = make_user(
        role=Role.ADMIN,
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _sign_in(client, account.email, account.password)
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=_body())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == PASSWORD_CHANGE_REQUIRED
    assert _user_count(conn) == before


def test_an_unauthenticated_caller_is_refused(client: TestClient) -> None:
    response = client.post(CREATE_USER, json=_body())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert "rocell_session=" in response.headers.get("set-cookie", "")


def test_a_demotion_takes_effect_on_the_next_request(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AD-3: `role` is re-read from Postgres on every request, never cached at
    # sign-in, so the request after the flip is the one that is refused.
    assert client.post(CREATE_USER, json=_body()).status_code == 201

    conn.execute("UPDATE users SET role = %s WHERE id = %s", (Role.STAFF.value, administrator.id))

    response = client.post(CREATE_USER, json=_body(email="kasun@rocell.lk"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED


@pytest.mark.parametrize(
    "duplicate",
    ["nadeesha@rocell.lk", "NADEESHA@ROCELL.LK", "  nadeesha@rocell.lk  ", "Nadeesha@Rocell.lk"],
)
def test_an_address_already_in_use_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, duplicate: str
) -> None:
    # Decided by the unique index over `lower(email)`, never by a prior SELECT: a
    # read-then-write is a race that hands two people the same login.
    assert client.post(CREATE_USER, json=_body()).status_code == 201

    response = client.post(CREATE_USER, json=_body(email=duplicate))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == EMAIL_ALREADY_EXISTS
    assert _rows_for(conn, "nadeesha@rocell.lk") == 1


def test_the_duplicate_is_answered_only_for_the_address_index(
    conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The handler answers `409` for `EMAIL_UNIQUE_INDEX` by name and re-raises
    # anything else, so the name has to be the one Postgres actually reports.
    # Rename the index in a migration, or answer the clash by exception class
    # alone, and a future unique constraint on `users` becomes a duplicate
    # address in front of an Administrator whose address is fine.
    account = make_user()

    with pytest.raises(pg_errors.UniqueViolation) as raised:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            ("Somebody Else", account.email, "x", Role.STAFF.value),
        )

    assert raised.value.diag.constraint_name == users.EMAIL_UNIQUE_INDEX


def test_a_clash_on_another_index_is_not_described_as_a_duplicate_address(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The branch `EMAIL_UNIQUE_INDEX` exists for, exercised through the endpoint
    # rather than against the index name alone. Answer every `UniqueViolation`
    # with `409` and the test above still passes — every clash it makes is on the
    # address index. This one is not: a second unique index, of the shape
    # Stories 1.9-1.11 may well add, is clashed on by a body whose address is
    # fine, and the Administrator must not be sent to the email field to fix it.
    conn.execute("CREATE UNIQUE INDEX users_name_key ON users (name)")
    assert client.post(CREATE_USER, json=_body()).status_code == 201

    with pytest.raises(pg_errors.UniqueViolation) as raised:
        client.post(CREATE_USER, json=_body(email="second@rocell.lk"))

    # Propagated, so `api.main` answers it as a 500 — honest about a clash this
    # endpoint cannot explain, rather than naming a field that is correct.
    assert raised.value.diag.constraint_name == "users_name_key"


def test_a_duplicate_writes_nothing_at_all(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    assert client.post(CREATE_USER, json=_body()).status_code == 201
    before = _user_count(conn)

    client.post(CREATE_USER, json=_body(name="Somebody Else", role=Role.ADMIN.value))

    assert _user_count(conn) == before


@pytest.mark.parametrize(
    "address",
    [
        "nadeesha",
        "@rocell.lk",
        "nadeesha@",
        "nadeesha@@rocell.lk",
        "a@b@c",
        "  ",
        "na\x00me@x.lk",
        # Interior whitespace. The ends are stripped, so what is left is a space
        # somebody typed inside the address — a stray keystroke, or a paste that
        # picked up a line wrap — and never part of an address anyone signs in
        # with. Refused rather than stored, because a stored one is a colleague
        # who cannot sign in for a reason nobody can see on a user list.
        "na deesha@rocell.lk",
        "nadeesha@roc ell.lk",
        # A non-breaking space, interior. `strip()` removes one at either end
        # like any other whitespace, so only an interior one reaches the check.
        "nadeesha\u00a0silva@rocell.lk",
    ],
)
def test_an_address_that_is_not_one_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, address: str
) -> None:
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=_body(email=address))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_EMAIL
    # The sentence names the rule (EXPERIENCE.md:87), rather than the generic
    # "the request was not in the expected shape" a request-model bound gives.
    assert "@" in response.json()["error"]["message"]
    assert _user_count(conn) == before


def test_an_address_that_is_not_one_costs_no_hash(
    client: TestClient, administrator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hashed: list[str] = []
    monkeypatch.setattr(users, "hash_password", lambda password: hashed.append(password) or "x")

    client.post(CREATE_USER, json=_body(email="nadeesha"))

    assert hashed == []


@pytest.mark.parametrize(
    ("password", "rule"),
    [
        ("", PASSWORD_RULES["empty"]),
        ("x" * (MIN_PASSWORD_LENGTH - 1), PASSWORD_RULES["too_short"]),
        ("x" * (MAX_PASSWORD_LENGTH + 1), PASSWORD_RULES["too_long"]),
    ],
)
def test_a_temporary_password_that_breaks_a_rule_is_refused(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    password: str,
    rule: str,
) -> None:
    # `shared_schema.passwords`' own sentences, verbatim — the one statement of
    # the rules, and the same message the forced change and the self-service
    # change give for the same string.
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=_body(temporary_password=password))

    assert response.status_code == 422
    assert response.json()["error"] == {"code": auth.WEAK_PASSWORD, "message": rule}
    assert _user_count(conn) == before


def test_a_temporary_password_that_breaks_a_rule_costs_no_hash(
    client: TestClient, administrator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cheap refusals come first, and this is what holds the order in place.
    # Move `password_rule_violation` below `hash_password` and the response is
    # byte-identical — same 422, same code, same sentence, same empty table — so
    # every other test in this file passes while an unthrottled endpoint
    # (DW-40/DW-69) starts paying 64 MiB of Argon2id for a blank field.
    hashed: list[str] = []
    monkeypatch.setattr(users, "hash_password", lambda password: hashed.append(password) or "x")

    client.post(CREATE_USER, json=_body(temporary_password=""))

    assert hashed == []


def test_the_address_is_answered_before_the_password(
    client: TestClient, administrator: Any
) -> None:
    # A body with two problems in it is answered about the one the Administrator
    # can see is wrong. Both refusals are a 422 and both name a rule, so nothing
    # else in this file notices if the two blocks are swapped — but the screen
    # marks and focuses the field the *code* names, and sending somebody to
    # correct a password when the address is what they mistyped is the "marking
    # the wrong input" failure `fieldAtFault` exists to prevent.
    response = client.post(CREATE_USER, json=_body(email="nadeesha", temporary_password=""))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_EMAIL


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"email": "nadeesha"}, 422),
        ({"temporary_password": ""}, 422),
    ],
)
def test_a_refusal_is_never_stored(
    client: TestClient, administrator: Any, body: dict[str, Any], expected: int
) -> None:
    # `NO_STORE` on the refusals as well as on the `201`. The 422 bodies carry
    # the address somebody typed and the 409 says it is already a login here;
    # neither belongs in a shared handset's back/forward cache.
    response = client.post(CREATE_USER, json=_body(**body))

    assert response.status_code == expected
    assert response.headers["cache-control"] == "no-store"


def test_the_duplicate_refusal_is_never_stored(client: TestClient, administrator: Any) -> None:
    assert client.post(CREATE_USER, json=_body()).status_code == 201

    response = client.post(CREATE_USER, json=_body())

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "name",
    [
        # A NUL, which Postgres text cannot carry at all: psycopg refuses to send
        # it, so without the validator's screen this reaches `conn.execute` after
        # a full Argon2id hash has been paid and answers `500` where every other
        # refused body answers `422`.
        "Nadeesha\x00Silva",
        # And the rest of the control range, which no name holds and which
        # renders as nothing on a user list.
        "Nadeesha\x07Silva",
        "Nadeesha\x7fSilva",
    ],
)
def test_a_name_carrying_a_control_character_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, name: str
) -> None:
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=_body(name=name))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert _user_count(conn) == before


@pytest.mark.parametrize("name", ["", " ", "\t\n", "x" * (MAX_NAME_LENGTH + 1)])
def test_a_name_that_is_blank_or_oversized_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, name: str
) -> None:
    # Bounded by the request model, so the refusal is the generic 422 — a name
    # has no rule beyond "present, and bounded" for a message to name.
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=_body(name=name))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert _user_count(conn) == before


@pytest.mark.parametrize(
    "overlong",
    [
        {"email": "n" * MAX_EMAIL_LENGTH + "@rocell.lk"},
        {"temporary_password": "x" * (MAX_PASSWORD_FIELD_LENGTH + 1)},
    ],
    ids=["email", "temporary_password"],
)
def test_a_field_past_its_bound_is_refused(
    client: TestClient, conn: psycopg.Connection, administrator: Any, overlong: dict[str, Any]
) -> None:
    # The name's bound had a case of its own and these two had none, although all
    # three are the same rule and all three are mirrored onto the screen's inputs
    # by `error-code-parity.test.ts`. `MAX_PASSWORD_FIELD_LENGTH` is the one that
    # matters most: it is the point past which a body stops being a password at
    # all, and nothing past it may reach a 64 MiB Argon2id hash.
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=_body(**overlong))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert _user_count(conn) == before


@pytest.mark.parametrize(
    "body",
    [
        {"role": "owner"},
        {"role": "Admin"},
        {"role": ""},
    ],
)
def test_a_role_outside_the_two_is_refused(
    client: TestClient, administrator: Any, body: dict[str, Any]
) -> None:
    # AGENTS.md Policy: never a third role. `Role` is a `StrEnum`, so pydantic
    # refuses one before the handler runs — and the column's own CHECK is the
    # second, independent copy of the same rule.
    response = client.post(CREATE_USER, json=_body(**body))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_an_unknown_body_key_is_refused(client: TestClient, administrator: Any) -> None:
    # `extra="forbid"`. The two keys most likely to be sent are the two this
    # endpoint states as product rules rather than reads from a body.
    response = client.post(
        CREATE_USER, json={**_body(), "must_change_password": False, "active": False}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("field", ["name", "email", "role", "temporary_password"])
def test_a_missing_field_is_refused(client: TestClient, administrator: Any, field: str) -> None:
    # Parametrized rather than looped: a loop stops at the first field that
    # regresses and reports nothing about the other three.
    incomplete = _body()
    del incomplete[field]

    response = client.post(CREATE_USER, json=incomplete)

    assert response.status_code == 422


# --- The statement itself -----------------------------------------------------


def _returning(statement: str) -> str:
    """The `RETURNING` clause of a statement, whitespace and all."""
    head, separator, clause = statement.partition("RETURNING")
    assert separator, "the statement has no RETURNING clause"
    return clause.strip()


def test_the_returning_list_has_not_drifted_from_the_other_writers() -> None:
    # Four statements in the product return the eleven-column `User` shape, and
    # `User.model_validate` is what reads all four. They are repeated rather than
    # shared through a constant because `test_source_guards.py` forbids a
    # statement assembled from a value — so this is what holds them together.
    written = _returning(users._INSERT_USER)

    assert written == _returning(auth._SET_PASSWORD)
    assert written == _returning(auth._CHANGE_PASSWORD)
    assert written == _returning(auth._RECORD_LOGIN)


def test_the_returning_list_names_exactly_the_contract() -> None:
    # The other half: identical to three other lists is worth nothing if all four
    # are wrong. `User` has no `password_hash` field, so a column added here that
    # the contract does not carry would fail `model_validate` at run time — this
    # fails it at collection time instead.
    columns = {column.strip() for column in _returning(users._INSERT_USER).split(",")}

    assert columns == set(User.model_fields)


def test_the_write_folds_the_address_in_postgres() -> None:
    # The column is written `lower(%s)`, not `%s`. That is what makes
    # `CHECK (email = lower(email))` unfailable — the value stored is by
    # construction the value the constraint compares against — instead of
    # depending on `str.lower()` and the server's collation reaching the same
    # answer on input neither of them was written against.
    #
    # Asserted over the statement's text because the behavioural case above
    # cannot fail on a `C.UTF-8` cluster: without this, reverting the fix is a
    # silent edit that the whole suite stays green through.
    statement = " ".join(users._INSERT_USER.split())

    assert "VALUES (%s, lower(%s), %s, %s," in statement


def test_the_write_states_both_product_rules_itself() -> None:
    # `active` and `must_change_password` are FR-11 and FR-2, written into the
    # statement rather than left to the column defaults: a default is a schema
    # fact a later migration may change, and these are product rules.
    statement = " ".join(users._INSERT_USER.split())

    assert "active, must_change_password, temp_credential_expires_at)" in statement
    assert "true, true, now() + make_interval(hours => %s))" in statement
