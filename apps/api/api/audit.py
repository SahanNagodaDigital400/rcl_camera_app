"""The append-only audit log's one write path (FR-20, NFR4, AD-4).

**This is the only file in the repository that names the `audit_log` table**,
exactly as `api.sessions` owns `sessions` and `api.throttle` owns
`login_attempts`, and `tests/test_source_guards.py` enforces it. A second
`INSERT` written wherever it was first needed would be a second opinion about
what an entry means; a second `UPDATE` would be the thing AD-4 exists to make
impossible.

Four things about this module are load-bearing.

**The entry is part of the unit of work, never a side effect.** Every call to
`record` below sits inside the same `with conn.transaction():` as the change it
records, so the change and its record commit together or neither does. Where
the "change" is a refusal on an autocommit connection — a failed sign-in — the
insert commits exactly the way the throttle counter beside it already does.
And an insert that fails **fails the request**. That deliberately breaks this
codebase's precedent for secondary writes: `sessions._touch_session`,
`throttle._mirror`, `throttle._sweep` and `sessions.delete_expired_sessions`
all swallow `psycopg.Error` so a fault in a tidy-up never decides a response.
Those are tidy-up. This one is the record of record — FR-20 and NFR4 say the
log is what makes an action attributable, so an action that happened with no
entry is precisely the state this module exists to prevent. `record` therefore
lets every `psycopg.Error` propagate, and `api.main`'s handler answers 500.

**Immutability is PostgreSQL's, not this module's.** `api.db` adopts the
`rocell_app` role at connection startup and
`infra/migrations/20260921T1000_create_audit_log` grants that role `SELECT,
INSERT` on this table and nothing more. There is no `UPDATE` statement here to
review, and if one were added it would fail at runtime with
`InsufficientPrivilege` rather than quietly working. AD-4: a wrong entry is
corrected by inserting a corrective entry.

**Actor and target are snapshots, not foreign keys (AD-10).** Each is stored as
an id *and* an address. `DELETE /admin/users/{id}` is a hard delete and the
application role holds no `DELETE` on this table, so a foreign key would force
a choice between blocking every user delete and cascading into a table nothing
may delete from. The id joins while the row lives; the address is what the
entry still means after it does not.

**Nothing secret ever reaches a row.** Not a password, not a password hash, not
a session token, not a token hash — not in a column and not in `details`. The
address a failed sign-in submitted *may* be recorded, and that is the one place
in the product where it is: `api.throttle` refuses to put it in the application
log precisely because that log has none of this table's protections, and this
table has all of them.

**Not here.** No read surface — no route, no query function, no pagination:
Story 1.13 owns reading the log and the shared contract type that goes with it,
which is also why nothing in `shared/schema` changed for this story. No
catalogue or scan events (Epics 2–3 add their own actions to `AuditAction`, and
any table they add needs its own `GRANT` in its own migration). No seed events:
`infra/rocell_infra/seed.py` and `make reseed-admin` run outside the
application, with no actor and no request, and inventing one would be the log
asserting something it does not know. And no retention or purge — a purge is a
`DELETE`, which this role cannot issue.
"""

from __future__ import annotations

import ipaddress
import os
from enum import StrEnum
from typing import Any
from uuid import UUID

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a dependency's
# annotations at runtime to build its graph, so a name that exists only for the
# type checker fails at import with a bare NameError.
import psycopg
from fastapi import Request
from psycopg.types.json import Jsonb


class AuditAction(StrEnum):
    """Every action this product records, and the whole vocabulary of `action`.

    `StrEnum`, matching `shared_schema.user.Role`: the member *is* its stored
    string, so a value passed to psycopg needs no `.value` and a value read
    back compares equal to the member.

    Deliberately **not** a database CHECK constraint. The vocabulary grows with
    every epic, and a constraint would make each addition a migration that has
    to be applied before the code that writes the value — the exact ordering
    hazard `infra/README.md` warns about, paid repeatedly for a rule no query
    depends on.

    The names distinguish things a caller cannot: seven different causes
    answer a sign-in with the same `401`, and all seven are `LOGIN_FAILED`
    here with `details.reason` telling them apart (`api.auth`'s `REASON_*`
    constants — six reached through one funnel, plus `malformed_address`).
    That asymmetry is the point of the log: the refusal leaks nothing, the
    record explains everything.
    """

    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGIN_REFUSED_LOCKED = "login_refused_locked"
    LOGGED_OUT = "logged_out"
    PASSWORD_CLAIMED = "password_claimed"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_CHANGE_REFUSED = "password_change_refused"
    SESSIONS_REVOKED = "sessions_revoked"
    USER_PROVISIONED = "user_provisioned"
    USER_EDITED = "user_edited"
    USER_DEACTIVATED = "user_deactivated"
    USER_ACTIVATED = "user_activated"
    USER_DELETED = "user_deleted"


#: The environment variable naming the header a trusted reverse proxy sets with
#: the real client address — `x-forwarded-for`, `x-real-ip`, `cf-connecting-ip`,
#: whichever the eventual edge layer uses.
#:
#: **Unset by default, and that is the safe default rather than an oversight.**
#: AD-4 forbids reading `source_ip` from a raw client-supplied header, and every
#: request header is client-supplied until something in front of the service
#: overwrites it. With no proxy in the repository and none chosen (hosting is a
#: deferred decision in the spine), there is nothing that overwrites one — so
#: unset, this product reads the TCP peer and can never be spoofed. Set, the
#: named header is the *only* source and the peer is ignored, because a
#: fallback to the peer would record the proxy's own address as a user's and
#: quietly make the log wrong rather than empty.
TRUSTED_PROXY_HEADER = "TRUSTED_PROXY_HEADER"


