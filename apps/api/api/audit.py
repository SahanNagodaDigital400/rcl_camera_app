"""The append-only audit log's one write path, and its one read (FR-20, FR-21, NFR4, AD-4).

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

**The read lives here too, and only here (FR-21).** `GET /admin/audit` is at
the bottom of this file because the table has exactly one owning module, not
because a route had nowhere else to go: a `SELECT` written wherever it was
first needed is a second opinion about what an entry means, in the same way a
second `INSERT` would be. It is Administrator-only, newest first, and paged by
a keyset cursor — the order `infra/migrations/20260921T1000_create_audit_log`
built `audit_log_created_at_idx` for. It adds no statement AD-4 forbids: the
grant is `SELECT, INSERT`, so the read was already inside the granted set and
`UPDATE`, `DELETE` and `TRUNCATE` remain refused by PostgreSQL itself.

**Still not here.** No catalogue or scan events (Epics 2–3 add their own
actions to `AuditAction`, and any table they add needs its own `GRANT` in its
own migration). No seed events: `infra/rocell_infra/seed.py` and
`make reseed-admin` run outside the application, with no actor and no request,
and inventing one would be the log asserting something it does not know. No
filter, search or date range over the read — none is in FR-21, and a
caller-supplied `LIMIT` would be a denial-of-service knob on the one table
nobody may prune. And no retention or purge — a purge is a `DELETE`, which this
role cannot issue.

**And no entry for the read itself.** Opening the log is a privileged action
and it writes nothing: `AuditAction` has no member for a read, and `GET
/admin/audit` below inserts nothing. FR-20 and AGENTS.md enumerate sign-ins,
failed sign-ins and account changes, so this is outside the requirement as
written rather than a gap in it — but "who read the security record, and when"
is the one question this surface newly makes askable and cannot answer. Adding
it is a row per page of every read, in a table nobody may prune, so it waits on
the retention and volume answers the spine still defers.
"""

from __future__ import annotations

import ipaddress
import os
from typing import Annotated, Any
from uuid import UUID

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a dependency's
# annotations at runtime to build its graph, so a name that exists only for the
# type checker fails at import with a bare NameError.
import psycopg
from fastapi import APIRouter, Depends, Request, Response, status
from psycopg.types.json import Jsonb

# `AuditAction` and `PAGE_SIZE` are imported, not defined here, and every name
# this module already exported is unchanged: `api.auth` and `api.users` go on
# importing `AuditAction` *from this module*, and the handler below goes on
# reading `PAGE_SIZE` as a local name.
#
# Both moved to `shared_schema.audit` for the same reason — they stopped being
# the writer's private concern. The read surface below labels an entry from the
# enum and `apps/web` has to hold the same eighteen values; the screen has to
# know the page size to tell a last page from a full one, because the response
# is a bare array that says nothing about what follows it. **Knowing it is not
# choosing it**: this route declares no `limit` parameter and never will, for
# the reason `shared_schema.audit.PAGE_SIZE`'s own comment gives at length — a
# caller-supplied page size is a denial-of-service knob on the one table
# nobody may prune. Publishing the number the server picked leaves that
# untouched.
from shared_schema.audit import FLAGGED_AUDIT_ACTIONS, PAGE_SIZE, AuditAction, AuditLogEntry
from shared_schema.errors import ApiError
from shared_schema.user import User

from api.db import get_connection
from api.dependencies import NO_STORE, require_administrator

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
#: No `RETURNING`. Nothing reads an entry back at the point it is written —
#: `record` returns nothing, and the read surface below answers a later request
#: about the whole table rather than about one insert — and a `RETURNING`
#: nobody consumes is a column list that drifts unnoticed.
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
    # the same host — and a `text` column compared with `=` cannot tell. The
    # read surface below deliberately offers no filter at all, so the argument
    # for canonicalising stands on FR-22's anomaly grouping alone: that work
    # groups on this value, and the normalisation has to happen before the
    # value is stored or it cannot happen at all. It is also what an
    # Administrator reading two rows off the screen compares by eye. `str()` on
    # an `ip_address` is the canonical form: lowercase, maximally compressed,
    # no leading zeros.
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


#: The cursor named no entry. Distinct from an exhausted log, which is `[]`
#: with a `200`: one means "there is nothing older than the row you named", the
#: other means "the row you named is not in this table". Collapsing them would
#: turn a client bug — or a hand-typed id — into a silently empty screen.
#:
#: The table has no delete path, so a cursor that resolved once resolves
#: forever. A `404` here can therefore only mean the id was invented.
AUDIT_ENTRY_NOT_FOUND = "audit_entry_not_found"

#: What that `404` says. Short and factual (EXPERIENCE.md's register), and it
#: names the cursor rather than the log, because the log is fine.
NO_SUCH_ENTRY = "No audit entry has that id."


