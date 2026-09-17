"""Environment-supplied configuration for the migration runner.

AGENTS.md Policy: secrets come from the environment or a secret store, never
from a file in the tree and never from a default baked into code. Every value
here is therefore read from the environment, and a missing one is a named,
listed failure rather than a silent fallback.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from shared_schema.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

#: The connection string every command needs.
DATABASE_URL = "DATABASE_URL"

#: The seed Administrator's credentials. Email and password are required when
#: the seed actually has work to do; the name is optional and has a default
#: that is a label, not a credential.
SEED_ADMIN_EMAIL = "SEED_ADMIN_EMAIL"
SEED_ADMIN_PASSWORD = "SEED_ADMIN_PASSWORD"
SEED_ADMIN_NAME = "SEED_ADMIN_NAME"

DEFAULT_SEED_ADMIN_NAME = "Rocell Administrator"


class ConfigurationError(RuntimeError):
    """A required environment variable is missing or breaks a stated rule."""


@dataclass(frozen=True, slots=True)
class SeedAdminConfig:
    """The operator-supplied identity of the one seeded Administrator."""

    email: str
    password: str
    name: str


def _read(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def database_url(env: Mapping[str, str] | None = None) -> str:
    """Return `DATABASE_URL`, or raise naming it."""
    value = _read(env).get(DATABASE_URL, "").strip()
    if not value:
        raise ConfigurationError(
            f"{DATABASE_URL} is not set. The migration runner needs a PostgreSQL "
            f"connection string, e.g. {DATABASE_URL}=postgresql://user@host:5432/rocell"
        )
    return value


def seed_admin_config(env: Mapping[str, str] | None = None) -> SeedAdminConfig:
    """Return the seed Administrator's credentials, or raise listing what is wrong.

    Read *lazily*, only once the seed has established that it has work to do —
    an already-seeded database must migrate with no seed environment at all.
    """
    environ = _read(env)

    missing = [
        name
        for name in (SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD)
        if not environ.get(name, "").strip()
    ]
    if missing:
        raise ConfigurationError(
            "Cannot seed the first Administrator: "
            + ", ".join(missing)
            + (" is not set." if len(missing) == 1 else " are not set.")
        )

    email = environ[SEED_ADMIN_EMAIL].strip()
    # Not a full RFC 5322 parse — just enough that a shell mishap (an unset
    # variable expanded to a flag, a stray quote) fails here rather than
    # becoming an address nobody can log in as.
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ConfigurationError(
            f"{SEED_ADMIN_EMAIL} does not look like an email address: {email!r}"
        )

    # Deliberately not stripped: leading and trailing whitespace is part of a
    # password, and silently trimming it would hash something other than what
    # the operator will type at the login screen.
    password = environ[SEED_ADMIN_PASSWORD]
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ConfigurationError(
            f"{SEED_ADMIN_PASSWORD} is too short: it must be at least "
            f"{MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ConfigurationError(
            f"{SEED_ADMIN_PASSWORD} is too long: it must be at most "
            f"{MAX_PASSWORD_LENGTH} characters."
        )

    name = environ.get(SEED_ADMIN_NAME, "").strip() or DEFAULT_SEED_ADMIN_NAME

    return SeedAdminConfig(email=email, password=password, name=name)
