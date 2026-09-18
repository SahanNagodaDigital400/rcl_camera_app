"""The one seeded Administrator.

Epic 1, Story 1.2: this is the only account in the product's lifetime that no
Administrator created. It is written by the migration runner — never by
application code, never through any UI — so there is no code path in the
running product that can mint an account from nothing.

Two independent layers keep it singular:

1. the `schema_migrations` ledger, which stops the seed migration's body from
   running a second time; and
2. the guard below, which does nothing at all if *any* `admin` row already
   exists.

Either alone would suffice. Both together mean that truncating the ledger,
restoring an old dump, or pointing the runner at an already-seeded database
still cannot produce a second seeded Administrator.

**Not audited yet.** Seeding and reissuing are both user changes made outside
the application, and AGENTS.md Policy requires the append-only audit log to
cover user changes. That log does not exist until Story 1.12, which owes these
two paths their entries — until then the only record of either is the console
output and `created_at` / `updated_at` on the row itself.
"""

from __future__ import annotations

from datetime import datetime

import psycopg
from psycopg import errors as pg_errors
from shared_schema.passwords import hash_password
from shared_schema.user import TEMP_CREDENTIAL_LIFETIME_HOURS, Role

from rocell_infra.config import SEED_ADMIN_EMAIL, ConfigurationError, seed_admin_config

# The 72 hours is `shared_schema.user`'s, not this module's, since Story 1.8
# gave `apps/api` a second writer of admin-issued credentials. The seeded
# credential is one of them, so it expires too — `reseed_administrator` exists
# because of that, see `infra/README.md`. Re-exported through `__all__` below,
# so `seed.TEMP_CREDENTIAL_LIFETIME_HOURS` still resolves for the callers and
# tests that read it from here.

_ADMINISTRATOR_EXISTS = "SELECT 1 FROM users WHERE role = %s LIMIT 1"

_INSERT_ADMINISTRATOR = """
INSERT INTO users (
    name, email, password_hash, role,
    active, must_change_password, temp_credential_expires_at
)
VALUES (%s, %s, %s, %s, true, true, now() + make_interval(hours => %s))
"""

_COUNT_ADMINISTRATORS = "SELECT count(*) FROM users WHERE role = %s"

_SELECT_UNCLAIMED_ADMINISTRATOR = """
SELECT id, email, temp_credential_expires_at
  FROM users
 WHERE role = %s
   AND must_change_password
   AND last_login_at IS NULL
 ORDER BY created_at
 LIMIT 1
"""

#: Deliberately does not touch `active`. Reissuing a credential is not a
#: reactivation, and an Administrator deactivated on purpose must not come back
#: because someone ran a console command that advertises itself as narrow.
_REISSUE_CREDENTIAL = """
UPDATE users
   SET password_hash = %s,
       must_change_password = true,
       temp_credential_expires_at = now() + make_interval(hours => %s),
       updated_at = now()
 WHERE id = %s
"""


class SeedRefused(RuntimeError):
    """A seed operation declined to run, on purpose."""


def administrator_exists(conn: psycopg.Connection) -> bool:
    """Whether the database already holds any Administrator."""
    row = conn.execute(_ADMINISTRATOR_EXISTS, (Role.ADMIN.value,)).fetchone()
    return row is not None


def seed_administrator(conn: psycopg.Connection) -> bool:
    """Create the first Administrator if there is not one already.

    Runs inside the caller's transaction — the migration runner's — so a
    failure here rolls the whole migration back and writes no ledger row.

    Returns whether a row was inserted. The environment is read *after* the
    guard, so an already-seeded database migrates with no seed environment set
    at all.
    """
    if administrator_exists(conn):
        return False

    config = seed_admin_config()
    conn.execute(
        _INSERT_ADMINISTRATOR,
        (
            config.name,
            # Stored lowercased, and the table's CHECK enforces it. Uniqueness
            # is over `lower(email)`, so a stored address in any other case
            # would oblige every lookup from Story 1.3 on to remember
            # `lower(email) = lower(<address>)` — and nothing would catch the first
            # one that forgot.
            config.email.lower(),
            hash_password(config.password),
            Role.ADMIN.value,
            TEMP_CREDENTIAL_LIFETIME_HOURS,
        ),
    )
    return True


