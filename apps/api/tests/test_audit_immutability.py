"""AD-4 — the audit log is append-only because PostgreSQL says so.

Every other guarantee in this story is a property of code somebody could
change. This one is a property of a `GRANT`, and that is the point: "no update
or delete path against the audit log exists" has to survive a route added in
Epic 3 by somebody who never read this file.

So the assertions here are deliberately not about `api.audit`. They are about
what the product's own connection can and cannot do:

* it runs as `rocell_app`, not as the table owner;
* `has_table_privilege` says INSERT and SELECT and nothing else on the log;
* the three forbidden statements really are refused, run for real;
* every *other* table is fully granted, so a migration that forgets its
  `GRANT` fails here rather than in production; and
* the entry and the change it records land together or not at all.

**`conn` is the wrong connection for all of this** and is used only to arrange
and inspect: on the suite's ephemeral cluster it is a superuser, which can
`UPDATE audit_log` all day. `app_role_conn` is built through `db.create_pool`,
so a test here fails the moment somebody drops the `options` entry from the
pool — which is the single edit that turns this whole story off.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from api.audit import AuditAction
from api.db import APPLICATION_ROLE, DATABASE_URL
from api.main import create_app
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from shared_schema.passwords import MIN_PASSWORD_LENGTH
from shared_schema.user import Role

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO_ROOT / "infra" / "migrations"

CREATE_USER = "/admin/users"
LOGIN = "/auth/login"

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, Any]]]

#: The table AD-4 protects, and the one the runner's ledger owns. Neither is
#: expected in the "fully granted" set below: the first deliberately is not,
#: and the second is `rocell_infra`'s, written by the migration runner under
#: the owner's own credentials and never touched by `apps/api`.
AUDIT_TABLE = "audit_log"
LEDGER_TABLE = "schema_migrations"

#: The four privileges a table the application mutates must carry.
DML = ("SELECT", "INSERT", "UPDATE", "DELETE")

TEMPORARY = "t" * (MIN_PASSWORD_LENGTH + 8)


def _body(**overrides: Any) -> dict[str, Any]:
    submitted: dict[str, Any] = {
        "name": "Nadeesha Silva",
        "email": "nadeesha@rocell.lk",
        "role": Role.STAFF.value,
        "temporary_password": TEMPORARY,
    }
    submitted.update(overrides)
    return submitted


def _privilege(conn: psycopg.Connection, table: str, privilege: str) -> bool:
    row = conn.execute(
        "SELECT has_table_privilege(%s, %s) AS allowed", (table, privilege)
    ).fetchone()
    assert row is not None
    return bool(row["allowed"])


# --- The role is actually adopted ---------------------------------------------


def test_the_products_own_connection_runs_as_the_application_role(
    app_role_conn: psycopg.Connection,
) -> None:
    # The first thing that would break if `options` were dropped from
    # `create_pool`, and the assertion that says *why* everything below fails
    # rather than leaving somebody to guess at a privilege error.
    row = app_role_conn.execute("SELECT current_user AS whoami").fetchone()
    assert row is not None
    assert row["whoami"] == APPLICATION_ROLE


def test_the_owner_and_the_application_role_are_not_the_same_connection(
    conn: psycopg.Connection, app_role_conn: psycopg.Connection
) -> None:
    # If these two were equal, every refusal below would be vacuous — and on a
    # cluster where the migration runner happened to connect as `rocell_app`
    # they would be. Stated rather than assumed.
    owner = conn.execute("SELECT current_user AS whoami").fetchone()
    app = app_role_conn.execute("SELECT current_user AS whoami").fetchone()
    assert owner is not None and app is not None
    assert owner["whoami"] != app["whoami"]


def test_the_migrating_role_is_granted_membership_of_the_application_role(
    conn: psycopg.Connection,
) -> None:
    # The `GRANT rocell_app TO current_user` block in the migration is what
    # lets a real deployment adopt the role at all: a non-superuser connection
    # asking for `-c role=rocell_app` without membership is refused at connect
    # time with `FATAL: permission denied to set role`, and *every* request
    # dies, not only the audit writes.
    #
    # **The test above cannot see that block.** This suite's cluster hands out
    # a superuser, and a superuser adopts any role without being a member of
    # it, so deleting the GRANT leaves `current_user == rocell_app` green here
    # and broken in production. `pg_has_role` is no help for the same reason —
    # it answers true for a superuser whatever the catalog says. So the
    # membership is read out of `pg_auth_members` directly, which records only
    # what was actually granted.
    row = conn.execute(
        """
        SELECT EXISTS (
                 SELECT 1
                   FROM pg_auth_members AS membership
                   JOIN pg_roles AS granted ON granted.oid = membership.roleid
                   JOIN pg_roles AS grantee ON grantee.oid = membership.member
                  WHERE granted.rolname = %s
                    AND grantee.rolname = current_user
               ) AS is_member
        """,
        (APPLICATION_ROLE,),
    ).fetchone()
    assert row is not None
    assert row["is_member"], (
        f"the migrating role is not a member of {APPLICATION_ROLE}. A superuser "
        "adopts the role anyway, so this suite would stay green while a "
        "non-superuser deployment could not open a single connection."
    )


def test_the_application_role_carries_no_attribute_beyond_membership(
    conn: psycopg.Connection,
) -> None:
    # The migration creates the role with no attributes at all, and argues the
    # point at length: adoption through `options=-c role=` needs MEMBERSHIP,
    # never LOGIN, so a LOGIN attribute would hand the cluster a passwordless
    # login principal whose only protection is `pg_hba.conf` — a connection
    # vector on a `trust` or `peer` cluster, for a capability nothing uses.
    #
    # **Nothing else in this suite can see that.** The privilege matrix below
    # asks what the role may do to a table; `rolcanlogin`, `rolsuper`,
    # `rolcreaterole` and `rolbypassrls` are not table privileges, so
    # `CREATE ROLE rocell_app LOGIN` — or a later `ALTER ROLE rocell_app
    # SUPERUSER`, which would make every refusal below vacuous — passes every
    # one of them. The attributes are the security decision; this is the test
    # that holds them.
    row = conn.execute(
        """
        SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls
          FROM pg_roles
         WHERE rolname = %s
        """,
        (APPLICATION_ROLE,),
    ).fetchone()
    assert row is not None, f"{APPLICATION_ROLE} does not exist"
    assert not row["rolcanlogin"], (
        f"{APPLICATION_ROLE} may log in. The role is adopted by membership and "
        "never connected to directly, so LOGIN adds nothing but a passwordless "
        "principal guarded only by pg_hba.conf."
    )
    assert not row["rolsuper"], (
        f"{APPLICATION_ROLE} is a superuser, which ignores every grant — the "
        "refusals this module asserts would all be vacuous."
    )
    assert not row["rolbypassrls"], f"{APPLICATION_ROLE} may bypass row-level security"
    assert not row["rolcreaterole"], f"{APPLICATION_ROLE} may create roles"
    assert not row["rolcreatedb"], f"{APPLICATION_ROLE} may create databases"


# --- The grant matrix ----------------------------------------------------------


@pytest.mark.parametrize("privilege", ["SELECT", "INSERT"])
def test_the_application_role_may_read_and_append_the_log(
    app_role_conn: psycopg.Connection, privilege: str
) -> None:
    assert _privilege(app_role_conn, AUDIT_TABLE, privilege)


@pytest.mark.parametrize("privilege", ["UPDATE", "DELETE", "TRUNCATE", "REFERENCES"])
def test_the_application_role_holds_nothing_else_on_the_log(
    app_role_conn: psycopg.Connection, privilege: str
) -> None:
    # `REFERENCES` is in the list although AD-4 does not name it: without it a
    # later migration cannot add a foreign key *pointing at* this table under
    # the application role, which is the other half of AD-10's snapshot rule.
    assert not _privilege(app_role_conn, AUDIT_TABLE, privilege)


@pytest.mark.parametrize("table", ["users", "sessions", "login_attempts"])
@pytest.mark.parametrize("privilege", DML)
def test_every_other_table_is_fully_granted(
    app_role_conn: psycopg.Connection, table: str, privilege: str
) -> None:
    assert _privilege(app_role_conn, table, privilege)


def test_no_table_is_left_ungranted_by_a_later_migration(
    conn: psycopg.Connection, app_role_conn: psycopg.Connection
) -> None:
    # The regression this file exists to make cheap. There is deliberately no
    # `ALTER DEFAULT PRIVILEGES` in the schema — a table added by a later
    # migration needs its own `GRANT` in that migration — so the failure mode
    # is a `permission denied` at the first request that touches it. This
    # turns that into a failing test the day the migration lands.
    tables = [
        row["tablename"]
        for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename",
            ("public",),
        ).fetchall()
    ]
    assert AUDIT_TABLE in tables, "the scan found no audit table; it has drifted off the schema"

    ungranted = [
        f"{table}.{privilege}"
        for table in tables
        if table not in (AUDIT_TABLE, LEDGER_TABLE)
        for privilege in DML
        if not _privilege(app_role_conn, table, privilege)
    ]

    assert ungranted == [], (
        "A table in `public` that the application role cannot fully use. Add its "
        "GRANT to the migration that created it — there is no ALTER DEFAULT "
        f"PRIVILEGES to fall back on: {', '.join(ungranted)}"
    )


# --- The refusals, run for real -----------------------------------------------


def test_an_append_succeeds_through_the_products_own_connection(
    app_role_conn: psycopg.Connection, conn: psycopg.Connection, audit_rows: AuditRows
) -> None:
    # The control for the three refusals below: without it they would all pass
    # against a table the role cannot reach at all, and nothing would say so.
    app_role_conn.execute("INSERT INTO audit_log (action) VALUES (%s)", ("login_succeeded",))
    assert [row["action"] for row in audit_rows(conn)] == ["login_succeeded"]


def test_updating_an_entry_is_refused_by_postgresql(
    app_role_conn: psycopg.Connection, conn: psycopg.Connection, audit_rows: AuditRows
) -> None:
    conn.execute("INSERT INTO audit_log (action) VALUES (%s)", ("login_succeeded",))

    with pytest.raises(pg_errors.InsufficientPrivilege):
        app_role_conn.execute("UPDATE audit_log SET action = %s", ("nothing_happened",))

    # And the row is exactly as it was. The refusal is the point; this is the
    # reason the refusal matters.
    assert [row["action"] for row in audit_rows(conn)] == ["login_succeeded"]


def test_deleting_an_entry_is_refused_by_postgresql(
    app_role_conn: psycopg.Connection, conn: psycopg.Connection, audit_rows: AuditRows
) -> None:
    conn.execute("INSERT INTO audit_log (action) VALUES (%s)", ("login_succeeded",))

    with pytest.raises(pg_errors.InsufficientPrivilege):
        app_role_conn.execute("DELETE FROM audit_log")

    assert len(audit_rows(conn)) == 1


def test_truncating_the_log_is_refused_by_postgresql(
    app_role_conn: psycopg.Connection, conn: psycopg.Connection, audit_rows: AuditRows
) -> None:
    # Neither an UPDATE nor a DELETE, and it empties the table in one
    # statement — so it needs its own assertion rather than being assumed to
    # fall out of the other two.
    conn.execute("INSERT INTO audit_log (action) VALUES (%s)", ("login_succeeded",))

    with pytest.raises(pg_errors.InsufficientPrivilege):
        app_role_conn.execute("TRUNCATE audit_log")

    assert len(audit_rows(conn)) == 1


def test_reading_the_log_is_allowed(
    app_role_conn: psycopg.Connection, conn: psycopg.Connection
) -> None:
    # Story 1.13's read surface has to be reachable by the same role, and a
    # grant model that forgot `SELECT` would look identical to a correct one
    # until that story tried to render a page.
    conn.execute("INSERT INTO audit_log (action) VALUES (%s)", ("login_succeeded",))
    row = app_role_conn.execute("SELECT count(*) AS total FROM audit_log").fetchone()
    assert row is not None
    assert row["total"] == 1


# --- No mutation path anywhere in the migrations ------------------------------


def _statements(path: Path) -> str:
    """A migration's body with its `--` comments blanked, newlines preserved.

    Both scans below are about what a migration *does*, and both files
    deliberately explain at length what they do not do — the down migration
    says in as many words why it carries no `DROP ROLE`. A scan that read the
    prose would flag the sentence arguing for the rule it enforces.

    **One string, not a list of lines**, for the reason `test_source_guards.py`
    gives for the same decision over the Python sources: DDL in this
    repository is written across lines, aligned in three columns, so the
    statement these scans exist to catch would almost certainly arrive as
    `DELETE\\n  FROM audit_log`. A line-by-line reader calls that clean. Every
    newline survives the blanking, so a match's offset still resolves to the
    line it is really on.
    """
    return "\n".join(
        line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()
    )


def _at(text: str, offset: int) -> int:
    """The 1-indexed line a match at `offset` starts on."""
    return text.count("\n", 0, offset) + 1


def _migrations() -> list[Path]:
    scanned = sorted(MIGRATIONS.glob("*.sql"))
    assert len(scanned) > 5, "the migration scan found nothing; it has drifted off the directory"
    return scanned


#: The three verbs AD-4 forbids, against the audit table, in the spellings SQL
#: writes them — the `.sql` twin of `test_source_guards.py`'s
#: `_MUTATION_OF_THE_AUDIT_LOG`, and deliberately the same shape: `\s+` between
#: every token so a statement split across lines still matches, and
#: `(?:public\.)?` because a schema-qualified `public.audit_log` is the same
#: table and the same violation.
#:
#: Written as one literal rather than concatenated around `AUDIT_TABLE`:
#: `tests/test_source_guards.py` forbids a SQL verb glued to a value with `+`,
#: and it is right to — this is a regex and not a statement, but the guard
#: cannot know that and a guard with an exception is a guard argued with.
_MIGRATION_MUTATION = re.compile(
    r"\b(?:UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?)\s+(?:public\.)?audit_log\b",
    re.IGNORECASE,
)

#: Cluster-scoped destruction, across lines for the same reason.
_MIGRATION_DROP_ROLE = re.compile(r"\bDROP\s+ROLE\b", re.IGNORECASE)


def test_no_migration_carries_a_mutation_path_against_the_log() -> None:
    # `infra/README.md`: no migration may add an UPDATE or DELETE path to the
    # audit table. `tests/test_source_guards.py` makes the same assertion over
    # the Python sources and cannot see `.sql` at all, so this is the other
    # half of it — and the migration that *creates* the table is in scope, not
    # exempt from it.
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{_at(body, match.start())}"
        for path in _migrations()
        for body in [_statements(path)]
        for match in _MIGRATION_MUTATION.finditer(body)
    ]
    assert offenders == [], (
        "A migration carrying a mutation path against the audit table (AD-4, "
        "infra/README.md): " + ", ".join(offenders)
    )


def test_no_migration_drops_the_application_role() -> None:
    # The role is cluster-scoped while every test here gets its own database,
    # so a `DROP ROLE` in a `.down.sql` would revoke it out from under every
    # other database in the cluster — and would take the whole suite with it
    # rather than one test.
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{_at(body, match.start())}"
        for path in _migrations()
        for body in [_statements(path)]
        for match in _MIGRATION_DROP_ROLE.finditer(body)
    ]
    assert offenders == [], "A migration dropping the cluster-scoped role: " + ", ".join(offenders)


@pytest.mark.parametrize(
    "body",
    [
        "UPDATE audit_log SET action = 'x';",
        "DELETE FROM audit_log WHERE created_at < now();",
        "TRUNCATE audit_log;",
        "truncate table audit_log cascade;",
        "DELETE FROM public.audit_log;",
        # **The shape a migration in this repository would actually take.**
        # Every statement in `infra/migrations` is written across lines with
        # its columns aligned, so the verb and the table land on different
        # ones — and a line-by-line scan reads all three of these as clean.
        "DELETE\n  FROM audit_log\n WHERE created_at < now();",
        "UPDATE\n    audit_log\n   SET action = 'x';",
        "TRUNCATE TABLE\n    public.audit_log;",
    ],
)
def test_the_migration_mutation_pattern_catches_what_it_is_for(body: str) -> None:
    # A guard nobody has seen fail is a guard nobody knows works.
    assert _MIGRATION_MUTATION.search(body)


@pytest.mark.parametrize(
    "body",
    [
        "INSERT INTO audit_log (action) VALUES ('login_succeeded');",
        "SELECT action FROM audit_log ORDER BY created_at DESC;",
        "GRANT SELECT, INSERT ON audit_log TO rocell_app;",
        "UPDATE users SET active = false WHERE id = $1;",
        "INSERT INTO audit_log (action)\nVALUES ('login_failed');",
        # The `down` migration's own statement: destruction of the whole table
        # is a different question from a mutation path against its rows, and
        # this guard deliberately does not answer it. The header of
        # `...create_audit_log.down.sql` is where that argument lives.
        "DROP TABLE IF EXISTS audit_log;",
    ],
)
def test_the_migration_mutation_pattern_leaves_the_permitted_statements_alone(body: str) -> None:
    assert not _MIGRATION_MUTATION.search(body)


@pytest.mark.parametrize("body", ["DROP ROLE rocell_app;", "drop\n  role rocell_app;"])
def test_the_drop_role_pattern_catches_what_it_is_for(body: str) -> None:
    assert _MIGRATION_DROP_ROLE.search(body)


@pytest.mark.parametrize(
    "body",
    [
        # Everything the two audit migrations actually do to the role or the
        # table. A guard that caught any of these would make the pair
        # unwritable, which is the failure mode a positive control alone
        # cannot see.
        "CREATE ROLE rocell_app;",
        "GRANT rocell_app TO rocell_owner;",
        "EXECUTE format('REVOKE rocell_app FROM %I', current_user);",
        "REVOKE ALL PRIVILEGES ON users FROM rocell_app;",
        "DROP TABLE IF EXISTS audit_log;",
        "DROP INDEX IF EXISTS audit_log_created_at_idx;",
        # `DROP` and `ROLE` both present, neither as the statement: the arm
        # that would fire on a naive `DROP.*ROLE`.
        "DROP TABLE roles;\nGRANT rocell_app TO rocell_owner;",
    ],
)
def test_the_drop_role_pattern_leaves_the_permitted_statements_alone(body: str) -> None:
    assert not _MIGRATION_DROP_ROLE.search(body)


# --- The entry and the change land together -----------------------------------
#
# Nine docstrings in this change promise that a write and its audit entry land
# together or neither does. Three of them are proved here, one per shape of
# transaction: `create_user`'s, which is new in this story; `delete_user`'s,
# which is destructive and irreversible if it half-happened; and `logout`'s,
# whose wrapper is also new and which is the one place the entry sits beside a
# statement that had already been written unwrapped. Each is staged the only
# honest way — take the INSERT grant away and drive the real endpoint.


@pytest.fixture
def unraising_client(migrated_url: str, monkeypatch: Any) -> Any:
    """A `TestClient` that renders a 500 instead of re-raising it.

    The shared `client` fixture leaves `raise_server_exceptions` on, which is
    right for every other test in the suite: an unexpected exception should
    surface as itself. Here the 500 *is* the assertion, so it has to come back
    as a response.
    """
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    return TestClient(create_app(), base_url="https://testserver", raise_server_exceptions=False)


def _counts(conn: psycopg.Connection) -> tuple[int, int]:
    """`(users, audit_log)` row counts, for a before/after comparison."""
    users = conn.execute("SELECT count(*) AS total FROM users").fetchone()
    entries = conn.execute("SELECT count(*) AS total FROM audit_log").fetchone()
    assert users is not None and entries is not None
    return int(users["total"]), int(entries["total"])


def test_a_delete_fails_and_leaves_the_user_row_when_the_log_cannot_be_appended(
    conn: psycopg.Connection,
    unraising_client: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    # The destructive one, and the one where half-happening is unrecoverable:
    # a `users` row removed with no record of who removed it is precisely the
    # state FR-20 exists to prevent, and no later entry can reconstruct it.
    # `delete_user` writes its entry inside the transaction that ran
    # `_DELETE_USER`, so the failure takes the delete with it.
    administrator = make_user(role=Role.ADMIN)
    target = make_user()

    with unraising_client as client:
        assert (
            client.post(
                LOGIN,
                json={"email": administrator.email, "password": administrator.password},
            ).status_code
            == 200
        )
        users_before, entries_before = _counts(conn)

        conn.execute("REVOKE INSERT ON audit_log FROM rocell_app")

        response = client.delete(f"/admin/users/{target.id}")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert _counts(conn) == (users_before, entries_before)
    # The row is still there, not merely the count.
    assert conn.execute(
        "SELECT count(*) AS total FROM users WHERE id = %s", (target.id,)
    ).fetchone() == {"total": 1}
    assert AuditAction.USER_DELETED not in {row["action"] for row in audit_rows(conn)}


def test_a_sign_out_fails_and_leaves_the_session_when_the_log_cannot_be_appended(
    conn: psycopg.Connection,
    unraising_client: Any,
    make_user: MakeUser,
    audit_rows: AuditRows,
) -> None:
    # `logout`'s `with conn.transaction():` is new in this story and nothing
    # else holds it in place: remove it and the session is revoked while the
    # entry is not, which is a sign-out the log says never happened. Recorded
    # or not at all — and a caller retrying an idempotent `204` costs nothing,
    # which is what makes failing the right direction here.
    account = make_user()

    with unraising_client as client:
        assert (
            client.post(
                LOGIN, json={"email": account.email, "password": account.password}
            ).status_code
            == 200
        )
        sessions_before = conn.execute(
            "SELECT count(*) AS total FROM sessions WHERE user_id = %s", (account.id,)
        ).fetchone()
        assert sessions_before == {"total": 1}

        conn.execute("REVOKE INSERT ON audit_log FROM rocell_app")

        response = client.post("/auth/logout")

    assert response.status_code == 500
    # The session survived with the entry that would have described it.
    assert conn.execute(
        "SELECT count(*) AS total FROM sessions WHERE user_id = %s", (account.id,)
    ).fetchone() == {"total": 1}
    assert AuditAction.LOGGED_OUT not in {row["action"] for row in audit_rows(conn)}


def test_a_provision_fails_and_writes_no_user_when_the_log_cannot_be_appended(
    conn: psycopg.Connection, migrated_url: str, make_user: MakeUser, monkeypatch: Any
) -> None:
    # The atomicity clause, staged the only honest way: take the grant away
    # and drive the real endpoint. `create_user` wraps its INSERT and its
    # audit entry in one transaction precisely so this cannot half-happen —
    # remove that transaction and this test fails while every other
    # provisioning test still passes.
    #
    # Its own `TestClient` rather than the shared fixture, with
    # `raise_server_exceptions=False`, so the enveloped 500 is observable as a
    # response instead of being re-raised into the test.
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    account = make_user(role=Role.ADMIN)

    with TestClient(
        create_app(), base_url="https://testserver", raise_server_exceptions=False
    ) as client:
        assert (
            client.post(
                LOGIN, json={"email": account.email, "password": account.password}
            ).status_code
            == 200
        )

        # Taken after the sign-in, which has already written a
        # `login_succeeded` entry of its own: the assertion below is that
        # nothing *else* landed, not that the log is empty.
        before = conn.execute("SELECT count(*) AS total FROM users").fetchone()
        entries_before = conn.execute("SELECT count(*) AS total FROM audit_log").fetchone()
        assert before is not None and entries_before is not None

        conn.execute("REVOKE INSERT ON audit_log FROM rocell_app")

        response = client.post(CREATE_USER, json=_body())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"

    after = conn.execute("SELECT count(*) AS total FROM users").fetchone()
    assert after is not None
    assert after["total"] == before["total"], (
        "the `users` row was written although its audit entry was not — the two "
        "are supposed to be one transaction"
    )
    assert conn.execute("SELECT count(*) AS total FROM audit_log").fetchone() == entries_before
