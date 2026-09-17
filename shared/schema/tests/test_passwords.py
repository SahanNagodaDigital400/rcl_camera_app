"""The hashing path is shared by the migration seed and the login verifier.

Every password used here is generated at runtime. AGENTS.md Policy forbids a
committed credential *including in test fixtures*, and a literal in this file
would be one.
"""

from __future__ import annotations

import secrets

import pytest
from argon2.exceptions import InvalidHashError
from shared_schema.passwords import (
    ARGON2ID_PREFIX,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    verify_password,
)

#: RFC 9106's second recommended configuration, as the encoded digest spells it
#: out: Argon2 version 19, 64 MiB, three passes, four lanes. Transcribed here
#: rather than imported from the module under test, so that lowering the cost
#: has to be done in two places and shows up in a diff as what it is.
EXPECTED_PARAMETERS = "$v=19$m=65536,t=3,p=4$"


def a_password(length: int = MIN_PASSWORD_LENGTH + 8) -> str:
    """A password of exactly `length` characters, never the same one twice."""
    return secrets.token_urlsafe(length * 2)[:length]


def test_a_hashed_password_verifies() -> None:
    password = a_password()

    assert verify_password(hash_password(password), password) is True


def test_the_digest_is_argon2id() -> None:
    # Not merely "some Argon2": a swap to argon2i or argon2d would still
    # verify its own hashes and would still pass every other test here.
    assert hash_password(a_password()).startswith(ARGON2ID_PREFIX)


def test_the_digest_carries_the_pinned_cost_parameters() -> None:
    # The module pins time, memory and parallelism by value precisely so a
    # library upgrade cannot move them silently — and nothing asserted them, so
    # dropping to m=1024,t=1 left the whole suite green: the digest still starts
    # `$argon2id$`, still verifies against itself, and still salts per hash.
    # Every stored password in the product is only as strong as this line.
    assert EXPECTED_PARAMETERS in hash_password(a_password())


def test_the_salt_and_hash_are_the_pinned_lengths() -> None:
    # The two lengths the encoded parameters do not carry. Base64 without
    # padding: 16 salt bytes are 22 characters, 32 hash bytes are 43.
    salt, digest = hash_password(a_password()).rsplit("$", 2)[-2:]

    assert (len(salt), len(digest)) == (22, 43)


def test_another_password_is_rejected() -> None:
    password_hash = hash_password(a_password())

    assert verify_password(password_hash, a_password()) is False


def test_a_near_miss_is_rejected() -> None:
    password = a_password()
    password_hash = hash_password(password)

    assert verify_password(password_hash, password + "x") is False
    assert verify_password(password_hash, password[:-1]) is False
    assert verify_password(password_hash, password.upper()) is False


def test_two_hashes_of_one_password_differ() -> None:
    # A per-hash salt. Equal digests would mean every account sharing a
    # password is identifiable from the column alone.
    password = a_password()

    assert hash_password(password) != hash_password(password)


def test_both_hashes_of_one_password_still_verify() -> None:
    password = a_password()

    assert verify_password(hash_password(password), password) is True
    assert verify_password(hash_password(password), password) is True


def test_an_empty_password_is_refused() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        hash_password("")


@pytest.mark.parametrize("length", [1, MIN_PASSWORD_LENGTH - 2, MIN_PASSWORD_LENGTH - 1])
def test_a_short_password_is_refused(length: int) -> None:
    with pytest.raises(ValueError, match=f"at least {MIN_PASSWORD_LENGTH}"):
        hash_password(a_password(length))


def test_the_minimum_length_itself_is_accepted() -> None:
    password = a_password(MIN_PASSWORD_LENGTH)

    assert verify_password(hash_password(password), password) is True


@pytest.mark.parametrize("length", [MAX_PASSWORD_LENGTH + 1, MAX_PASSWORD_LENGTH * 10])
def test_an_oversized_password_is_refused(length: int) -> None:
    # Argon2id's cost is deliberately high. Without a ceiling, Story 1.3's
    # unauthenticated login endpoint would hash whatever it is sent.
    with pytest.raises(ValueError, match=f"at most {MAX_PASSWORD_LENGTH}"):
        hash_password(a_password(length))


def test_the_maximum_length_itself_is_accepted() -> None:
    password = a_password(MAX_PASSWORD_LENGTH)

    assert verify_password(hash_password(password), password) is True


def test_an_oversized_candidate_never_verifies() -> None:
    # Rejected before hashing: hashing a multi-megabyte candidate to find out
    # it is wrong is the attack, not the check.
    password_hash = hash_password(a_password())

    assert verify_password(password_hash, a_password(MAX_PASSWORD_LENGTH + 1)) is False


def test_a_short_candidate_still_verifies_against_its_own_hash() -> None:
    # The minimum is a rule about setting a password, not about checking one:
    # applying it here would lock out every existing account the day it rises.
    password = a_password(MIN_PASSWORD_LENGTH)
    password_hash = hash_password(password)

    assert verify_password(password_hash, password) is True
    assert verify_password(password_hash, password[:4]) is False


def test_an_empty_candidate_never_verifies() -> None:
    assert verify_password(hash_password(a_password()), "") is False


def test_a_malformed_stored_digest_is_not_reported_as_a_wrong_password() -> None:
    # A column holding something this module did not write is a data-integrity
    # fault. Returning False would hide it behind "wrong password" forever.
    with pytest.raises(InvalidHashError):
        verify_password("not-a-digest", a_password())
