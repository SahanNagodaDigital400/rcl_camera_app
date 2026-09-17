"""The hashing path is shared by the migration seed and the login verifier.

Every password used here is generated at runtime. AGENTS.md Policy forbids a
committed credential *including in test fixtures*, and a literal in this file
would be one.
"""

from __future__ import annotations

import secrets
import threading
from pathlib import Path

import pytest
from argon2.exceptions import InvalidHashError
from shared_schema import passwords
from shared_schema.passwords import (
    ARGON2ID_PREFIX,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    verify_dummy_password,
    verify_password,
    warm_password_verifier,
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


# --- The decoy verifier (DW-24) ---------------------------------------------
#
# `verify_dummy_password` exists so `apps/api`'s login can spend the same work
# on an address that does not exist as on one that does. Everything below is
# about that equivalence holding: a decoy that returned early, hashed cheaply,
# or was rebuilt per call would each leave the timing signal in place while the
# login tests stayed green.


def test_the_decoy_never_verifies() -> None:
    assert verify_dummy_password(a_password()) is False


@pytest.mark.parametrize(
    "candidate",
    ["", a_password(1), a_password(MIN_PASSWORD_LENGTH), a_password(MAX_PASSWORD_LENGTH + 1)],
)
def test_the_decoy_rejects_every_input(candidate: str) -> None:
    # Including the two `verify_password` refuses before hashing. The decoy has
    # to answer those the same way, or the early return is itself a signal.
    assert verify_dummy_password(candidate) is False


def test_the_decoy_digest_is_argon2id_at_the_pinned_cost() -> None:
    # A cheap decoy is measurably faster than a real verify and defeats the
    # entire point. It is built by the same `_HASHER`, and this is what says so.
    warm_password_verifier()
    digest = passwords._DECOY_DIGEST

    assert digest is not None
    assert digest.startswith(ARGON2ID_PREFIX)
    assert EXPECTED_PARAMETERS in digest


def test_the_decoy_digest_is_built_once_and_reused() -> None:
    warm_password_verifier()
    first = passwords._DECOY_DIGEST

    verify_dummy_password(a_password())
    verify_dummy_password(a_password())

    assert passwords._DECOY_DIGEST is first


def test_concurrent_first_calls_share_one_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    # `apps/api` serves its sync endpoints from a threadpool, so two
    # simultaneous rejections can both reach the lazy build. Unlocked, both
    # allocate a 64 MiB Argon2id hash and one is thrown away — and the caller
    # that loses the race would verify against a digest the module no longer
    # holds. Every thread must come back with the *same object*.
    monkeypatch.setattr(passwords, "_DECOY_DIGEST", None)
    start = threading.Barrier(4)
    seen: list[str] = []
    lock = threading.Lock()

    def build() -> None:
        start.wait()
        digest = passwords._decoy_digest()
        with lock:
            seen.append(digest)

    threads = [threading.Thread(target=build) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(seen) == 4
    assert all(digest is seen[0] for digest in seen)


def test_the_decoy_digest_is_not_built_at_import_time() -> None:
    # A 64 MiB Argon2id hash on import would be paid by every process that
    # imports `shared_schema`, including every test run, for a path most of
    # them never take. The module-level default is what keeps it lazy.
    source = Path(passwords.__file__).read_text(encoding="utf-8")

    assert "_DECOY_DIGEST: str | None = None" in source


def test_warming_the_verifier_is_idempotent() -> None:
    warm_password_verifier()
    warmed = passwords._DECOY_DIGEST
    warm_password_verifier()

    assert passwords._DECOY_DIGEST is warmed


def test_no_decoy_digest_is_committed_to_the_source() -> None:
    # AGENTS.md Policy forbids a committed credential, fixtures included. The
    # decoy's password is generated at runtime and thrown away; a digest
    # pasted into the file would be a credential in the repository.
    source = Path(passwords.__file__).read_text(encoding="utf-8")

    assert source.count(ARGON2ID_PREFIX) == 1, "only the prefix constant may name it"
    assert "secrets.token_urlsafe" in source
