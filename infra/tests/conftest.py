"""A throwaway PostgreSQL for the migration tests.

`TEST_DATABASE_URL` wins if it is set — CI points it at whatever it already
runs. Otherwise an ephemeral cluster is started with `initdb` + `pg_ctl` and
torn down at the end of the session.

That cluster listens on **127.0.0.1**, with unix sockets switched off (`-k ''`).
A socket would be created under the temporary directory, and on macOS that path
routinely exceeds the 103-byte limit a unix-domain socket path has — the server
then refuses to start with an error that has nothing to do with the tests.

Every test gets a freshly created, empty database, so no test can pass only
because an earlier one left state behind.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

TEST_DATABASE_URL = "TEST_DATABASE_URL"

#: `_free_port` closes its probe before `pg_ctl` binds, so the port can be
#: taken in between. Retry on a fresh one rather than skipping the whole suite
#: with a message that points at PostgreSQL being absent when it is not.
START_ATTEMPTS = 5


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
                # -k '' disables the unix socket; see the module docstring.
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
    name = f"rocell_test_{uuid4().hex}"

    # An identifier cannot be a query parameter. `sql.Identifier` quotes it
    # through libpq rather than concatenating it, which is the same rule the
    # runner follows for values.
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
def conn(database_url: str) -> Iterator[psycopg.Connection]:
    """An autocommit connection to this test's database, as the runner uses."""
    with psycopg.connect(database_url, autocommit=True) as connection:
        yield connection
