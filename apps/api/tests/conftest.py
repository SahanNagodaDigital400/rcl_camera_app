"""A throwaway PostgreSQL, the real migrations, and a client that talks to both.

The cluster-management half below is a deliberate duplicate of
`infra/tests/conftest.py`. It *could* be shared — an importable helper module
loaded through `pytest_plugins`, or a root-level `conftest.py`, would do it —
but either means moving fixtures that Story 1.2's suite depends on, and that
refactor is tracked separately rather than taken as a drive-by here. Until it
happens the duplication is real: a change to the `initdb`/`pg_ctl` handling in
`infra/tests/conftest.py` has to be made here too.

Two things this file insists on:

* **The schema comes from `infra/migrations`, applied by `rocell_infra.migrate`.**
  A hand-written `CREATE TABLE` in a fixture would let the API be tested green
  against a shape the product does not actually ship, which is the one bug a
  database test exists to catch.
* **No password is committed.** Every credential here is generated at runtime
  (AGENTS.md Policy forbids one in a fixture as firmly as in source).
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from api import db
from api.db import DATABASE_URL
from api.main import create_app
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from rocell_infra import migrate
from shared_schema.passwords import MIN_PASSWORD_LENGTH, hash_password
from shared_schema.user import Role

TEST_DATABASE_URL = "TEST_DATABASE_URL"

#: The one migration these fixtures skip, by exact version. Matching on a
#: substring (`"seed" not in version`) would silently skip any later migration
#: whose name happened to contain it, and the API would then be tested against
#: a schema the product does not ship — the single failure a database test
#: exists to catch.
SEED_MIGRATION_VERSION = "20260917T1210_seed_administrator"

#: `_free_port` closes its probe before `pg_ctl` binds, so the port can be
#: taken in between. Retry on a fresh one rather than skipping the whole suite
#: with a message that points at PostgreSQL being absent when it is not.
START_ATTEMPTS = 5

#: A syntactically valid connection string pointing at nothing, for the tests
#: that never reach the database. The app's lifespan requires `DATABASE_URL` to
#: be *set* — it opens the pool without waiting for a connection — so
#: `/health` and the error-envelope tests need a value and not a server.
UNREACHABLE_URL = "postgresql://rocell@127.0.0.1:1/rocell"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


def _start_ephemeral_cluster() -> Iterator[str]:
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    if initdb is None or pg_ctl is None:
        pytest.skip("no PostgreSQL available (initdb/pg_ctl are not on PATH)")

    root = Path(tempfile.mkdtemp(prefix="rocell-pg-"))
    datadir = root / "data"
    logfile = root / "server.log"

    def give_up(detail: str) -> None:
        shutil.rmtree(root, ignore_errors=True)
        log = logfile.read_text(encoding="utf-8") if logfile.exists() else ""
        pytest.skip(f"no PostgreSQL available: {detail}\n{log}")

    try:
        subprocess.run(
            [initdb, "-D", str(datadir), "-U", "postgres", "--auth=trust", "--no-sync"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as failure:
        give_up(failure.stderr or failure.stdout)

    port = 0
    for attempt in range(START_ATTEMPTS):
        port = _free_port()
        started = subprocess.run(
            [
                pg_ctl,
                "-D",
                str(datadir),
                "-l",
                str(logfile),
                # -k '' disables the unix socket: on macOS a socket path under
                # a temporary directory routinely exceeds the 103-byte limit.
                "-o",
                f"-h 127.0.0.1 -p {port} -k ''",
                "-w",
                "start",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if started.returncode == 0:
            break
        if attempt == START_ATTEMPTS - 1:
            give_up(started.stderr or started.stdout)
        logfile.unlink(missing_ok=True)

    try:
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(datadir), "-m", "immediate", "-w", "stop"],
            check=False,
            capture_output=True,
        )
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def maintenance_url() -> Iterator[str]:
    """A connection string to a server that can create and drop databases."""
    configured = os.environ.get(TEST_DATABASE_URL, "").strip()
    if configured:
        yield configured
        return

    yield from _start_ephemeral_cluster()


@pytest.fixture
def database_url(maintenance_url: str) -> Iterator[str]:
    """A connection string to a database created empty for this one test."""
    name = f"rocell_api_test_{uuid4().hex}"

    with psycopg.connect(maintenance_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

    try:
        yield _with_database(maintenance_url, name)
    finally:
        with psycopg.connect(maintenance_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def migrated_url(database_url: str) -> str:
    """This test's database with `infra/migrations` applied — the shipped schema.

    The seed migration is skipped: it needs `SEED_ADMIN_*` in the environment
    and would put an account in the table that no test asked for. Every test
    user here is created explicitly by `make_user`. `test_seeded_login.py`
    applies the full set, seed included, and is where the 1.2 → 1.3
    composition is proven.
    """
    plan = [m for m in migrate.discover_migrations() if m.version != SEED_MIGRATION_VERSION]
    assert len(plan) == len(migrate.discover_migrations()) - 1, (
        f"{SEED_MIGRATION_VERSION} is no longer in infra/migrations; this filter is stale"
    )

    with psycopg.connect(database_url, autocommit=True) as conn:
        migrate.up(conn, plan)

    return database_url


@pytest.fixture
def conn(migrated_url: str) -> Iterator[psycopg.Connection]:
    """An autocommit connection to this test's migrated database.

    **This is the table owner, and on the ephemeral cluster a superuser.** It
    can do anything to any table, including `UPDATE audit_log` — so it is
    exactly the wrong connection to prove AD-4's immutability with. Use it to
    arrange state and to read results; use `app_role_conn` below to act with
    the privileges the product actually has.
    """
    with psycopg.connect(migrated_url, autocommit=True, row_factory=dict_row) as connection:
        yield connection


@pytest.fixture
def app_role_conn(migrated_url: str) -> Iterator[psycopg.Connection]:
    """A connection built the way `apps/api` builds one, `rocell_app` and all.

    Through `db.create_pool` rather than `psycopg.connect` with an `options`
    argument copied from it: a test that assembled its own connection string
    would pass on the day somebody dropped the `options` entry from the pool,
    which is the single change that turns AD-4's enforcement off. Going
    through the product's own constructor is what makes these tests fail for
    that edit.
    """
    pool = db.create_pool(migrated_url)
    try:
        with pool.connection() as connection:
            yield connection
    finally:
        pool.close()


_SELECT_AUDIT_ROWS = """
SELECT id, created_at, action, actor_user_id, actor_email,
       target_user_id, target_email, source_ip, details
  FROM audit_log
 ORDER BY created_at, id
