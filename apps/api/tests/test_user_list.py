"""`GET /admin/users` — FR-10, every row of Story 1.9's I/O matrix.

The authorization *guard* lives in `test_admin_authorization.py`, which holds the
role check to the route table in both directions and now covers this route
without being taught about it — that is the property it was written for. This
file is about the read: what it returns, in what order, and the two things
nothing else in the suite can see — that the list is *every* account rather than
a filtered view of one, and that its column list has not drifted from the write
sitting beside it in `api/users.py`.

FR-4's lock is rendered from this body and decided from nothing: `locked_until`
is status, never enforcement (`shared_schema.user`), so the only claim made here
is that the value reaches the wire as a UTC timestamp. The unlock is Story
1.10's (DW-64).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from api import users
from api.dependencies import ADMINISTRATOR_REQUIRED, PASSWORD_CHANGE_REQUIRED, UNAUTHORIZED
from fastapi.testclient import TestClient
from shared_schema.user import Role, User

LIST_USERS = "/admin/users"
LOGIN = "/auth/login"

MakeUser = Callable[..., Any]


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    """A claimed Administrator, signed in on `client`.

    `make_user(role=Role.ADMIN)` already produces one — `must_change_password`
    defaults to `False` there — so the fixture is only the sign-in.
    """
    account = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(client, account)
    return account


def _listed(client: TestClient) -> list[dict[str, Any]]:
    response = client.get(LIST_USERS)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    return body


def _by_email(body: list[dict[str, Any]], email: str) -> dict[str, Any]:
    matches = [row for row in body if row["email"] == email]
    assert len(matches) == 1, f"{email} appears {len(matches)} times in the list"
    return matches[0]


# --- The list itself ----------------------------------------------------------


def test_an_administrator_lists_every_account(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The acceptance clause, in one test: the caller's own row, a deactivated
    # one, one that has never signed in, and one carrying a live lock. A filter
    # on any of the four would be a lie about who has access.
    deactivated = make_user(active=False, name="Kasun Perera")
    never_signed_in = make_user(name="Nadeesha Silva")
    locked = make_user(name="Bimal Fernando")
    conn.execute(
        "UPDATE users SET locked_until = now() + interval '15 minutes' WHERE id = %s",
        (locked.id,),
    )

    body = _listed(client)

    assert len(body) == 4
    assert {row["email"] for row in body} == {
        administrator.email,
        deactivated.email,
        never_signed_in.email,
        locked.email,
    }


def test_the_callers_own_row_is_in_the_list(client: TestClient, administrator: Any) -> None:
    # On purpose. An Administrator auditing who has access is one of the people
    # who has it, and a list that quietly omitted the reader would be answering a
    # different question from the one FR-10 asks.
    assert _by_email(_listed(client), administrator.email)["role"] == Role.ADMIN.value


def test_a_deactivated_account_is_listed_with_its_status(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # FR-10: "a deactivated user is visually distinct, no separate screen needed"
    # — which needs the row present and the flag on it, not the row removed.
    deactivated = make_user(active=False, name="Kasun Perera")

    assert _by_email(_listed(client), deactivated.email)["active"] is False


def test_an_account_that_has_never_signed_in_reads_null(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    fresh = make_user(name="Nadeesha Silva")

    assert _by_email(_listed(client), fresh.email)["last_login_at"] is None


def test_the_last_login_is_populated_once_the_account_signs_in(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # The other half of the same clause, and the one that proves the column is
    # the live one rather than a null the list always renders.
    other = make_user(name="Nadeesha Silva")
    assert _by_email(_listed(client), other.email)["last_login_at"] is None

    # Signing in as them replaces the Administrator's cookie on this client's
    # jar, so the Administrator signs back in before reading the list again.
    _sign_in(client, other)
    _sign_in(client, administrator)

    assert _by_email(_listed(client), other.email)["last_login_at"] is not None


def test_an_unclaimed_account_is_listed_with_its_deadline(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # A row provisioned a moment ago and not yet claimed. It is somebody who has
    # access, so it is on the list.
    deadline = datetime.now(UTC) + timedelta(hours=72)
    unclaimed = make_user(
        must_change_password=True, temp_credential_expires_at=deadline, name="Amal Perera"
    )

    row = _by_email(_listed(client), unclaimed.email)

    assert row["must_change_password"] is True
    assert row["temp_credential_expires_at"] is not None


def test_a_lock_reaches_the_wire_as_a_utc_timestamp(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # FR-4's lock, rendered. Written straight to the column because `make_user`
    # cannot set it and because ten failed sign-ins are `test_login_throttle.py`'s
    # subject, not this file's. Status only: nothing here decides anything from
    # the value, and neither does the screen that renders it.
    locked = make_user(name="Bimal Fernando")
    conn.execute(
        "UPDATE users SET locked_until = now() + interval '15 minutes' WHERE id = %s",
        (locked.id,),
    )

    value = _by_email(_listed(client), locked.email)["locked_until"]

    assert value is not None
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(0)
    assert parsed > datetime.now(UTC)


def test_a_lapsed_lock_is_still_reported_rather_than_cleared(
    client: TestClient, conn: psycopg.Connection, administrator: Any, make_user: MakeUser
) -> None:
    # The column is history as much as state (`shared_schema.user`): a value in
    # the past means "locked recently", and the API neither clears it nor hides
    # it. Deciding it is not a lock any more is the reader's job.
    lapsed = make_user(name="Bimal Fernando")
    conn.execute(
        "UPDATE users SET locked_until = now() - interval '1 hour' WHERE id = %s",
        (lapsed.id,),
    )

    value = _by_email(_listed(client), lapsed.email)["locked_until"]

    assert value is not None
    assert datetime.fromisoformat(value) < datetime.now(UTC)


# --- Order --------------------------------------------------------------------


def test_the_order_is_by_name_ignoring_case(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # Inserted in the wrong order on purpose. Postgres's `C` collation orders by
    # code point, which files every lowercase name after every uppercase one —
    # `ruwan` after `Zoya` — and a list nobody can scan is a list that does not
    # answer "who has access".
    make_user(name="Zoya")
    make_user(name="ruwan")
    make_user(name="Amal")

    names = [row["name"] for row in _listed(client)]

    assert names == sorted(names, key=str.lower)
    assert names.index("ruwan") < names.index("Zoya")


def test_two_people_sharing_a_name_are_ordered_by_address(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # `email` is the tie-break because it is the table's only unique non-opaque
    # column: without it two rows with one name come back in whatever order the
    # planner felt like, and the list is not reproducible between reloads.
    first = make_user(name="Kasun Perera")
    second = make_user(name="Kasun Perera")

    listed = [row["email"] for row in _listed(client) if row["name"] == "Kasun Perera"]

    assert listed == sorted([first.email, second.email])


# --- The shape of the body ----------------------------------------------------


def test_every_element_is_the_shared_user_contract(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # `isUser` in the TypeScript twin rejects an element carrying any key beyond
    # the contract, and `User.model_validate` has already refused one on the way
    # out. Asserted per element rather than over the first, because a list is the
    # one shape where a single malformed row can hide behind ten good ones.
    make_user(name="Kasun Perera")

    for row in _listed(client):
        assert set(row) == set(User.model_fields)


def test_no_element_carries_a_digest(
    client: TestClient, administrator: Any, make_user: MakeUser
) -> None:
    # `User` has no `password_hash` field, so this cannot happen without the
    # contract changing — which is exactly why it is asserted over the raw text
    # as well as over the keys. This body names every account in the product.
    make_user(name="Kasun Perera")

    response = client.get(LIST_USERS)

    assert all("password_hash" not in row for row in response.json())
    assert "password_hash" not in response.text


def test_the_list_is_never_stored(client: TestClient, administrator: Any) -> None:
    # Every authenticated response carries it, and more so this one: a cached
    # roster served to the next person on a shared shop-floor tablet is the whole
    # failure mode `NO_STORE` exists for.
    assert client.get(LIST_USERS).headers["cache-control"] == "no-store"


def test_the_body_is_a_bare_array(client: TestClient, administrator: Any) -> None:
    # Not `{"users": [...]}`. There is no cursor, no total and no page to carry,
    # and a wrapper invented to leave room for one is a shape the product would
    # have to keep honouring after pagination never arrives.
    assert isinstance(client.get(LIST_USERS).json(), list)


# --- Refusals -----------------------------------------------------------------


def test_a_staff_caller_is_refused_and_sees_no_row(client: TestClient, make_user: MakeUser) -> None:
    # From the dependency, before the handler runs — so nothing it would have
    # returned can leak. `403`, never `401`: a 401 would fire `apps/web`'s
    # unauthorized observer and sign a perfectly good session out.
    staff = make_user(role=Role.STAFF, name="Kasun Perera")
    other = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(client, staff)

    response = client.get(LIST_USERS)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED
    assert set(response.json()) == {"error"}
    assert other.email not in response.text


def test_an_administrator_on_a_temporary_credential_is_refused_by_the_gate(
    client: TestClient, make_user: MakeUser
) -> None:
    # The gate fires before the role check, because `require_administrator`
    # chains on `require_claimed_user`. An Administrator holding a note-borne
    # credential cannot read the roster with it.
    deadline = datetime.now(UTC) + timedelta(hours=72)
    unclaimed = make_user(
        role=Role.ADMIN, must_change_password=True, temp_credential_expires_at=deadline
    )
    _sign_in(client, unclaimed)

    response = client.get(LIST_USERS)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == PASSWORD_CHANGE_REQUIRED


def test_an_unauthenticated_caller_is_refused(client: TestClient) -> None:
    response = client.get(LIST_USERS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == UNAUTHORIZED


def test_an_administrator_deactivated_mid_session_is_refused_as_unauthenticated(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AGENTS.md Policy: deactivating a user never leaves a session live. AD-3's
    # one session lookup re-reads `active` per request, so the roster closes on
    # the very next request with no sign-out in between.
    assert client.get(LIST_USERS).status_code == 200

    conn.execute("UPDATE users SET active = false WHERE id = %s", (administrator.id,))

    refused = client.get(LIST_USERS)
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == UNAUTHORIZED


def test_a_demotion_closes_the_list_on_the_next_request(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    assert client.get(LIST_USERS).status_code == 200

    conn.execute("UPDATE users SET role = %s WHERE id = %s", (Role.STAFF.value, administrator.id))

    refused = client.get(LIST_USERS)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == ADMINISTRATOR_REQUIRED


# --- The statement itself -----------------------------------------------------


#: Both readers below collapse runs of whitespace before comparing, and the
#: reason is worth stating: the guard is about *column drift*, not about layout.
#: `RETURNING` and `SELECT` are different lengths, so a continuation line aligned
#: under one keyword cannot also be aligned under the other — comparing the
#: literal text would oblige one of the two statements to carry an indent that
#: makes no sense where it is written, and would fail on a reformat that changed
#: no column at all.
def _normalized(clause: str) -> str:
    """A column list with every run of whitespace collapsed to one space."""
    return " ".join(clause.split())


def _returning(statement: str) -> str:
    """The `RETURNING` clause of a statement, normalized."""
    head, separator, clause = statement.partition("RETURNING")
    assert separator, "the statement has no RETURNING clause"
    return _normalized(clause)


def _selected(statement: str) -> str:
    """The column list of a `SELECT`, normalized."""
    head, separator, rest = statement.partition("SELECT")
    assert separator, "the statement has no SELECT"
    columns, separator, _ = rest.partition("FROM")
    assert separator, "the statement has no FROM"
    return _normalized(columns)


def test_the_selected_columns_have_not_drifted_from_the_write() -> None:
    # Parsed from the module's own source rather than retyped, so this cannot
    # pass by two lists being wrong in the same way. They are repeated in the
    # source rather than shared through a constant because
    # `test_source_guards.py` forbids a statement assembled from a value — this
    # is what holds them together instead, and `test_create_user.py` holds the
    # write's list to the three writers in `api.auth`.
    assert _selected(users._SELECT_USERS) == _returning(users._INSERT_USER)


def test_the_selected_columns_name_exactly_the_contract() -> None:
    # Identical to the write's list is worth nothing if both are wrong. `User`
    # has no `password_hash` field, so a column added here that the contract does
    # not carry would fail `model_validate` at run time — this fails it at
    # collection time instead.
    columns = {column.strip() for column in _selected(users._SELECT_USERS).split(",")}

    assert columns == set(User.model_fields)


def test_the_read_is_every_account_with_no_filter_and_no_page() -> None:
    # Asserted over the statement's text as well as behaviourally above, because
    # a `LIMIT` added later is invisible to a test that only ever creates four
    # users — the suite would stay green while the surface answering "who has
    # access" started answering "some of them".
    #
    # `FETCH FIRST` is named beside `LIMIT` because it is the standard spelling
    # of the same clause and a guard that missed it would be a guard against one
    # way of writing the mistake.
    statement = " ".join(users._SELECT_USERS.split()).upper()

    assert "WHERE" not in statement
    assert "LIMIT" not in statement
    assert "OFFSET" not in statement
    assert "FETCH" not in statement

    # The parameter check reads the *un*-uppercased statement: psycopg's named
    # placeholder is `%(name)s`, and uppercasing it produces `%(NAME)S`, which
    # contains no `%s` at all. Both spellings are checked, because either one is
    # a value reaching a statement whose whole claim is that it takes none.
    written = " ".join(users._SELECT_USERS.split())

    assert "%s" not in written
    assert "%(" not in written


def test_the_order_is_stated_by_the_statement() -> None:
    # The behavioural ordering tests above can only fail on a cluster whose
    # collation makes them fail; this one fails anywhere.
    statement = " ".join(users._SELECT_USERS.split())

    assert "ORDER BY lower(name), email" in statement