def unclaimed_administrator(conn: psycopg.Connection) -> tuple[str, datetime] | None:
    """The unclaimed Administrator's address and credential expiry, if there is one.

    Read-only, and for the console: the runner prints both after seeding or
    reissuing so the operator does not have to query the database to learn what
    to type and by when.
    """
    row = conn.execute(_SELECT_UNCLAIMED_ADMINISTRATOR, (Role.ADMIN.value,)).fetchone()
    if row is None or row[2] is None:
        return None
    return str(row[1]), row[2]


def administrator_count(conn: psycopg.Connection) -> int:
    """How many Administrators this database holds.

    Public because the runner's console reporting needs it too: advice to run
    `make reseed-admin` is only true while there is exactly one Administrator,
    which is the same condition `reseed_administrator` refuses on.
    """
    try:
        row = conn.execute(_COUNT_ADMINISTRATORS, (Role.ADMIN.value,)).fetchone()
    except pg_errors.UndefinedTable as missing:
        raise SeedRefused(
            "This database has no `users` table. Run `make migrate` against it first."
        ) from missing
    return 0 if row is None else int(row[0])


def reseed_administrator(conn: psycopg.Connection) -> None:
    """Reissue the seeded Administrator's temporary credential.

    The seeded credential expires after 72 hours like any other. If nobody
    claims the account in that window there is no Administrator left to reissue
    it and the product is unreachable — this is the way back in.

    It is deliberately narrow, so that it can never become a back door into a
    live system. It refuses once a second Administrator exists (someone else
    can reissue it through the product), and it refuses once the account has
    been claimed (`must_change_password` cleared, or a recorded sign-in). It
    also never touches `active`: a deactivated Administrator stays deactivated.
    """
    count = administrator_count(conn)

    if count == 0:
        raise SeedRefused(
            "No Administrator exists to reseed. Run `make migrate` against this database first."
        )
    if count > 1:
        raise SeedRefused(
            f"Refusing to reseed: this database has {count} Administrators. Reissue the "
            "credential from the admin screens instead."
        )

    unclaimed = conn.execute(_SELECT_UNCLAIMED_ADMINISTRATOR, (Role.ADMIN.value,)).fetchone()
    if unclaimed is None:
        raise SeedRefused(
            "Refusing to reseed: the seeded Administrator has already been claimed. "
            "Reissue the credential from the admin screens instead."
        )

    admin_id, stored_email = unclaimed[0], str(unclaimed[1])

    config = seed_admin_config()
    # `SEED_ADMIN_EMAIL` is required and validated here, and the reissue changes
    # the password and the expiry and nothing else — so an operator who supplies
    # a *different* address would be told the credential was reissued and then
    # find that nothing accepts the address they typed. Refuse instead, and name
    # the address that would have worked.
    if config.email.lower() != stored_email:
        raise SeedRefused(
            f"Refusing to reseed: {SEED_ADMIN_EMAIL} is {config.email.lower()!r} but the "
            f"seeded Administrator is {stored_email!r}. Reissuing does not change the "
            f"address — re-run with {SEED_ADMIN_EMAIL}={stored_email}."
        )

    conn.execute(
        _REISSUE_CREDENTIAL,
        (
            hash_password(config.password),
            TEMP_CREDENTIAL_LIFETIME_HOURS,
            admin_id,
        ),
    )


__all__ = [
    "TEMP_CREDENTIAL_LIFETIME_HOURS",
    "ConfigurationError",
    "SeedRefused",
    "administrator_count",
    "administrator_exists",
    "reseed_administrator",
    "seed_administrator",
    "unclaimed_administrator",
]
