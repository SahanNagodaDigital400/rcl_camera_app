"""`make migrate` and `make reseed-admin`, driven the way an operator drives them.

Everything else in `infra/tests` calls the runner's functions directly, and
`tests/test_make_targets.py` only ever runs `make migrate` *without* a
`DATABASE_URL` — so both of its cases pass for any subcommand the runner
accepts. That left the recipes themselves unverified: pointing `migrate:` at
`status` applies nothing, exits 0 and keeps the whole suite green, while
`README.md`, `CLAUDE.md` and `infra/README.md` all promise the target applies
migrations. `make reseed-admin` had no coverage at all.

These live here rather than in `tests/` because this is where the throwaway
PostgreSQL fixture is, and they skip with the rest of the suite when there is
no database to point at.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from pathlib import Path

import psycopg
import pytest
from shared_schema.passwords import MIN_PASSWORD_LENGTH, verify_password

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

MAKE = shutil.which("make")

pytestmark = pytest.mark.skipif(MAKE is None, reason="make is not on PATH")

SEED_EMAIL = "ruwan@rocell.lk"


def a_password() -> str:
    """Never a committed one: AGENTS.md Policy forbids a credential in a fixture."""
    return secrets.token_urlsafe(64)[: MIN_PASSWORD_LENGTH + 8]


def run_target(
    target: str, *, env_overrides: dict[str, str], timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    """Run one Makefile target in a subprocess that is not part of this build.

    `make test` may itself be the caller, and MAKEFLAGS carries the parent's
    jobserver file descriptors — inheriting them makes a nested make either warn
    about a disabled jobserver or block on descriptors this process does not
    hold.
    """
    assert MAKE is not None
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MAKELEVEL"}}
    env.update(env_overrides)

    try:
        return subprocess.run(
            [MAKE, target],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:  # pragma: no cover - a hung target
        pytest.fail(f"make {target} did not finish within {expired.timeout}s")


def stored_hash(conn: psycopg.Connection) -> str:
    row = conn.execute("SELECT password_hash FROM users WHERE role = 'admin'").fetchone()
    assert row is not None
    return str(row[0])


def test_make_migrate_creates_the_schema_and_seeds_one_administrator(
    conn: psycopg.Connection, database_url: str
) -> None:
    password = a_password()
    env = {
        "DATABASE_URL": database_url,
        "SEED_ADMIN_EMAIL": SEED_EMAIL,
        "SEED_ADMIN_PASSWORD": password,
    }

    result = run_target("migrate", env_overrides=env)
    assert result.returncode == 0, result.stdout + result.stderr

    columns = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
        ).fetchall()
    }
    assert {"role", "active", "must_change_password", "temp_credential_expires_at"} <= columns

    count = conn.execute("SELECT count(*) FROM users WHERE role = 'admin'").fetchone()
    assert count is not None and count[0] == 1
    assert verify_password(stored_hash(conn), password)

    # Re-running is the second half of the same acceptance clause, and running
    # it in this test rather than its own saves a second `uv run` startup.
    again = run_target("migrate", env_overrides=env)
    assert again.returncode == 0, again.stdout + again.stderr
    count = conn.execute("SELECT count(*) FROM users WHERE role = 'admin'").fetchone()
    assert count is not None and count[0] == 1


def test_make_migrate_names_the_target_and_the_credential_deadline(
    conn: psycopg.Connection, database_url: str
) -> None:
    result = run_target(
        "migrate",
        env_overrides={
            "DATABASE_URL": database_url,
            "SEED_ADMIN_EMAIL": SEED_EMAIL,
            "SEED_ADMIN_PASSWORD": a_password(),
        },
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    # Which database, so two URLs in a shell history do not produce identical
    # output; and the 72-hour deadline, which is the most time-critical fact
    # about the account and used to require a query to discover.
    assert "migrate: target" in output
    assert SEED_EMAIL in output
    assert "UTC" in output


def test_make_reseed_admin_reissues_rather_than_printing_usage(
    conn: psycopg.Connection, database_url: str
) -> None:
    # Any subcommand spelling the runner does not know makes this target exit 2
    # with a usage line, and nothing observed it. It is the only documented way
    # back in once the seeded credential has expired.
    first = a_password()
    seeded = run_target(
        "migrate",
        env_overrides={
            "DATABASE_URL": database_url,
            "SEED_ADMIN_EMAIL": SEED_EMAIL,
            "SEED_ADMIN_PASSWORD": first,
        },
    )
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    before = stored_hash(conn)

    second = a_password()
    result = run_target(
        "reseed-admin",
        env_overrides={
            "DATABASE_URL": database_url,
            "SEED_ADMIN_EMAIL": SEED_EMAIL,
            "SEED_ADMIN_PASSWORD": second,
        },
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "usage:" not in output
    assert stored_hash(conn) != before
    assert verify_password(stored_hash(conn), second)
    assert not verify_password(stored_hash(conn), first)
