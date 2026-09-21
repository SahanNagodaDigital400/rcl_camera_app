"""`GET /admin/audit` — FR-21, every row of Story 1.13's I/O matrix.

The authorization *guard* lives in `test_admin_authorization.py`, which holds
the role check to the route table in both directions and covers this route
without being taught about it — that is the property it was written for. The
append-only guarantee lives in `test_audit_immutability.py`, which is about a
`GRANT` rather than about any code here. This file is about the read: what it
returns, in what order, how it pages, and the things nothing else in the suite
can see — that the order has a *total* order to page through, that a page
boundary neither repeats a row nor skips one, and that an entry whose `action`
this build has never heard of is still served.

**The log is never empty by the time a test runs**, because signing the
Administrator in writes the first entry. That is why almost every test here
takes its expected order from the table itself (`audit_rows`, oldest first,
reversed) rather than from a list written out by hand: the oracle is the whole
table in the order the statement claims, and the assertion is that the route
returns exactly that.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from api import audit
from api.audit import AUDIT_ENTRY_NOT_FOUND, PAGE_SIZE
from api.dependencies import (
    ADMINISTRATOR_REQUIRED,
    PASSWORD_CHANGE_REQUIRED,
    UNAUTHORIZED,
    require_administrator,
)
from api.sessions import SESSION_COOKIE_NAME
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from shared_schema.audit import CURSOR_PARAM, AuditAction, AuditLogEntry
from shared_schema.user import Role

READ_AUDIT = "/admin/audit"
LOGIN = "/auth/login"

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, Any]]]

#: Arranged directly as the table owner, which is the only way to write an
#: entry this product's own code would never write: a `created_at` of our
#: choosing (so ordering is asserted against known instants rather than
#: whatever two inserts happened to collide on), and an `action` outside
#: `AuditAction` (so the read's refusal to narrow it is provable). `api.audit`
#: is deliberately not used — it is the code under test on the write side, and
#: a fixture that went through it could not express either case.
_ARRANGE_ENTRY = """
INSERT INTO audit_log (created_at, action, actor_user_id, actor_email,
                       target_user_id, target_email, source_ip, details)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

#: Emptying the log, as the owner, to arrange the one state a signed-in
#: Administrator cannot otherwise be in: a table with no rows. The sign-in that
#: authenticates every test here writes the first entry, so "the log is empty"
#: has to be staged after authentication or not at all.
#:
#: **This is the superuser `conn`, never `app_role_conn`.** The product's own
#: role is refused this statement by PostgreSQL, which is what
#: `test_audit_immutability.py` proves; arranging state as the owner is what
#: `conftest.py`'s own docstring says that fixture is for.
_EMPTY_THE_LOG = "DELETE FROM audit_log"


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    """A claimed Administrator, signed in on `client`.

    `make_user(role=Role.ADMIN)` already produces one — `must_change_password`
    defaults to `False` there — so the fixture is only the sign-in. That
    sign-in is also the log's first entry, which every test here accounts for.
    """
    account = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(client, account)
    return account


def _arrange(
    conn: psycopg.Connection,
    count: int,
    *,
    first_at: datetime | None = None,
    step: timedelta = timedelta(seconds=1),
    action: str = AuditAction.LOGIN_SUCCEEDED.value,
    actor_user_id: str | None = None,
    actor_email: str | None = "ruwan@rocell.lk",
    target_user_id: str | None = None,
    target_email: str | None = "kasun@rocell.lk",
    source_ip: str | None = "127.0.0.1",
    details: dict[str, Any] | None = None,
) -> list[str]:
    """`count` entries, oldest first, each `step` newer than the last.

    `first_at` defaults to a minute in the future so every arranged row is
    newer than the sign-in the fixture above wrote — the arrangement then sits
    at the top of the newest-first order, where a page boundary is easiest to
    reason about.

    `actor_user_id` and `target_user_id` default to `None` because most rows
    here only need the address half, but they are parameters rather than
    hard-coded nulls: with them fixed, every assertion that an id serializes as
    `null` held for any row this helper could produce and proved nothing about
    the case it named. There is no foreign key on either column (AD-10 stores a
    snapshot pair, not a reference), so any UUID is a valid value here.

    Returns the ids in the order they were written, so `reversed(...)` is the
    order the route must answer in.
    """
    base = first_at if first_at is not None else datetime.now(UTC) + timedelta(minutes=1)
    written: list[str] = []
    for index in range(count):
        row = conn.execute(
            _ARRANGE_ENTRY,
            (
                base + step * index,
                action,
                actor_user_id,
                actor_email,
                target_user_id,
                target_email,
                source_ip,
                Jsonb(details if details is not None else {"index": index}),
            ),
        ).fetchone()
        assert row is not None
        written.append(str(row["id"]))
    return written


