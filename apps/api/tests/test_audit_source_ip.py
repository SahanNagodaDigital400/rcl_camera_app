"""AD-4's trust boundary: where `source_ip` may come from, and where it may not.

The clause is one sentence — "`source_ip` is captured only from the trusted
reverse-proxy header, never a raw client-supplied one" — and it has a trap in
it. Read literally it says *always read a header*, which with no proxy in front
of the service means always trusting whatever the caller typed. `api.audit`
reads the inversion: a header is read only when `TRUSTED_PROXY_HEADER` names
one, and otherwise the value is the TCP peer, which the caller cannot forge.

So this file is mostly about what does **not** reach the column. Every
spoofing case asserts the submitted value appears in no row at all, rather than
only that the recorded value is the right one — an assertion on the right value
alone would pass against an implementation that recorded both.

The unit half exercises `api.audit.source_ip` against a hand-built `Request`,
because several of its cases (no peer at all, a header carrying a chain of
hops) are not reachable through `TestClient`. The endpoint half drives
`POST /auth/login` and reads the row, because a dependency that is correct and
not wired to anything is worth nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from api import audit
from api.audit import TRUSTED_PROXY_HEADER
from api.db import DATABASE_URL
from api.main import create_app
from fastapi.testclient import TestClient
from starlette.requests import Request

LOGIN = "/auth/login"

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, Any]]]

#: The address a spoofing caller sends. Documentation range (RFC 5737), so it
#: cannot collide with anything real and is obviously deliberate in a failure
#: message.
SPOOFED = "203.0.113.99"

#: The address the proxy would legitimately report.
FORWARDED = "198.51.100.7"

#: What `conftest.client` presents as its peer.
PEER = "127.0.0.1"

#: A header name an operator might configure. Lowercase because ASGI
#: normalizes header names, and `Request.headers` is case-insensitive either
#: way — asserted below rather than assumed.
PROXY_HEADER = "x-real-ip"


def _request(
    client_host: str | None,
    headers: dict[str, str] | None = None,
    *,
    lines: list[tuple[str, str]] | None = None,
) -> Request:
    """A bare ASGI scope, for the cases a `TestClient` cannot produce.

    `headers` is the ordinary one-line-per-name case. `lines` is the raw list,
    for the repeated-header case a `dict` cannot express — HTTP permits the
    same field name more than once and the whole of P1's spoof lives in that
    gap.
    """
    raw = lines if lines is not None else list((headers or {}).items())
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/auth/login",
        "headers": [(name.encode("latin-1"), value.encode("latin-1")) for name, value in raw],
        "client": None if client_host is None else (client_host, 51234),
    }
    return Request(scope)


# --- Unset: the peer, and only the peer ---------------------------------------


def test_with_no_configured_header_the_peer_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    assert audit.source_ip(_request(PEER)) == PEER


def test_with_no_configured_header_a_forwarded_header_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The spoof, at the unit level. Every request header is client-supplied
    # until something in front of the service overwrites it, and nothing does.
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    resolved = audit.source_ip(_request(PEER, {"x-forwarded-for": SPOOFED}))
    assert resolved == PEER


def test_an_empty_configured_header_name_is_the_same_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An operator who writes `TRUSTED_PROXY_HEADER=` in an env file has
    # configured nothing, and the safe reading of nothing is the peer.
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, "   ")
    assert audit.source_ip(_request(PEER, {"x-forwarded-for": SPOOFED})) == PEER


def test_a_peer_that_is_not_an_address_is_not_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Starlette's own `TestClient` default is the literal string `testclient`,
    # so this is not a hypothetical shape: an unvalidated peer would put it in
    # the column. Nothing that is not an address reaches the row.
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    assert audit.source_ip(_request("testclient")) is None


def test_a_request_with_no_peer_at_all_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    assert audit.source_ip(_request(None)) is None


def test_an_ipv6_peer_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    # `ipaddress.ip_address` accepts both families and the column is `text`,
    # so there is nothing to do here — asserted so that a later narrowing to
    # IPv4 has to be a deliberate edit.
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    assert audit.source_ip(_request("2001:db8::1")) == "2001:db8::1"


@pytest.mark.parametrize(
    ("submitted", "stored"),
    [
        ("2001:0db8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
        ("2001:DB8::1", "2001:db8::1"),
        ("::FFFF:198.51.100.7", "::ffff:198.51.100.7"),
        # Already canonical: the normalisation must be a no-op on the common
        # case, or every existing assertion in this suite is measuring it.
        ("198.51.100.7", "198.51.100.7"),
        (PEER, PEER),
    ],
)
def test_an_address_is_stored_in_one_canonical_spelling(
    monkeypatch: pytest.MonkeyPatch, submitted: str, stored: str
) -> None:
    # One host has many spellings and `source_ip` is a `text` column, so
    # whatever reaches it is what a later `=` or `GROUP BY` compares. Return
    # the raw string instead of `str(ip_address(...))` and Story 1.13's
    # "everything from this address" filter silently splits one host into
    # several — the values still *look* right in every other test here,
    # because they all submit addresses that are already canonical.
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    assert audit.source_ip(_request(submitted)) == stored


# --- Set: the named header, and only the named header -------------------------


def test_the_configured_header_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, PROXY_HEADER)
    assert audit.source_ip(_request(PEER, {PROXY_HEADER: FORWARDED})) == FORWARDED


def test_the_configured_header_name_is_matched_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An operator will write `X-Real-IP` as often as `x-real-ip`, and a
    # configuration that silently resolved to NULL for the difference would be
    # the worst of both worlds: no error, and no address.
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, "X-Real-IP")
    assert audit.source_ip(_request(PEER, {"x-real-ip": FORWARDED})) == FORWARDED


def test_the_last_element_of_a_chain_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    # `X-Forwarded-For` appends rather than replaces: each hop adds the peer it
    # saw. Everything before the last element was written by something further
    # out than the trusted proxy — which is to say, by the client.
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, "x-forwarded-for")
    chain = f"{SPOOFED}, 192.0.2.1, {FORWARDED}"
    assert audit.source_ip(_request(PEER, {"x-forwarded-for": chain})) == FORWARDED


def test_the_last_header_line_wins_over_a_forged_first_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The spoof `headers.get` would fall for. A caller sends their own
    # `X-Forwarded-For:` line; the proxy in front appends a *second* line
    # rather than folding into the first, which HTTP permits and Starlette
    # preserves. `get` returns the first — the forged one. `getlist()[-1]` is
    # the line the proxy wrote, and it is the only one this service has any
    # reason to trust.
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, "x-forwarded-for")
    resolved = audit.source_ip(
        _request(
            PEER,
            lines=[("x-forwarded-for", SPOOFED), ("x-forwarded-for", FORWARDED)],
        )
    )
    assert resolved == FORWARDED
    assert resolved != SPOOFED


def test_a_forged_line_inside_a_forged_chain_still_loses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both appends at once: the caller sends a chain of their own, the proxy
    # adds a line of its own. The two rules compose — last line, then last
    # element — and nothing the caller wrote survives either of them.
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, "x-forwarded-for")
    resolved = audit.source_ip(
        _request(
            PEER,
            lines=[
                ("x-forwarded-for", f"{SPOOFED}, 192.0.2.50"),
                ("x-forwarded-for", FORWARDED),
            ],
        )
    )
    assert resolved == FORWARDED


def test_a_forged_first_line_reaches_no_row(
    migrated_url: str,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The same spoof end to end, asserted as "appears nowhere" rather than
    # only "the right value was stored".
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, "x-forwarded-for")
    account = make_user()

    with TestClient(create_app(), base_url="https://testserver", client=(PEER, 50000)) as client:
        # httpx sends one line per tuple, which is what makes this the real
        # shape rather than a comma-joined approximation.
        assert (
            client.post(
                LOGIN,
                json={"email": account.email, "password": account.password},
                headers=[
                    ("x-forwarded-for", SPOOFED),
                    ("x-forwarded-for", FORWARDED),
                ],
            ).status_code
            == 200
        )

    rows = audit_rows(conn)
    assert [row["source_ip"] for row in rows] == [FORWARDED]
    assert SPOOFED not in str(rows)


def test_a_missing_configured_header_records_nothing_and_never_the_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The misconfigured edge. The peer here is the proxy, so recording it
    # would put the load balancer's address on a user's action — a plausible
    # wrong answer, which is worse than no answer.
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, PROXY_HEADER)
    assert audit.source_ip(_request(PEER)) is None


def test_an_unparseable_configured_header_records_nothing_and_never_the_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, PROXY_HEADER)
    assert audit.source_ip(_request(PEER, {PROXY_HEADER: "not-an-address"})) is None


def test_an_empty_configured_header_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, PROXY_HEADER)
    assert audit.source_ip(_request(PEER, {PROXY_HEADER: ""})) is None


# --- Through the endpoint -----------------------------------------------------


def test_a_signed_in_users_peer_address_reaches_the_row(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    account = make_user()

    assert (
        client.post(LOGIN, json={"email": account.email, "password": account.password}).status_code
        == 200
    )

    rows = audit_rows(conn)
    assert [row["source_ip"] for row in rows] == [PEER]


def test_a_spoofed_forwarded_header_reaches_no_row(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The acceptance clause, end to end. Asserted as "appears nowhere" rather
    # than "the recorded value is the peer": an implementation that wrote both
    # would pass the second assertion and fail this one.
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    account = make_user()

    assert (
        client.post(
            LOGIN,
            json={"email": account.email, "password": account.password},
            headers={"X-Forwarded-For": SPOOFED},
        ).status_code
        == 200
    )

    rows = audit_rows(conn)
    assert rows != []
    assert SPOOFED not in {row["source_ip"] for row in rows}
    assert all(row["source_ip"] == PEER for row in rows)
    assert SPOOFED not in str(rows)


def test_a_failed_sign_in_records_the_peer_too(
    client: TestClient,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A refusal is where the address matters most — a run of them from one
    # place is the thing FR-22's anomaly work will read — so the refusal path
    # must carry it as well as the success path.
    monkeypatch.delenv(TRUSTED_PROXY_HEADER, raising=False)
    account = make_user()

    assert (
        client.post(LOGIN, json={"email": account.email, "password": "wrong-password"}).status_code
        == 401
    )

    rows = audit_rows(conn)
    assert [row["source_ip"] for row in rows] == [PEER]


def test_the_configured_header_reaches_the_row_through_the_endpoint(
    migrated_url: str,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Its own client, so the peer can be something other than the forwarded
    # address: with both the same, "the header was used" and "the peer was
    # used" are indistinguishable.
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, PROXY_HEADER)
    account = make_user()

    with TestClient(create_app(), base_url="https://testserver", client=(PEER, 50000)) as client:
        assert (
            client.post(
                LOGIN,
                json={"email": account.email, "password": account.password},
                headers={PROXY_HEADER: FORWARDED},
            ).status_code
            == 200
        )

    rows = audit_rows(conn)
    assert [row["source_ip"] for row in rows] == [FORWARDED]
    assert PEER not in {row["source_ip"] for row in rows}


def test_a_configured_header_the_caller_omits_leaves_the_column_null(
    migrated_url: str,
    conn: psycopg.Connection,
    make_user: MakeUser,
    audit_rows: AuditRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL, migrated_url)
    monkeypatch.setenv(TRUSTED_PROXY_HEADER, PROXY_HEADER)
    account = make_user()

    with TestClient(create_app(), base_url="https://testserver", client=(PEER, 50000)) as client:
        assert (
            client.post(
                LOGIN, json={"email": account.email, "password": account.password}
            ).status_code
            == 200
        )

    rows = audit_rows(conn)
    assert [row["source_ip"] for row in rows] == [None]
