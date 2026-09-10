"""Seed exactly one Administrator account.

Credentials come from environment variables, never a literal in
migration source (AGENTS.md: never hardcode secrets; addendum.md:
"Secrets in a managed secret store or environment variables -- never
committed to the repo"). All three `SEED_ADMIN_*` variables are
checked before any statement touches the database, so a missing one
aborts cleanly with no partial row.

The seeded account starts in the `must_change_password` state with a
72-hour temporary-credential window (FR-2), so even the very first
sign-in is gated by Story 1.4. Idempotency needs no extra check here:
this migration is recorded in `schema_migrations` after it first
succeeds and the runner never re-executes a recorded migration --see
infra/migrate.py.
"""

from __future__ import annotations

import os

import psycopg
from argon2 import PasswordHasher

REQUIRED_ENV_VARS = ("SEED_ADMIN_EMAIL", "SEED_ADMIN_NAME", "SEED_ADMIN_PASSWORD")


def _read_seed_credentials() -> tuple[str, str, str]:
    values = {name: os.environ.get(name, "").strip() for name in REQUIRED_ENV_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "seed_administrator: missing required environment variable(s): "
            + ", ".join(missing)
        )

    return (
        values["SEED_ADMIN_EMAIL"],
        values["SEED_ADMIN_NAME"],
        values["SEED_ADMIN_PASSWORD"],
    )


def up(cur: psycopg.Cursor) -> None:
    email, name, password = _read_seed_credentials()
    email = email.lower()
    password_hash = PasswordHasher().hash(password)

    cur.execute(
        """
        INSERT INTO users (
            name, email, password_hash, role, active,
            must_change_password, temp_credential_expires_at
        )
        VALUES (
            %s, %s, %s, 'admin', true,
            true, now() + interval '72 hours'
        )
        """,
        (name, email, password_hash),
    )
