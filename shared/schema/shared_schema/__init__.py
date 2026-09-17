"""Shared contracts between `apps/web` and `apps/api`.

Every type here is part of a cross-layer agreement: the Python definition and
its TypeScript twin under `shared_schema/ts/` must stay in step, because
`apps/api` serialises against one and `apps/web` compiles against the other.

Glossary terms from the PRD (`Tile`, `Category`, `Size`, `Code`,
`ReferenceImage`, `Scan`, `Candidate`, `Catalogue`, `Staff`, `Administrator`,
`Session`) are used verbatim as PascalCase names here. `Product` and `Face` are
retired by AD-18 and must not appear.
"""

from shared_schema.errors import ApiError, ErrorBody, ErrorEnvelope
from shared_schema.passwords import (
    hash_password,
    password_rule_violation,
    verify_dummy_password,
    verify_password,
    warm_password_verifier,
)
from shared_schema.user import Role, User

__all__ = [
    "ApiError",
    "ErrorBody",
    "ErrorEnvelope",
    "Role",
    "User",
    "hash_password",
    "password_rule_violation",
    "verify_dummy_password",
    "verify_password",
    "warm_password_verifier",
]