#: The first page: the newest `PAGE_SIZE` entries.
#:
#: **The column list is the nine columns `AuditLogEntry` declares**, which is
#: also `_INSERT_ENTRY`'s column list plus the two the table fills itself.
#: `tests/test_audit_read.py` holds it to `set(AuditLogEntry.model_fields)`, so
#: a column added to the table and forgotten in the contract fails at
#: collection time rather than as an extra key on the wire.
#:
#: **`ORDER BY created_at DESC, id DESC`, and the tiebreaker is not
#: decoration.** `created_at` defaults to `now()`, which is the *transaction*
#: timestamp, so two entries written by one request — a deactivation and its
#: revocation — share it to the microsecond. A sort on `created_at` alone has
#: no total order, which means no stable page boundary and no cursor that can
#: be trusted not to repeat or skip a row. The migration wrote
#: `audit_log_created_at_idx` over exactly this pair for exactly this read.
#:
#: `LIMIT %s` is a parameter, not a formatted number: `PAGE_SIZE` is ours and
#: could safely be interpolated, and interpolating it anyway would be the habit
#: `tests/test_source_guards.py` exists to stop before it reaches a value that
#: is not ours.
_SELECT_LATEST_ENTRIES = """
SELECT id, created_at, action, actor_user_id, actor_email,
       target_user_id, target_email, source_ip, details
FROM audit_log
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

#: The next page: the newest `PAGE_SIZE` entries strictly older than one row.
#:
#: **Keyset, not `OFFSET`.** Entries land at the *top* of this order between
#: two requests — every sign-in writes one — so `OFFSET 50` after a page of
#: fifty would re-serve rows the reader has already seen, one for every entry
#: written in between. The row comparison `(created_at, id) < (...)` is stable
#: under insertion: it asks for what is older than a specific row rather than
#: for a position in a list that keeps growing from the other end.
#:
#: **The cursor is one id, and the statement resolves the pair itself.** A
#: `(timestamp, id)` cursor would be two query parameters that are only valid
#: together, which needs a hand-written "both or neither" refusal FastAPI
#: cannot express; one id is self-consistent, is a value the client already
#: holds, and — because this table has no delete path — can only fail to
#: resolve if a caller invented it, which is what `AUDIT_ENTRY_NOT_FOUND`
#: says. The subquery is the same index lookup the planner would do for a
#: literal pair.
#:
#: `<` and not `<=`: the row named by the cursor is the last one already
#: rendered, so including it would repeat it at the top of every page.
_SELECT_ENTRIES_BEFORE = """
SELECT id, created_at, action, actor_user_id, actor_email,
       target_user_id, target_email, source_ip, details
FROM audit_log
WHERE (created_at, id) < (SELECT created_at, id FROM audit_log WHERE id = %s)
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

#: The first page of the Flagged filter (Story 3.7, FR-22): the newest
#: `PAGE_SIZE` entries whose `action` is one of `FLAGGED_AUDIT_ACTIONS`.
#:
#: **`_SELECT_LATEST_ENTRIES`'s own text, plus one `AND`.** Never a
#: dynamically assembled `WHERE` — the two flag actions are the only variable
#: part, and they travel as a parameterized array (`= ANY(%s)`), never
#: interpolated. Same column list, same `ORDER BY created_at DESC, id DESC`,
#: same keyset shape: the Flagged filter is a predicate on top of the
#: unfiltered read, not a second read with its own paging rules.
#:
#: `audit_log_flagged_idx` (`20260923T1010_add_audit_log_flagged_index.up.sql`)
#: is this statement's own partial index over exactly this ordering and
#: exactly this predicate.
_SELECT_LATEST_FLAGGED_ENTRIES = """
SELECT id, created_at, action, actor_user_id, actor_email,
       target_user_id, target_email, source_ip, details
FROM audit_log
WHERE action = ANY(%s)
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

#: The next page of the Flagged filter — `_SELECT_ENTRIES_BEFORE`'s own text,
#: the same `AND action = ANY(%s)` added.
_SELECT_FLAGGED_ENTRIES_BEFORE = """
SELECT id, created_at, action, actor_user_id, actor_email,
       target_user_id, target_email, source_ip, details
FROM audit_log
WHERE (created_at, id) < (SELECT created_at, id FROM audit_log WHERE id = %s)
  AND action = ANY(%s)
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

#: Whether a cursor names a row at all.
#:
#: Run only when the page above came back empty, which is the one case where
#: "no rows" is ambiguous — the oldest entry and an invented id produce the
#: same result set, and they are a `200 []` and a `404` respectively. On every
#: other page this statement is never executed, so distinguishing the two
#: costs nothing on the path that is taken almost every time.
#:
#: `SELECT 1`: the question is existence, and selecting columns nobody reads
#: would be a second column list to keep in step with the contract.
_SELECT_ENTRY_EXISTS = """
SELECT 1
FROM audit_log
WHERE id = %s
"""

#: Tagged rather than prefixed. `/admin/` is an authorization boundary that
#: `tests/test_admin_authorization.py` reads off the *path*, so the path is
#: written out at the route rather than assembled from a router prefix a reader
#: has to go and find — `api.users` does the same.
router = APIRouter(tags=["audit"])


