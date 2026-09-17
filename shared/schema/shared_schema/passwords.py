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

import secrets
import threading
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

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


#: The complete set of rules a password being *set* has to satisfy, each as the
#: sentence a user is shown when it fails.
#:
#: They are messages rather than codes because both consumers show them
#: verbatim: `hash_password` raises one, and `apps/api`'s password endpoint puts
#: one in the error envelope that `apps/web` renders inline. EXPERIENCE.md:87
#: requires a rejected password to name the rule that failed — "length, reuse of
#: the temporary password" — and never a generic "invalid password", so the
#: wording is the contract and not decoration.
#:
#: Length is the whole list on purpose. A composition rule ("one digit, one
#: symbol") shrinks the search space an attacker has to cover; see
#: `MIN_PASSWORD_LENGTH`. Reuse of a *temporary* credential is a rule about one
#: specific account's stored digest rather than about the string, so it cannot
#: be decided here — `apps/api` owns that one, in the same rule-naming register.
PASSWORD_RULES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "empty": "A password must not be empty.",
        "too_short": f"A password must be at least {MIN_PASSWORD_LENGTH} characters.",
        "too_long": f"A password must be at most {MAX_PASSWORD_LENGTH} characters.",
    }
)


def password_rule_violation(password: str) -> str | None:
    """The message for the first rule `password` breaks, or `None` if it breaks none.

    The one statement of the length rules in the product. `hash_password`
    raises whatever this returns, and `apps/api`'s forced-change endpoint
    answers `422 weak_password` with it, so a caller that wants to refuse a
    password *before* paying for a 64 MiB Argon2id hash gets exactly the same
    verdict and exactly the same sentence as the hasher would have given.

    Story 1.7 reuses it for the signed-in self-service change rather than
    restating the rules, which is the point of it living here.
    """
    if not password:
        return PASSWORD_RULES["empty"]
    if len(password) < MIN_PASSWORD_LENGTH:
        return PASSWORD_RULES["too_short"]
    if len(password) > MAX_PASSWORD_LENGTH:
        return PASSWORD_RULES["too_long"]
    return None


def hash_password(password: str) -> str:
    """Hash a password with Argon2id, returning the encoded digest to store.

    The digest carries its own salt and parameters, so nothing else has to be
    persisted alongside it.

    Raises `ValueError` for a password that breaks a length rule — refused
    where it is supplied, the way `ApiError` refuses an empty code, rather than
    stored and discovered later. The rules themselves are
    `password_rule_violation`'s, so this function and every endpoint that
    pre-checks a password cannot drift apart about what is acceptable.
    """
    violation = password_rule_violation(password)
    if violation is not None:
        raise ValueError(violation)

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


#: The decoy digest `verify_dummy_password` verifies against, built on first
#: use and never rebuilt. Lazily, not at import time: a 64 MiB Argon2id hash on
#: import would be paid by every process that touches `shared_schema` —
#: including every test run — for a path most of them never take.
_DECOY_DIGEST: str | None = None

#: `apps/api` serves its sync endpoints from a threadpool, so two rejections
#: can reach the lazy build below at the same moment. Unlocked, both allocate a
#: 64 MiB Argon2id hash and one of them is thrown away — "built once" would be
#: true of the odds rather than of the code, and the cost is paid in the one
#: place the process is already under load.
_DECOY_LOCK = threading.Lock()


def _decoy_digest() -> str:
    """The module's one decoy digest, hashed on first use.

    The password behind it is generated at runtime and thrown away: nothing can
    present it, so the verify below can only ever fail. A digest *committed* to
    the tree would be a credential in the repository, which AGENTS.md Policy
    forbids even in fixtures.
    """
    global _DECOY_DIGEST
    # Read before taking the lock: every call after the first is a plain read
    # of a module global, and serialising those would put a mutex in front of
    # every failed login for no benefit.
    if _DECOY_DIGEST is None:
        with _DECOY_LOCK:
            # Re-read under the lock: the loser of the race must use the
            # winner's digest, not build a second one over the top of it.
            if _DECOY_DIGEST is None:
                # Same hasher, therefore the same pinned cost. A cheap decoy
                # would be measurably faster than a real verify and would
                # reintroduce exactly the timing signal this exists to remove.
                _DECOY_DIGEST = _HASHER.hash(secrets.token_urlsafe(32))
    return _DECOY_DIGEST


def warm_password_verifier() -> None:
    """Build the decoy digest now, so the first rejection does not pay for it.

    Called from `apps/api`'s startup. Without it the very first unknown-address
    rejection in a process costs two Argon2id hashes and every later one costs
    one — a difference a patient caller can measure, which is the whole signal
    `verify_dummy_password` exists to remove.
    """
    _decoy_digest()


def verify_dummy_password(password: str) -> bool:
    """Spend a real Argon2id verify and return `False`, always.

    A login endpoint that skips hashing when no account matches answers
    measurably faster for an unknown address than for a wrong password, and
    that difference enumerates accounts. Calling this on the no-such-user path
    makes the two cost the same work.

    It lives here rather than in `apps/api` for the reason the module docstring
    gives: a second `PasswordHasher` outside this file would let the decoy's
    parameters drift from the real verifier's, and a decoy that is cheaper than
    a real verify is not a decoy at all.

    The early return mirrors `verify_password` exactly — an empty or oversized
    candidate is refused there *before* hashing, so refusing it here after
    hashing would create the very asymmetry this closes, in the other
    direction.

    The first call also pays for building the decoy digest, so a process that
    has never rejected a login answers its first unknown address one hash
    slower than its second. `apps/api` warms this at startup rather than
    leaving that one observation on the table.
    """
    if not password or len(password) > MAX_PASSWORD_LENGTH:
        return False

    try:
        _HASHER.verify(_decoy_digest(), password)
    except VerificationError:
        return False

    # Unreachable in practice — nothing holds the decoy's password. Written as
    # a plain return rather than an assertion so that "always False" is true of
    # the code and not only of the odds.
    return False
