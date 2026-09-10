"""Integration tests for the migration runner, against a real Postgres.

Requires `DATABASE_URL` to point at a reachable, disposable local
database (see infra/README.md). Deliberately not skipped when
`DATABASE_URL` is unset -- once DB-backed schema exists, a reachable
Postgres is an unavoidable test prerequisite, not something to work
around (spec-1-2 Design Notes).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from argon2 import PasswordHasher

MIGRATE_SCRIPT = Path(__file__).resolve().parent.parent / "migrate.py"


def _load_migrate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate", MIGRATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SEED_ENV = {
    "SEED_ADMIN_EMAIL": "admin@rocell.test",
    "SEED_ADMIN_NAME": "Seed Administrator",
    "SEED_ADMIN_PASSWORD": "correct-horse-battery-staple",
}

REQUIRED_USER_COLUMNS = {
    "id",
    "name",
    "email",
    "password_hash",
    "role",
    "active",
    "must_change_password",
    "temp_credential_expires_at",
    "created_at",
}


def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail(
            "DATABASE_URL must be set to a reachable, disposable local "
            "Postgres to run infra tests -- see infra/README.md"
        )
    return url


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _assert_database_looks_disposable(url: str) -> None:
    """Refuse to reset a database that doesn't look test-only.

    The fixture below runs `DROP TABLE` against whatever `DATABASE_URL`
    points at. Without this guard, an operator who accidentally runs
    `make test` against a real/shared database would silently destroy
    its `users` table. A database-name check alone would still pass
    for a test-named database that happens to live on a non-local
    (e.g. staging/production) host, so the host must look local too.
    """
    conninfo = psycopg.conninfo.conninfo_to_dict(url)
    db_name = conninfo.get("dbname", "")
    host = conninfo.get("host", "")
    if "test" not in db_name.lower() or host.lower() not in _LOCAL_HOSTS:
        pytest.fail(
            "refusing to reset database "
            f"{db_name!r} on host {host!r}: DATABASE_URL must point at a "
            "disposable database whose name contains 'test' on a local "
            "host to run infra tests -- see infra/README.md"
        )


@pytest.fixture
def database_url() -> Iterator[str]:
    url = _require_database_url()
    _assert_database_looks_disposable(url)

    def _reset() -> None:
        with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS users")
            cur.execute("DROP TABLE IF EXISTS schema_migrations")

    _reset()
    yield url
    _reset()


def _run_migrate(
    database_url: str, env_overrides: dict[str, str | None] | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env.update(SEED_ENV)
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    return subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_missing_database_url_aborts_before_connecting() -> None:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.update(SEED_ENV)

    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr


def test_fresh_database_creates_users_table_and_seeds_one_admin(
    database_url: str,
) -> None:
    result = _run_migrate(database_url)
    assert result.returncode == 0, result.stderr

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
        )
        columns = {row[0] for row in cur.fetchall()}
        assert REQUIRED_USER_COLUMNS <= columns

        cur.execute(
            "SELECT role, must_change_password, temp_credential_expires_at FROM users"
        )
        rows = cur.fetchall()
        assert len(rows) == 1

        role, must_change_password, temp_credential_expires_at = rows[0]
        assert role == "admin"
        assert must_change_password is True
        assert temp_credential_expires_at is not None


def test_rerunning_migrate_is_idempotent(database_url: str) -> None:
    first = _run_migrate(database_url)
    assert first.returncode == 0, first.stderr

    second = _run_migrate(database_url)
    assert second.returncode == 0, second.stderr

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users WHERE role = 'admin'")
        assert cur.fetchone()[0] == 1


def test_missing_seed_password_aborts_without_inserting_a_row(
    database_url: str,
) -> None:
    result = _run_migrate(database_url, env_overrides={"SEED_ADMIN_PASSWORD": None})

    assert result.returncode != 0
    assert "SEED_ADMIN_PASSWORD" in result.stderr

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        # 0001 still applies cleanly; only the seed insert aborts.
        cur.execute("SELECT count(*) FROM users")
        assert cur.fetchone()[0] == 0

        cur.execute("SELECT name FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
        assert "0001_create_users.py" in applied
        assert "0002_seed_administrator.py" not in applied


def test_reseed_onto_conflicting_email_fails_on_unique_constraint(
    database_url: str,
) -> None:
    # Apply 0001 only, then plant a user row under the seed email out of
    # band (e.g. manual intervention) before letting 0002 run for the
    # first time.
    first = _run_migrate(database_url, env_overrides={"SEED_ADMIN_PASSWORD": None})
    assert first.returncode != 0

    with psycopg.connect(database_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users
                (name, email, password_hash, role, active, must_change_password)
            VALUES
                (%s, %s, 'not-a-real-hash', 'admin', true, false)
            """,
            ("Existing User", SEED_ENV["SEED_ADMIN_EMAIL"]),
        )

    second = _run_migrate(database_url)
    assert second.returncode != 0
    assert "users_email_key" in second.stderr or "unique" in second.stderr.lower()

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users")
        assert cur.fetchone()[0] == 1

        cur.execute("SELECT name FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
        assert "0002_seed_administrator.py" not in applied


def test_seeded_password_hash_verifies_against_the_seed_password(
    database_url: str,
) -> None:
    result = _run_migrate(database_url)
    assert result.returncode == 0, result.stderr

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE role = 'admin'")
        (password_hash,) = cur.fetchone()

    PasswordHasher().verify(password_hash, SEED_ENV["SEED_ADMIN_PASSWORD"])


def test_seed_email_is_lowercased_when_given_mixed_case(database_url: str) -> None:
    result = _run_migrate(
        database_url, env_overrides={"SEED_ADMIN_EMAIL": "Admin@Rocell.Test"}
    )
    assert result.returncode == 0, result.stderr

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE role = 'admin'")
        (email,) = cur.fetchone()
        assert email == "admin@rocell.test"


def test_case_variant_duplicate_email_violates_unique_index(
    database_url: str,
) -> None:
    result = _run_migrate(database_url)
    assert result.returncode == 0, result.stderr

    case_variant_email = SEED_ENV["SEED_ADMIN_EMAIL"].upper()
    with psycopg.connect(database_url, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, role, active, must_change_password)
                VALUES
                    (%s, %s, 'not-a-real-hash', 'staff', true, false)
                """,
                ("Case Variant User", case_variant_email),
            )


def test_invalid_role_violates_check_constraint(database_url: str) -> None:
    result = _run_migrate(database_url)
    assert result.returncode == 0, result.stderr

    with psycopg.connect(database_url, autocommit=True) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, role, active, must_change_password)
                VALUES
                    (%s, %s, 'not-a-real-hash', 'superadmin', true, false)
                """,
                ("Invalid Role User", "not-the-seed-email@rocell.test"),
            )


def test_discover_migrations_rejects_malformed_filename(tmp_path: Path) -> None:
    module = _load_migrate_module()
    module.MIGRATIONS_DIR = tmp_path
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "0001_create_users.py").write_text("def up(cur): pass\n")
    (tmp_path / "not_a_migration.py").write_text("def up(cur): pass\n")

    with pytest.raises(ValueError, match="naming pattern"):
        module._discover_migrations()


def test_discover_migrations_rejects_duplicate_ordinal(tmp_path: Path) -> None:
    module = _load_migrate_module()
    module.MIGRATIONS_DIR = tmp_path
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "0001_create_users.py").write_text("def up(cur): pass\n")
    (tmp_path / "0001_conflicting.py").write_text("def up(cur): pass\n")

    with pytest.raises(ValueError, match="same ordinal"):
        module._discover_migrations()


def test_run_raises_when_migration_defines_no_up(
    database_url: str, tmp_path: Path
) -> None:
    module = _load_migrate_module()
    module.MIGRATIONS_DIR = tmp_path
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "0001_missing_up.py").write_text("VALUE = 1\n")

    with pytest.raises(AttributeError, match="defines no up"):
        module.run(database_url)

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM schema_migrations")
        assert cur.fetchone() is None