def _audit_entry_not_found() -> ApiError:
    """The `404` for a cursor that names no entry. See `AUDIT_ENTRY_NOT_FOUND`."""
    return ApiError(
        AUDIT_ENTRY_NOT_FOUND,
        NO_SUCH_ENTRY,
        status_code=status.HTTP_404_NOT_FOUND,
        headers=NO_STORE,
    )


@router.get("/admin/audit", response_model=list[AuditLogEntry])
def read_audit_log(
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
    before: UUID | None = None,
    flagged: bool = False,
) -> list[AuditLogEntry]:
    """FR-21 — the log, newest first, one page at a time.

    **The `administrator` parameter is the authorization, not a value.** It is
    the caller, resolved from the session cookie and re-read from Postgres on
    this request (AD-3), and declaring the dependency is the whole of its job.
    A Staff caller is refused before this function is entered, and an
    Administrator still holding a temporary credential is refused before that
    by `require_claimed_user`, which `require_administrator` chains on. What
    `apps/web` renders is a convenience and never the control — a demotion
    between two requests closes this surface on the very next one.

    Sync, not `async def`: psycopg is a synchronous driver (AD-3,
    `tests/test_source_guards.py`), and FastAPI runs a sync endpoint in its
    threadpool.

    **A bare JSON array, not an envelope**, exactly as `GET /admin/users` is.
    The envelope everywhere else in this product is the *error* envelope; every
    success body is the thing itself. A `{entries, has_more}` wrapper for one
    boolean would make this the only shaped success body in the API, and the
    client can already tell: a page shorter than `PAGE_SIZE` is the last one.
    The cost is one wasted request when the log's length is an exact multiple
    of the page size — the client asks, gets `[]`, and stops. That is a press,
    not a defect, and it is cheaper than a second body shape.

    **`before` is the oldest row already rendered, never a position.** See
    `_SELECT_ENTRIES_BEFORE` for why a keyset beats an `OFFSET` on a table that
    grows from the top, and why the cursor is one id rather than a pair. A
    well-formed id naming no row is a `404`; a malformed one never reaches this
    function at all, because FastAPI validates `UUID` and `api.main`'s handler
    answers the shared `422` envelope.

    **`flagged` (Story 3.7, FR-22) selects a second, otherwise-identical pair
    of statements** — `_SELECT_LATEST_FLAGGED_ENTRIES` /
    `_SELECT_FLAGGED_ENTRIES_BEFORE` — scoped to `FLAGGED_AUDIT_ACTIONS`, never
    a `WHERE` assembled at request time. Same order, same page size, same
    keyset cursor shape as the unfiltered read: the filter changes which rows
    qualify, never how the page is built. Defaults to `False` so every
    existing caller — and every unfiltered test — is unaffected.

    **This surface is read-only and has no counterpart.** There is no route
    that edits or removes an entry, here or anywhere, and there cannot be one:
    `rocell_app` holds `SELECT, INSERT` on this table and nothing else, so an
    `UPDATE` added later fails at runtime with `InsufficientPrivilege` rather
    than quietly working (AD-4, AGENTS.md Policy).

    `NO_STORE` for the reason every other authenticated response carries it —
    and more so here, because this body is the record of who did what, read on
    a shared desk. Nothing secret is in it: `AuditLogEntry` has no field a
    digest or a token could occupy, and `record`'s own rule keeps them out of
    `details`.
    """
    response.headers.update(NO_STORE)

    flag_actions = list(FLAGGED_AUDIT_ACTIONS)

    if before is None:
        # `model_validate` per row rather than a bulk construction: it is the
        # same gate the write goes through, so a column that stopped matching
        # the contract fails loudly here instead of reaching the wire.
        statement, params = (
            (_SELECT_LATEST_FLAGGED_ENTRIES, (flag_actions, PAGE_SIZE))
            if flagged
            else (_SELECT_LATEST_ENTRIES, (PAGE_SIZE,))
        )
        return [AuditLogEntry.model_validate(row) for row in conn.execute(statement, params)]

    statement, params = (
        (_SELECT_FLAGGED_ENTRIES_BEFORE, (before, flag_actions, PAGE_SIZE))
        if flagged
        else (_SELECT_ENTRIES_BEFORE, (before, PAGE_SIZE))
    )
    entries = [AuditLogEntry.model_validate(row) for row in conn.execute(statement, params)]
    # Only when the page is empty. A cursor that resolves and a cursor that
    # does not produce the same empty result — `(created_at, id) < NULL` is
    # NULL for every row — and the two are a `200 []` and a `404`. Existence is
    # checked against the whole table regardless of `flagged`: a cursor is
    # "invented" or not independent of which rows the current page filters to.
    if not entries and conn.execute(_SELECT_ENTRY_EXISTS, (before,)).fetchone() is None:
        raise _audit_entry_not_found()
    return entries