"""


def _audit_rows(connection: psycopg.Connection) -> list[dict[str, object]]:
    """Every audit entry, oldest first.

    **`created_at` defaults to `now()`, which is the transaction timestamp**,
    so two entries written by one request share it exactly and `id` — a random
    UUID — is the only tiebreaker available. The order between rows of one
    transaction is therefore arbitrary: a test that cares which of two entries
    a request wrote should select by `action`, not by index. Across requests
    the order is real.

    Handed out by the `audit_rows` fixture below as a *callable* rather than
    as a snapshot: most callers want to read the log twice in one test, before
    and after a write, and a fixture returning rows would give them one
    reading. A fixture at all — rather than a module-level function a test
    imports — because the suite runs under `--import-mode=importlib` with no
    `__init__.py`, so `conftest` is not an importable module name.
    """
    return list(connection.execute(_SELECT_AUDIT_ROWS).fetchall())


@pytest.fixture
def audit_rows() -> Callable[[psycopg.Connection], list[dict[str, object]]]:
    """`audit_rows(conn)` — every audit entry, oldest first. See `_audit_rows`."""
    return _audit_rows


@dataclass(frozen=True, slots=True)
class Account:
    """A user this test created, and the password it can sign in with."""

    id: UUID
    email: str
    password: str
    name: str


_INSERT_USER = """
INSERT INTO users (
    name, email, password_hash, role, active, must_change_password,
    temp_credential_expires_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""


@pytest.fixture
def make_user(conn: psycopg.Connection) -> Callable[..., Account]:
    """Create a user with a runtime-generated password. Returns an `Account`."""

    def factory(
        *,
        role: Role = Role.STAFF,
        active: bool = True,
        must_change_password: bool = False,
        temp_credential_expires_at: datetime | None = None,
        name: str = "Test User",
    ) -> Account:
        # Generated per call, never a literal: AGENTS.md Policy forbids a
        # committed credential in a fixture as firmly as in source.
        password = secrets.token_urlsafe(32)[: MIN_PASSWORD_LENGTH + 8]
        email = f"user-{uuid4().hex}@rocell.lk"

        row = conn.execute(
            _INSERT_USER,
            (
                name,
                email,
                hash_password(password),
                role.value,
                active,
                must_change_password,
                temp_credential_expires_at,
            ),
        ).fetchone()
        assert row is not None

        return Account(id=row["id"], email=email, password=password, name=name)

    return factory


@pytest.fixture
def client(migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A `TestClient` whose app is pointed at this test's migrated database.

    `base_url` is https so the `Secure` session cookie is stored by the test
    client's cookie jar — over http it would be set by the server and silently
    dropped by the client, and every "then the session works" assertion would
    fail for a reason that has nothing to do with the code under test.
    """
    monkeypatch.setenv(DATABASE_URL, migrated_url)

    with TestClient(
        create_app(),
        base_url="https://testserver",
        # A peer address that is actually an address. Starlette's default is
        # the literal string `testclient`, which `api.audit.source_ip`
        # correctly refuses to store — every entry would then carry a NULL
        # `source_ip` and the assertions that it is captured at all would be
        # asserting the default. Loopback, because that is what a request to a
        # locally served API really comes from.
        client=("127.0.0.1", 50000),
    ) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _database_url_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the app a `DATABASE_URL` for the tests that never use one.

    The lifespan refuses to start without it, on purpose. The `client` fixture
    above overrides this with a real one; the tests that only exercise routing
    and the error envelope get a string pointing at nothing, which is all the
    pool needs to be constructed.
    """
    if not os.environ.get(DATABASE_URL, "").strip():
        monkeypatch.setenv(DATABASE_URL, UNREACHABLE_URL)
