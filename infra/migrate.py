"""Forward-only Postgres migration runner.

Reads `DATABASE_URL`, ensures a `schema_migrations` tracking table
exists, then applies any `infra/migrations/NNNN_*.py` modules not yet
recorded there, in filename order, each inside its own transaction.
Migration files are numbered (e.g. `0001_create_users.py`), so they
cannot be named as a dotted-import path -- each is loaded dynamically
by file path rather than imported as `migrations.NNNN_*`.

Run via `make migrate` (see infra/README.md). Never edit an applied
migration (AGENTS.md Conventions) -- add a new one instead.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from types import ModuleType

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_MIGRATION_NAME_RE = re.compile(r"^\d{4}_.*\.py$")

CONNECT_TIMEOUT_SECONDS = 10


def _discover_migrations() -> list[Path]:
    """Return migration files in filename (i.e. application) order.

    Also guards against a migration file whose name doesn't match the
    expected `NNNN_*.py` pattern -- such a file would otherwise be
    silently skipped forever instead of raising a clear error -- and
    against two files sharing the same 4-digit ordinal, which would
    otherwise apply in an arbitrary alphabetical tie-break order
    instead of a raised conflict.
    """
    unmatched = sorted(
        path
        for path in MIGRATIONS_DIR.glob("*.py")
        if path.name != "__init__.py" and not _MIGRATION_NAME_RE.match(path.name)
    )
    if unmatched:
        names = ", ".join(path.name for path in unmatched)
        raise ValueError(
            "migrate: found migration file(s) not matching the required "
            f"NNNN_*.py naming pattern (they would never be applied): {names}"
        )

    migrations = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.py"))

    ordinals: dict[str, list[str]] = {}
    for path in migrations:
        ordinals.setdefault(path.name[:4], []).append(path.name)
    duplicates = {ordinal: names for ordinal, names in ordinals.items() if len(names) > 1}
    if duplicates:
        detail = "; ".join(
            f"{ordinal}: {', '.join(names)}" for ordinal, names in sorted(duplicates.items())
        )
        raise ValueError(
            f"migrate: found migration files sharing the same ordinal ({detail})"
        )

    return migrations


def _load_migration(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load migration module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_schema_migrations_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id serial PRIMARY KEY,
            name text UNIQUE NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def _applied_names(cur: psycopg.Cursor) -> set[str]:
    cur.execute("SELECT name FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def run(database_url: str) -> None:
    """Apply every pending migration against `database_url`."""
    with psycopg.connect(
        database_url, autocommit=True, connect_timeout=CONNECT_TIMEOUT_SECONDS
    ) as conn:
        with conn.cursor() as cur:
            _ensure_schema_migrations_table(cur)
            applied = _applied_names(cur)

        for path in _discover_migrations():
            if path.name in applied:
                continue

            module = _load_migration(path)
            up = getattr(module, "up", None)
            if up is None:
                raise AttributeError(f"migration {path.name} defines no up(cur)")

            with conn.transaction():
                with conn.cursor() as cur:
                    up(cur)
                    cur.execute(
                        "INSERT INTO schema_migrations (name) VALUES (%s)",
                        (path.name,),
                    )


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("migrate: DATABASE_URL is not set", file=sys.stderr)
        raise SystemExit(1)

    try:
        run(database_url)
    except Exception as exc:
        print(f"migrate: failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