def _every_value(entries: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    """Every (field, value) pair on the wire, `details` flattened one level.

    So a credential assertion can name the field it fires on rather than being
    a substring sweep over the whole serialized body, where the `action`
    column's own vocabulary is indistinguishable from a leak.
    """
    pairs: list[tuple[str, Any]] = []
    for entry in entries:
        for field, value in entry.items():
            if field == "details" and isinstance(value, dict):
                pairs.extend((f"details.{key}", inner) for key, inner in value.items())
            else:
                pairs.append((field, value))
    return pairs


def _expected_order(conn: psycopg.Connection, audit_rows: AuditRows) -> list[str]:
    """Every id in the table, newest first — the order the statement claims.

    `audit_rows` reads `ORDER BY created_at, id` (both ascending), so reversing
    it is exactly `ORDER BY created_at DESC, id DESC`. Taking the oracle from
    the table rather than from a hand-written list is what lets these tests
    ignore the sign-in entry they did not arrange.
    """
    return [str(row["id"]) for row in reversed(audit_rows(conn))]


def _read(client: TestClient, before: str | None = None) -> list[dict[str, Any]]:
    path = READ_AUDIT if before is None else f"{READ_AUDIT}?before={before}"
    response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return body


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["id"] for entry in entries]


# --- The order ----------------------------------------------------------------


