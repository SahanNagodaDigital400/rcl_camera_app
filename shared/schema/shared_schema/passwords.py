"""The one password-hashing path in the product.

AGENTS.md Policy fixes Argon2id and nothing else. Two callers have to execute
*identical* parameters against the same digests: the migration seed in `infra`
(which writes the first Administrator's hash) and the login verifier in
`apps/api` (which reads it back). A second `PasswordHasher` anywhere would let
those parameters drift, and a seeded password that login cannot verify is a
silent failure — the account simply never works and nothing raises.

So the parameters live here, pinned explicitly rather than inherited from the
library's defaults, and both callers import `hash_password` / `verify_password`
from this module. `shared/*` is the only direction `infra` and `apps/api` may
both depend on.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from argon2.low_level import Type

#: The shortest password the product will hash. Length is the only strength
#: rule enforced here: a composition rule ("one digit, one symbol") shrinks the
#: search space an attacker has to cover, which is the opposite of the intent.
MIN_PASSWORD_LENGTH = 12

#: The longest. Argon2id's cost is deliberately high, and Story 1.3's login
#: endpoint is unauthenticated: without a ceiling, anyone can make the server
#: hash a multi-megabyte string on demand, which is a CPU-exhaustion vector
#: rather than a login attempt. Comfortably above any passphrase a person
#: types, so it costs a real user nothing.
MAX_PASSWORD_LENGTH = 128

#: Every digest this module writes starts with this. Asserted by the tests so a
#: swap to another Argon2 variant (argon2i, argon2d) cannot pass unnoticed.
ARGON2ID_PREFIX = "$argon2id$"

# RFC 9106's second recommended configuration: 64 MiB, three passes, four
# lanes. Pinned by value, not defaulted, because a library upgrade that moved
# the defaults would otherwise silently change what this module produces.
_TIME_COST = 3
_MEMORY_COST_KIB = 64 * 1024
_PARALLELISM = 4
_HASH_LENGTH = 32
_SALT_LENGTH = 16

_HASHER = PasswordHasher(
    time_cost=_TIME_COST,
    memory_cost=_MEMORY_COST_KIB,
    parallelism=_PARALLELISM,
    hash_len=_HASH_LENGTH,
    salt_len=_SALT_LENGTH,
    type=Type.ID,
)


def hash_password(password: str) -> str:
    """Hash a password with Argon2id, returning the encoded digest to store.

    The digest carries its own salt and parameters, so nothing else has to be
    persisted alongside it.

    Raises `ValueError` for a password that breaks a length rule — refused
    where it is supplied, the way `ApiError` refuses an empty code, rather than
    stored and discovered later.
    """
    if not password:
        raise ValueError("A password must not be empty.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"A password must be at most {MAX_PASSWORD_LENGTH} characters.")

    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return whether `password` is the password behind `password_hash`.

    A wrong password is an ordinary outcome and returns `False`. A *malformed*
    stored digest is not: it means the column holds something this module did
    not write, and swallowing it would report a data-integrity fault as "wrong
    password" forever. `InvalidHashError` is not a `VerificationError` in
    argon2-cffi, so it passes through this handler untouched — deliberately.

    An oversized candidate is rejected *before* hashing rather than raised: on
    an unauthenticated login path, hashing a multi-megabyte candidate to find
    out it is wrong is the attack, not the check. The *minimum* is deliberately
    not applied here — that is a rule about passwords being set, and enforcing
    it on verification would lock out every existing account the day it rises.
    """
    if not password or len(password) > MAX_PASSWORD_LENGTH:
        return False

    try:
        return _HASHER.verify(password_hash, password)
    except VerificationError:
        return False