#: One row, one statement, fully parameterized. `id` and `created_at` take
#: their column defaults: the timestamp is the database's clock, not this
#: host's, and nothing in the product may choose either.
#:
#: `details` is passed as `Jsonb`, so psycopg adapts a `dict` to the column
#: rather than this module serialising JSON by hand — a hand-built string is a
#: second encoder to keep in step with the first.
#:
#: No `RETURNING`. Nothing reads an entry back in this story (Story 1.13 owns
#: the read surface), and a `RETURNING` nobody consumes is a column list that
#: drifts unnoticed.
_INSERT_ENTRY = """
INSERT INTO audit_log (action, actor_user_id, actor_email,
                       target_user_id, target_email, source_ip, details)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def source_ip(request: Request) -> str | None:
    """The address this request came from, as AD-4's trust boundary defines it.

    Two sources, and never both:

    * `TRUSTED_PROXY_HEADER` **unset** — the TCP peer (`request.client.host`).
      Not a header, not client-supplied, and not forgeable by the caller: it is
      whatever address the kernel accepted the connection from. With no reverse
      proxy in front of the service, it is the client.
    * `TRUSTED_PROXY_HEADER` **set** — the named header, and only it. The peer
      is then the proxy and recording it would be recording the wrong machine,
      so it is not used as a fallback: a misconfigured edge produces `NULL`,
      which is honest, rather than a plausible address that is not the user's.

    The value is validated with `ipaddress.ip_address()` and stored as `NULL`
    when it does not parse. That is not tidiness — it is what stops an
    arbitrary client-supplied string reaching a text column that a later story
    will render, and it is why the header path cannot be used to write
    something that is not an address. What is stored is the *parsed* address in
    its canonical form, never the spelling it arrived in, so two entries about
    one host compare equal in a column that only knows how to compare strings.

    **The last line, then the last element of it.** `X-Forwarded-For` appends
    rather than replaces, and it appends in two ways a caller can exploit.
    Within one line it appends comma-separated elements, so the last element
    is the address the trusted proxy itself observed and everything before it
    was written further out — by the client, in the end. Across lines, HTTP
    permits the same field name more than once, and Starlette keeps the lines
    separate rather than folding them: a caller who sends their own
    `X-Forwarded-For:` line arrives at a proxy that adds a *second* one, and
    reading the first line (which `headers.get` does) would read the forged
    one. `getlist` and `[-1]` take the line the proxy appended, which is the
    only one this service has any reason to trust.

    A proxy that *replaces* the header rather than appending sends one line,
    and the same rule reads it correctly. A proxy that folds the caller's line
    into its own produces one line with the forged value in front of the real
    one, and the last-element rule handles that too. The two rules together
    are the same rule: trust the value written closest to us.

    A FastAPI dependency rather than middleware, for the reason
    `api.dependencies` gives at length about the forced-change gate: middleware
    would apply to a route table it cannot see, and declaring the requirement
    in the signature puts it where it is read. It lives beside the module that
    consumes it rather than in `api.dependencies`, which means "the
    authorization chain" and nothing else.
    """
    header = os.environ.get(TRUSTED_PROXY_HEADER, "").strip()

    if header:
        # `getlist`, not `get`: `get` returns the FIRST line of a repeated
        # header, which is the one a spoofing caller sent. See the docstring.
        forwarded = request.headers.getlist(header)
        if not forwarded:
            return None
        candidate = forwarded[-1].rsplit(",", 1)[-1].strip()
    else:
        client = request.client
        if client is None:
            # No peer at all. Reachable through an ASGI transport that does not
            # supply one; nothing is known, so nothing is recorded.
            return None
        candidate = client.host

    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    # The *parsed* address, not the string it came in as. One address has many
    # spellings — `2001:DB8::1`, `2001:db8:0:0:0:0:0:1` and `2001:db8::1` are
    # the same host — and a `text` column compared with `=` cannot tell. Story
    # 1.13's "everything from this address" filter and FR-22's anomaly work
    # both group on this value, so the normalisation has to happen before it is
    # stored or it cannot happen at all. `str()` on an `ip_address` is the
    # canonical form: lowercase, maximally compressed, no leading zeros.
    return str(parsed)


def record(
    conn: psycopg.Connection,
    *,
    action: AuditAction,
    actor_id: UUID | None = None,
    actor_email: str | None = None,
    target_id: UUID | None = None,
    target_email: str | None = None,
    source_ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one entry. Raises rather than swallowing — see the module docstring.

    Every argument but `action` is keyword-only and optional: seven of the
    eight are nullable columns, and a positional call site would be seven
    same-typed values in an order nobody can check by eye.

    No return value. There is nothing a caller can usefully do with the id in
    this story, and returning one would invite a second write that referenced
    it.

    **`details` must never carry a secret.** Not a password, not a digest, not
    a session token. There is no runtime check for that, because a check would
    have to know the shape of every future action's payload; the rule lives in
    this docstring, in the module's, and in the review of every call site.
    """
    conn.execute(
        _INSERT_ENTRY,
        (
            action,
            actor_id,
            actor_email,
            target_id,
            target_email,
            source_ip,
            Jsonb(details if details is not None else {}),
        ),
    )