def test_the_first_page_is_newest_first(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    _arrange(conn, 3)

    assert _ids(_read(client)) == _expected_order(conn, audit_rows)


def test_two_entries_sharing_a_created_at_are_ordered_by_id_descending(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The tiebreaker, and the reason it exists. `created_at` defaults to
    # `now()`, which is the *transaction* timestamp, so two entries written by
    # one request — a deactivation and the revocation beside it — share it to
    # the microsecond. With `ORDER BY created_at DESC` alone the planner may
    # return them in either order, which means no stable page boundary at all.
    # Arranged with an identical instant rather than by hoping two inserts
    # collide, so this fails deterministically when the tiebreaker is removed.
    shared = datetime.now(UTC) + timedelta(minutes=1)
    written = _arrange(conn, 2, first_at=shared, step=timedelta(0))

    top = _ids(_read(client))[:2]

    assert set(top) == set(written)
    assert top == sorted(written, reverse=True)


def test_the_statement_and_not_the_handler_decides_the_order(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # Written in a shuffled order of `created_at`, so a handler that returned
    # rows in insertion order — or sorted them itself on something else —
    # disagrees with the oracle.
    base = datetime.now(UTC) + timedelta(minutes=1)
    for offset in (5, 1, 9, 3, 7):
        _arrange(conn, 1, first_at=base + timedelta(seconds=offset))

    assert _ids(_read(client)) == _expected_order(conn, audit_rows)


# --- Paging -------------------------------------------------------------------


def test_a_full_page_holds_the_server_s_page_size_and_no_more(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    _arrange(conn, PAGE_SIZE + 10)

    assert len(_read(client)) == PAGE_SIZE


def test_the_next_page_repeats_nothing_and_skips_nothing(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The whole point of the keyset. The boundary deliberately falls in the
    # middle of the arranged run, and the two pages together must be the table
    # in the statement's order — no row twice, no row missing.
    _arrange(conn, PAGE_SIZE + 10)
    expected = _expected_order(conn, audit_rows)

    first = _ids(_read(client))
    second = _ids(_read(client, before=first[-1]))

    assert first + second == expected
    assert len(set(first + second)) == len(expected)


def test_a_page_boundary_between_two_entries_sharing_a_created_at_loses_neither(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The acceptance clause's hardest case: a page that ends between two
    # entries written by one request. `created_at` alone cannot separate them,
    # so a cursor compared on the timestamp would either serve the second one
    # twice or drop it. Arranged as one instant shared by every row in the run,
    # which makes the *whole* order depend on the `id` tiebreaker.
    shared = datetime.now(UTC) + timedelta(minutes=1)
    _arrange(conn, PAGE_SIZE + 5, first_at=shared, step=timedelta(0))
    expected = _expected_order(conn, audit_rows)

    first = _ids(_read(client))
    second = _ids(_read(client, before=first[-1]))

    assert first + second == expected
    assert len(set(first + second)) == len(expected)


def test_a_second_page_is_also_capped_at_the_page_size(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The `LIMIT` on `_SELECT_ENTRIES_BEFORE`, exercised at its boundary.
    # Every other cursor test in this file arranges fewer than `PAGE_SIZE`
    # rows behind the cursor, so deleting `LIMIT %s` from that statement
    # would fail only the statement-text guard below — the behaviour would
    # look identical while the second page quietly became the whole rest of
    # the table.
    _arrange(conn, PAGE_SIZE * 2 + 5)

    first = _ids(_read(client))
    second = _ids(_read(client, before=first[-1]))

    assert len(first) == PAGE_SIZE
    assert len(second) == PAGE_SIZE


def test_an_entry_written_between_two_reads_shifts_nothing(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # **The reason this pages by keyset and not by `OFFSET`.** Entries land at
    # the *top* of this order between two requests — every sign-in writes one
    # — so `OFFSET 50` after a page of fifty would re-serve a row already
    # read, one for every entry written in between. The cursor compares
    # against a specific row instead, which is stable under insertion.
    #
    # Arranged as a real interleaving: read page one, write an entry newer
    # than everything on it, then read page two. Under `OFFSET` the last row
    # of page one would reappear at the top of page two; under the keyset it
    # cannot, and the new entry is simply not in either page because it is
    # newer than the cursor.
    _arrange(conn, PAGE_SIZE + 10)

    first = _ids(_read(client))
    interloper = _arrange(conn, 1, first_at=datetime.now(UTC) + timedelta(hours=1))[0]
    second = _ids(_read(client, before=first[-1]))

    assert len(first) == PAGE_SIZE
    assert set(first).isdisjoint(second), "a row was served on both pages"
    assert interloper not in first + second

    # And nothing older than the cursor was skipped either: the two pages are
    # the whole table minus the interloper, in the statement's order. A fresh
    # first read now leads with the interloper, which is where an entry
    # written after the paging began belongs — and why it was in neither page.
    everything = _expected_order(conn, audit_rows)
    assert everything[0] == interloper
    assert first + second == [entry for entry in everything if entry != interloper]


def test_the_cursor_at_the_oldest_entry_answers_an_empty_page(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # Exhausted, not missing: `200 []`, which is how the client learns to stop
    # offering more.
    _arrange(conn, 3)
    oldest = _expected_order(conn, audit_rows)[-1]

    assert _read(client, before=oldest) == []


def test_the_client_cannot_choose_the_page_size(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # A `limit` query parameter is not declared, so FastAPI ignores the name
    # entirely rather than honouring it. Asserted because the failure mode is
    # silent: a route that grew one would answer this request with 500 rows and
    # nothing else in the suite would notice.
    _arrange(conn, PAGE_SIZE + 10)

    response = client.get(f"{READ_AUDIT}?limit=500")

    assert response.status_code == 200
    assert len(response.json()) == PAGE_SIZE


# --- The cursor's two failures ------------------------------------------------


def test_a_cursor_naming_no_entry_is_refused(client: TestClient, administrator: Any) -> None:
    # Distinguished from an exhausted log, which is `[]`. The table has no
    # delete path, so a cursor that ever resolved resolves forever — a `404`
    # here can only mean the id was invented.
    response = client.get(f"{READ_AUDIT}?before={uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == AUDIT_ENTRY_NOT_FOUND
    # The refusal is `no-store` too, as the sibling routes' own 404s are. It is
    # raised as an `ApiError` and rendered by `api.main`'s handler, which never
    # sees the `Response` object the success path writes the header onto — so
    # this header comes from `_audit_entry_not_found`'s own `headers=NO_STORE`
    # and from nothing else. Dropping it would leave a cookie-gated answer
    # about the audit log heuristically cacheable by an intermediary.
    assert response.headers["cache-control"] == "no-store"


def test_a_cursor_that_is_not_a_uuid_is_refused(client: TestClient, administrator: Any) -> None:
    response = client.get(f"{READ_AUDIT}?before=nonsense")

    assert response.status_code == 422
    # The shared envelope from `api.main`'s validation handler, not FastAPI's
    # own `{"detail": ...}`.
    assert response.json()["error"]["code"] == "validation_error"


def test_an_exhausted_log_and_an_invented_cursor_are_not_the_same_answer(
    client: TestClient, conn: psycopg.Connection, administrator: Any, audit_rows: AuditRows
) -> None:
    # The pair, asserted together: collapsing them would turn a client bug — or
    # a hand-typed id — into a silently empty screen that looks like the end of
    # the log.
    _arrange(conn, 2)
    oldest = _expected_order(conn, audit_rows)[-1]

    assert client.get(f"{READ_AUDIT}?before={oldest}").status_code == 200
    assert client.get(f"{READ_AUDIT}?before={uuid4()}").status_code == 404


# --- The empty log ------------------------------------------------------------


def test_an_empty_log_is_an_empty_array(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Staged as the table owner after the sign-in that authenticates the
    # request, because there is no other way to be a signed-in Administrator
    # looking at a log with nothing in it. Unreachable in the product — the
    # reader's own sign-in is always in there — and rendered anyway, because a
    # bare header with nothing under it reads as a screen that failed.
    conn.execute(_EMPTY_THE_LOG)

    response = client.get(READ_AUDIT)

    assert response.status_code == 200
    assert response.json() == []


# --- What an entry carries ----------------------------------------------------


def test_an_entry_with_no_actor_serializes_both_halves_as_null(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # An unknown-account sign-in attempt: nobody is known, so the entry says
    # so. Rendering it as the target — or as an invented principal — would be
    # the log asserting something it was never told.
    _arrange(
        conn,
        1,
        action=AuditAction.LOGIN_FAILED.value,
        actor_email=None,
        target_email="nobody@rocell.lk",
    )

    newest = _read(client)[0]

    assert newest["actor_user_id"] is None
    assert newest["actor_email"] is None
    assert newest["target_email"] == "nobody@rocell.lk"


def test_an_entry_with_an_actor_serializes_both_id_halves(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The contrast the test above needs to mean anything: `actor_user_id` and
    # `target_user_id` are two of the nine contract fields, and until this
    # arranged a row that *has* them, no test in this file ever wrote a
    # non-null value into either — so "serializes as null" was true of every
    # row the helper could produce rather than of the case being named.
    actor, target = str(uuid4()), str(uuid4())
    _arrange(
        conn,
        1,
        action=AuditAction.USER_EDITED.value,
        actor_user_id=actor,
        target_user_id=target,
    )

    newest = _read(client)[0]

    assert newest["actor_user_id"] == actor
    assert newest["target_user_id"] == target


def test_an_entry_with_no_recorded_address_serializes_as_null(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    _arrange(conn, 1, source_ip=None)

    assert _read(client)[0]["source_ip"] is None


def test_an_action_outside_the_vocabulary_is_served_verbatim(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The column has no CHECK by design, the vocabulary grows with Epics 2 and
    # 3, and AD-4's correction mechanism is an entry inserted by hand. A read
    # that refused to serve a value it did not recognise would make the one
    # table that can never be rewritten have a viewer that hides parts of it.
    _arrange(conn, 1, action="catalogue_tile_added")

    assert _read(client)[0]["action"] == "catalogue_tile_added"


def test_nested_details_round_trip(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    changed = {"changed": {"role": {"from": "staff", "to": "admin"}}}
    _arrange(conn, 1, action=AuditAction.USER_EDITED.value, details=changed)

    assert _read(client)[0]["details"] == changed


def test_every_element_satisfies_the_shared_contract(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The same gate the handler puts each row through, applied to what actually
    # reached the wire: a column added to the table and forgotten in the
    # contract would arrive as an extra key and fail here.
    _arrange(conn, 3)

    for entry in _read(client):
        assert set(entry) == set(AuditLogEntry.model_fields)
        AuditLogEntry.model_validate(entry)


def test_the_body_is_a_bare_array(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # Mirrors `GET /admin/users`. The envelope everywhere in this product is
    # the *error* envelope; every success body is the thing itself.
    _arrange(conn, 2)

    body = client.get(READ_AUDIT).json()

    assert isinstance(body, list)


def test_the_response_is_never_stored(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # This body is the record of who did what, read on a shared desk.
    _arrange(conn, 1)

    assert client.get(READ_AUDIT).headers["cache-control"] == "no-store"


def test_no_credential_material_reaches_the_body(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # `AuditLogEntry` has no field a digest or a token could occupy, and
    # `record`'s own rule keeps both out of `details` — asserted over the
    # serialized body rather than over the model, because the claim is about
    # what leaves the process.
    _arrange(conn, 3)
    # Arranged deliberately: this is the row that makes the assertion below
    # load-bearing rather than incidentally true.
    _arrange(conn, 1, action=AuditAction.PASSWORD_CHANGED.value)
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token, "the fixture is not signed in, so this assertion proves nothing"

    entries = _read(client)
    body = json.dumps(entries)

    # **Not a `"password" not in body` sweep.** Three members of `AuditAction`
    # are `password_claimed`, `password_changed` and `password_change_refused`,
    # so the substring is a legitimate value of the `action` column: the sweep
    # passed only because no test here happened to arrange one of those rows,
    # and would have failed on a correct body the moment one did. The claim is
    # about credential *material*, so it is asserted over the markers material
    # would actually carry.
    assert "$argon2" not in body
    assert token not in body
    for field, value in _every_value(entries):
        assert "password" not in str(value).lower() or field == "action", (field, value)


# --- Who may read it ----------------------------------------------------------


def test_a_staff_caller_is_refused_and_sees_no_entry(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    _arrange(conn, 2)
    _sign_in(client, make_user(role=Role.STAFF))

    response = client.get(READ_AUDIT)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED
    # The refusal carries the envelope and nothing else: no array, no entry,
    # no count of what was withheld.
    assert set(response.json()) == {"error"}


def test_an_administrator_on_a_temporary_credential_is_refused_by_the_gate(
    client: TestClient, make_user: MakeUser
) -> None:
    # The forced-change gate, which `require_administrator` chains on — so a
    # credential that travelled by note cannot read the log either.
    account = make_user(
        role=Role.ADMIN,
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _sign_in(client, account)

    response = client.get(READ_AUDIT)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == PASSWORD_CHANGE_REQUIRED


def test_an_unauthenticated_caller_is_refused(client: TestClient) -> None:
    response = client.get(READ_AUDIT)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == UNAUTHORIZED


def test_a_demotion_closes_the_surface_on_the_very_next_request(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AD-3: `lookup_session` re-reads the role from Postgres on every request
    # and nothing is cached at sign-in, so no sign-out and no new sign-in sits
    # between the change and the refusal.
    assert client.get(READ_AUDIT).status_code == 200

    conn.execute("UPDATE users SET role = %s WHERE id = %s", (Role.STAFF.value, administrator.id))

    refused = client.get(READ_AUDIT)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == ADMINISTRATOR_REQUIRED


# --- The statements themselves ------------------------------------------------
#
# Behavioural tests above can only fail on data a test happened to arrange: a
# `WHERE` added to the read is invisible to a suite whose rows all match it,
# and a `LIMIT` formatted from a value passes every assertion about how many
# rows come back. These fail anywhere, and they are what
# `test_user_list.py`'s statement section is to `GET /admin/users`.

PAGE_STATEMENTS = (
    ("_SELECT_LATEST_ENTRIES", audit._SELECT_LATEST_ENTRIES),
    ("_SELECT_ENTRIES_BEFORE", audit._SELECT_ENTRIES_BEFORE),
)

ALL_STATEMENTS = (*PAGE_STATEMENTS, ("_SELECT_ENTRY_EXISTS", audit._SELECT_ENTRY_EXISTS))


def _normalized(clause: str) -> str:
    """A fragment with every run of whitespace collapsed to one space."""
    return " ".join(clause.split())


def _selected(statement: str) -> str:
    """The column list of the outermost `SELECT`, normalized."""
    head, separator, rest = statement.partition("SELECT")
    assert separator, "the statement has no SELECT"
    columns, separator, _ = rest.partition("FROM")
    assert separator, "the statement has no FROM"
    return _normalized(columns)


@pytest.mark.parametrize(("name", "statement"), PAGE_STATEMENTS)
def test_the_selected_columns_name_exactly_the_contract(name: str, statement: str) -> None:
    # Parsed from the module's own source rather than retyped, so a column
    # added to the table and not to `AuditLogEntry` fails at collection time
    # instead of reaching the wire as an extra key. The two page statements
    # carry the same list, which is what keeps a change to one from quietly
    # applying to only the first page.
    columns = {column.strip() for column in _selected(statement).split(",")}

    assert columns == set(AuditLogEntry.model_fields), name


def test_both_page_statements_select_the_same_columns() -> None:
    latest, before = (_selected(statement) for _, statement in PAGE_STATEMENTS)

    assert latest == before


@pytest.mark.parametrize(("name", "statement"), PAGE_STATEMENTS)
def test_the_order_and_its_tiebreaker_are_stated_by_the_statement(
    name: str, statement: str
) -> None:
    # The behavioural ordering tests can pass on a run where the planner
    # happened to return rows in the right order; this one fails anywhere.
    assert "ORDER BY created_at DESC, id DESC" in _normalized(statement), name


@pytest.mark.parametrize(("name", "statement"), PAGE_STATEMENTS)
def test_the_page_size_is_a_parameter_and_not_a_number(name: str, statement: str) -> None:
    # `LIMIT %s`, never `LIMIT 50` formatted in. `PAGE_SIZE` is ours and could
    # safely be interpolated; interpolating it would be the habit
    # `test_source_guards.py` exists to stop before it reaches a value that is
    # not ours.
    written = _normalized(statement)

    assert "LIMIT %s" in written, name
    assert "OFFSET" not in written.upper(), name


def test_the_cursor_is_compared_as_a_whole_pair_strictly() -> None:
    # `<`, not `<=`: the cursor names the last row already rendered, so `<=`
    # repeats it at the top of every page. And the pair, not the timestamp
    # alone, which is the comparison that has a total order.
    written = _normalized(audit._SELECT_ENTRIES_BEFORE)

    assert "WHERE (created_at, id) < (SELECT created_at, id FROM audit_log WHERE id = %s)" in (
        written
    )


@pytest.mark.parametrize(("name", "statement"), ALL_STATEMENTS)
def test_no_read_statement_mutates_anything(name: str, statement: str) -> None:
    # AD-4, stated over this story's own statements as well as over the grant.
    # `test_source_guards.py` scans the whole module for the same three verbs;
    # this says it of the three constants by name, so deleting that guard does
    # not silently take this claim with it.
    written = _normalized(statement).upper()

    for verb in ("UPDATE", "DELETE", "TRUNCATE", "INSERT"):
        assert verb not in written, (name, verb)


def test_the_route_reads_the_cursor_under_the_shared_name() -> None:
    # The server's half of the wire contract. FastAPI reads the query string
    # with the *parameter's name*, so `before` here and `AUDIT_CURSOR_PARAM` in
    # `ts/audit.ts` are two literals in two languages with nothing between
    # them; `shared_schema.audit.CURSOR_PARAM` is what both now point at, and
    # `shared/schema/tests/test_audit.py` pins the twin to it from the other
    # side.
    #
    # Worth a test of its own rather than left to the behavioural paging tests:
    # an unknown query parameter is *ignored*, not refused, so a rename here
    # would keep answering `200` with the first page to every Load more. The
    # screen would repeat its newest fifty rows forever and nothing would raise.
    signature = inspect.signature(audit.read_audit_log)

    assert CURSOR_PARAM in signature.parameters


def test_the_route_declares_the_role_check_and_lives_under_admin() -> None:
    # Restated here as a sentence about this story rather than left to
    # `test_admin_authorization.py`'s table walk: the path is what the
    # authorization boundary is read off, so the path is worth asserting where
    # somebody reading this file will see it.
    #
    # **Both halves, not only the path.** The dependency tree is walked the way
    # `test_admin_authorization.py:_declares` walks it — the check may be
    # declared directly, through `dependencies=[...]`, or behind another
    # dependency that wraps it, and all three are the route declaring it. The
    # earlier form of this test asserted `READ_AUDIT.startswith("/admin/")`,
    # which is a tautology over this file's own literal: it stayed green with
    # `Depends(require_administrator)` deleted, while claiming in its name to
    # be the thing that would catch that.
    routes = list(audit.router.routes)
    paths = {route.path for route in routes}  # type: ignore[attr-defined]

    assert paths == {READ_AUDIT}
    assert READ_AUDIT.startswith("/admin/")

    pending = [
        dependant
        for route in routes
        for dependant in route.dependant.dependencies  # type: ignore[attr-defined]
    ]
    declared: set[object] = set()
    while pending:
        dependant = pending.pop()
        declared.add(dependant.call)
        pending.extend(dependant.dependencies)

    assert require_administrator in declared
