"""`DATABASE_URL` is required, never defaulted, and the failure says so.

Four documents now promise this behaviour — `README.md`, `infra/README.md`,
`CLAUDE.md` and `make dev`'s health-gate message — and nothing asserted it: the
suite's autouse fixture sets the variable, so the unset path was unreachable
from every other test in the package.

The environment is passed explicitly rather than patched into `os.environ`,
following `infra/tests/test_migrate.py`'s pattern: a test that mutated the
process environment would leak into whatever ran next in the same worker, and
what matters here is the function's rule, not where it happens to read from.
"""

from __future__ import annotations

import pytest
from api.db import DATABASE_URL, POOL_MAX_SIZE, DatabaseNotConfigured, database_url
from api.main import create_app
from fastapi.testclient import TestClient
from shared_schema import passwords


@pytest.mark.parametrize(
    ("environment", "why"),
    [
        pytest.param({}, "unset", id="unset"),
        pytest.param({DATABASE_URL: ""}, "empty", id="empty"),
        pytest.param({DATABASE_URL: "   "}, "whitespace", id="whitespace"),
    ],
)
def test_a_missing_connection_string_is_refused_by_name(
    environment: dict[str, str], why: str
) -> None:
    with pytest.raises(DatabaseNotConfigured) as refused:
        database_url(environment)

    # Named, because the fix is "set this variable" and a message that does not
    # say which one sends an operator reading logs.
    assert DATABASE_URL in str(refused.value), why


def test_nothing_is_substituted_for_a_missing_connection_string() -> None:
    # A service that guesses a connection string can talk to the wrong
    # database. The example in the message must stay an example: if the
    # function ever returned it, this is what catches that.
    with pytest.raises(DatabaseNotConfigured):
        database_url({})


def test_a_configured_connection_string_is_returned_verbatim_but_trimmed() -> None:
    url = "postgresql://rocell@db.internal:5432/rocell"

    assert database_url({DATABASE_URL: url}) == url
    # A trailing newline is what a `$(cat secret)` or a copied line produces,
    # and libpq will not parse one.
    assert database_url({DATABASE_URL: f"  {url}\n"}) == url


def test_an_app_built_without_its_lifespan_says_so_rather_than_failing_obscurely(
    migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `TestClient(app)` used as a plain constructor never runs the lifespan, so
    # there is no pool. Without the guard the first request dies on
    # `AttributeError: 'State' object has no attribute 'pool'`.
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    client = TestClient(create_app(), base_url="https://testserver")

    with pytest.raises(DatabaseNotConfigured, match="lifespan"):
        client.get("/auth/session")


def test_startup_warms_the_password_verifier(
    migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Deleting the `warm_password_verifier()` call from the lifespan leaves
    # every other test green while reintroducing a once-per-process timing
    # difference on the unknown-address path: the first rejection would pay for
    # two Argon2id hashes and every later one for a single hash, which is
    # precisely the signal `verify_dummy_password` exists to remove (DW-24).
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    # Restored by monkeypatch when the test ends, so no later test pays for a
    # rebuild it did not ask for.
    monkeypatch.setattr(passwords, "_DECOY_DIGEST", None)

    with TestClient(create_app(), base_url="https://testserver"):
        assert passwords._DECOY_DIGEST is not None


def test_the_pool_is_closed_when_the_application_stops(
    migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A pool left open holds its connections for the life of the process, and
    # `--reload` restarts one on every file save.
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    app = create_app()

    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/auth/session").status_code == 401
        pool = app.state.pool

    assert pool.closed
    assert app.state.pool is None


def test_startup_does_not_wait_for_a_reachable_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The pool is opened without waiting, so a momentarily unreachable database
    # does not turn into a service that will not boot — and `/health`, which
    # touches no database, is meaningful precisely then.
    monkeypatch.setenv(DATABASE_URL, "postgresql://rocell@127.0.0.1:1/rocell")

    with TestClient(create_app(), base_url="https://testserver") as client:
        assert client.get("/health").status_code == 200


def test_a_connection_is_returned_to_the_pool_after_every_request(
    migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `get_connection` is the one place every database-backed route borrows
    # from, and a borrow that is never returned is invisible to the rest of the
    # suite: the busiest test makes seven requests against a pool of ten and
    # then tears the app down. In a process that stays up, request eleven blocks
    # for `POOL_TIMEOUT_SECONDS` and every request after it fails the same way —
    # a service that works for a handful of calls after each restart.
    #
    # `GET /auth/session` with no cookie is the cheapest route that takes the
    # dependency: it borrows, answers 401, and hashes nothing.
    monkeypatch.setenv(DATABASE_URL, migrated_url)

    with TestClient(create_app(), base_url="https://testserver") as client:
        for _ in range(POOL_MAX_SIZE + 2):
            assert client.get("/auth/session").status_code == 401
