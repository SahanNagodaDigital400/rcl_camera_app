"""The service's one route to PostgreSQL: a pool, and a dependency over it.

`apps/web` holds no database credential and has no network path to Postgres
(AD-6) — every read and write in the product comes through here.

Two rules this module exists to keep:

* **`DATABASE_URL` is never defaulted.** `infra/rocell_infra/config.py` follows
  the same rule for the migration runner and says why: a service that guesses a
  connection string can talk to the wrong database. A missing variable is a
  named failure at startup, not a surprise at the first request.
* **Connections are autocommit, with explicit transactions where a write spans
  more than one statement.** That is the shape `rocell_infra.migrate` already
  uses. The alternative — an implicit transaction opened by the driver and
  committed somewhere in FastAPI's dependency teardown — makes "did this
  commit?" depend on where an exception was raised, which is not a question a
  login endpoint should have.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import psycopg
from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from shared_schema.passwords import warm_password_verifier

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

#: The connection string. Required, never defaulted — see the module docstring.
DATABASE_URL = "DATABASE_URL"

#: Nothing is pre-opened. A pool that insisted on a live connection at import
#: or startup would turn a momentarily unreachable database into a service that
#: will not boot, and `apps/api` has one unauthenticated endpoint (`/health`)
#: that is meaningful precisely when the database is not.
POOL_MIN_SIZE = 0
POOL_MAX_SIZE = 10

#: How long a request waits for a free connection before failing. Without a
#: bound, a saturated pool turns into requests that hang rather than fail.
POOL_TIMEOUT_SECONDS = 10.0


class DatabaseNotConfigured(RuntimeError):
    """`DATABASE_URL` is missing. Named, so the fix is obvious from the message."""


def database_url(env: Mapping[str, str] | None = None) -> str:
    """Return `DATABASE_URL`, or raise naming it."""
    value = (os.environ if env is None else env).get(DATABASE_URL, "").strip()
    if not value:
        raise DatabaseNotConfigured(
            f"{DATABASE_URL} is not set. apps/api needs a PostgreSQL connection string, "
            f"e.g. {DATABASE_URL}=postgresql://rocell@localhost:5432/rocell — the same "
            f"database `make migrate` was pointed at."
        )
    return value


def create_pool(url: str | None = None) -> ConnectionPool:
    """Build the connection pool. Opened without waiting; see `POOL_MIN_SIZE`."""
    pool = ConnectionPool(
        conninfo=url if url is not None else database_url(),
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        timeout=POOL_TIMEOUT_SECONDS,
        # `dict_row` so a query's columns are read by name. Positional tuples
        # make a `SELECT` and its unpacking two places that have to agree about
        # column order, and the ten-column `User` read below is exactly the
        # shape where that goes wrong silently.
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )
    pool.open(wait=False)
    return pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Hold the connection pool open for the life of the application.

    `DATABASE_URL` is read here rather than at the first request: a service
    that starts and only then discovers it has no database has already told a
    load balancer it is healthy.
    """
    # Build the decoy digest now. The first login rejection would otherwise pay
    # for it and answer measurably slower than every later one — the timing
    # signal `verify_dummy_password` exists to remove (DW-24).
    warm_password_verifier()

    pool = create_pool()
    app.state.pool = pool
    try:
        yield
    finally:
        app.state.pool = None
        pool.close()


def get_pool(request: Request) -> ConnectionPool:
    """The running application's pool, or a clear failure if there is none."""
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise DatabaseNotConfigured(
            "The application has no connection pool. It was built without its lifespan — "
            "a TestClient used as a plain constructor rather than a context manager does "
            "exactly this."
        )
    return pool


def get_connection(request: Request) -> Iterator[psycopg.Connection]:
    """FastAPI dependency yielding one pooled, autocommit connection.

    Returned to the pool when the request finishes, whatever the outcome.
    """
    with get_pool(request).connection() as connection:
        yield connection
