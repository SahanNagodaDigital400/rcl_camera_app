"""The `AuditLogEntry` contract, shared by `apps/web` and `apps/api`.

The field set is the nine columns the append-only log actually holds — the
architecture spine's ERD block names four of them (`id`, `action`, `source_ip`,
`created_at`) and calls that a floor rather than a ceiling, and the shipped
table adds the actor and target snapshot pair AD-10 requires.

`AuditAction` lives here rather than in `apps/api` because it is no longer only
a writer's vocabulary: the read surface labels an entry from it, and
`apps/web`'s twin has to hold the same thirteen values. `api.audit` re-imports
it, so every existing call site is unchanged. `PAGE_SIZE` is here for the same
reason — see its own comment below.

**Nothing secret is representable.** There is no password field, no digest and
no session token — not as a column and not inside `details`, whose contents are
the writer's responsibility (`api.audit.record` states that rule at its own call
sites). A serializer cannot leak what the model cannot hold.

`shared_schema/ts/audit.ts` is the TypeScript twin. The two files are one
contract in two languages and change together or not at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_serializer

#: How many entries one page of the audit log carries.
#:
#: **The client is told this number; it never chooses it.** Those are different
#: things, and only the second is a hazard. `GET /admin/audit` declares no
#: `limit` parameter and never will: this is the one table in the product that
#: only grows and that no principal may prune (AD-4 grants no `DELETE`), so a
#: caller-supplied page size is a denial-of-service knob on exactly the surface
#: that cannot be trimmed — one request asking for every row is years of
#: history serialised into one response. That argument is untouched by
#: publishing the value.
#:
#: **Publishing it is what lets the screen tell a last page from a full one.**
#: The response is a bare array (`api.audit.read_audit_log` argues why), so
#: nothing on the wire says whether more entries exist — the client works it
#: out from the length of the page it just received, and it can only do that
#: against a number it knows. The alternative it replaces was inferring the
#: size from the length of the *first* page, which reads a log of five entries
#: as a full page of five: every short log — which is every log early in this
#: product's life — would then offer a Load more that fetches nothing. What
#: remains is the log whose length is an exact multiple of this number, where
#: the last press answers `[]`.
#:
#: It lives in `shared/*` because that is the only direction both halves may
#: point, exactly as `user.TEMP_CREDENTIAL_LIFETIME_HOURS` does: `apps/api`
#: reads it to build the statement's `LIMIT`, `apps/web` reads its twin
#: (`AUDIT_PAGE_SIZE` in `ts/audit.ts`) to decide whether to offer another
#: page, and `tests/test_audit.py` pins the two spellings to one value. Two
#: copies that disagree would be a screen that stops one page early or offers
#: one page too many, with nothing raising.
#:
#: Fifty is enough that an Administrator answering "who signed in on Tuesday"
#: usually finds the answer on the first page, and small enough that the body
#: stays a page rather than a download.
PAGE_SIZE = 50

#: The name of the query parameter carrying the keyset cursor —
#: `GET /admin/audit?before=<id of the oldest row already rendered>`.
#:
#: Here for the same reason `PAGE_SIZE` is, and it is the first query parameter
#: in this product, so it is the first time the two halves have had to agree on
#: more than a path. The server's spelling is the name of `read_audit_log`'s
#: parameter, which FastAPI reads the query string with; the client's spelling
#: is `AUDIT_CURSOR_PARAM` in `ts/audit.ts`, which it builds the request path
#: from. Nothing at build time crosses between them, so without a pin the two
#: are two string literals in two languages that nothing holds together:
#: renaming one leaves every test in both suites green while the server
#: silently ignores an unknown parameter and answers the *first* page to every
#: Load more — a log that repeats its newest fifty rows forever, which is the
#: one failure mode a record may not have.
#:
#: `tests/test_audit.py` pins the twin's spelling to this value, and
#: `apps/api/tests/test_audit_read.py` pins the route's parameter name to it.
CURSOR_PARAM = "before"


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

    It is also what the read surface labels an entry with. The screen maps each
    member to a human phrase and falls back to the stored string for anything
    it does not know — see `action` on the model below for why that fallback is
    the point rather than a lenience.
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
    # Epic 2's first entry, and the first that names something other than
    # an account. `details` carries the Code — the Tile's identity (AD-18)
    # — as a snapshot, never a foreign key: removal (Story 2.3) is a hard
    # delete and the log may neither block it nor be cascaded into (AD-10).
    CATALOGUE_TILE_ADDED = "catalogue_tile_added"
    # Story 2.2's correction. A separate member rather than a second
    # `catalogue_tile_added` with a flag in `details`: the log has to name what
    # happened, and an edit is not an add — it can rename the Code the earlier
    # entry recorded, and a reader following a Tile through the log needs the
    # two to be distinguishable without parsing `details`.
    CATALOGUE_TILE_EDITED = "catalogue_tile_edited"
    # Story 2.3's withdrawal. A member of its own rather than a
    # `catalogue_tile_edited` carrying a flag, for a reason the edit's argument
    # only half covers: a removal is the one catalogue event whose subject no
    # longer exists once it has been written. Nothing can be fetched to explain
    # the entry afterwards, so the entry has to say what happened by itself —
    # and a reader following a Tile through the log needs the last thing that
    # happened to it to be readable as the end of the trail.
    CATALOGUE_TILE_REMOVED = "catalogue_tile_removed"


class AuditLogEntry(BaseModel):
    """One entry, as the API renders it (FR-20, FR-21).

    Closed shape, for the same reason `User` is closed: the TypeScript twin's
    `isAuditLogEntry` rejects a body carrying any key beyond the contract, and
    pydantic's default is to accept and silently discard. A column added to the
    table and forgotten here must be a loud failure, not a quiet drop.

    Nullable fields are required-but-nullable rather than optional, so the JSON
    the API emits always carries all nine keys and the twin can check for them.
    A missing `actor_user_id` and an explicit `null` mean different things to a
    reader — "not recorded" against "there was no actor" — and only the second
    is ever true of this table.

    **`action` is `str`, not `AuditAction`, and that is the deliberate
    asymmetry of this contract.** Writes are constrained — `api.audit.record`
    takes the enum and is the only writer the application has — while reads are
    not:

    * the column has no CHECK by design, so the database has never promised
      that every stored value is a member;
    * the vocabulary grows with Epics 2 and 3, so an API serving entries
      written by a newer process is an ordinary deployment state rather than a
      fault; and
    * a corrective entry is inserted by hand as the table owner (AD-4's
      correction mechanism), which is precisely the case a closed enum refuses.

    A viewer that will not render an entry it does not recognise is the one
    failure an append-only log may not have: the row exists, it cannot be
    edited, and hiding it makes the surface a less faithful record than the
    table behind it. The screen falls back to the stored value, which is
    readable even when it is not recognised.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    # The database clock, never a writing host's. Written once and never moved:
    # there is no `updated_at` here because there is no update (AD-4).
    #
    # `AwareDatetime`, like every timestamp in this package: a naive value
    # carries no instant at all, and the twin's `isUtcTimestamp` rejects one.
    created_at: AwareDatetime
    # See the class docstring. `str` on the wire; `AuditAction` on every write.
    action: str
    # Who acted. Both `None` where nobody is known — a refused sign-in against
    # an address that is not an account. A reader must render that as *no
    # actor*, never as the target and never as an invented principal: the
    # entry does not know who tried, and saying otherwise would be the log
    # asserting something it was never told.
    actor_user_id: UUID | None
    actor_email: str | None
    # Who it was done to. Equal to the actor for a self-directed action (a
    # sign-in, a password change); different for every admin write. The id and
    # the address are a snapshot pair, not a foreign key (AD-10): the id joins
    # while the row lives, the address is what the entry still means after it
    # does not.
    target_user_id: UUID | None
    target_email: str | None
    # The source address as `api.audit.source_ip` resolved it, canonicalised
    # and validated before storage. `None` where it did not parse or no trusted
    # header was set — honest rather than plausible.
    source_ip: str | None
    # Everything the action needs that is not a column: a refusal's reason, a
    # revocation's count, an edit's before/after. Not nullable — the column
    # defaults to `{}` — so a reader never has to tell "no detail" from "not
    # recorded".
    #
    # `dict[str, Any]` rather than a per-action model: the payload's shape
    # differs by action and grows with every epic, and a closed union here
    # would refuse to serve an entry for the same reason a closed `action`
    # would. The twin types it `Record<string, unknown>` to match.
    details: dict[str, Any]

    @field_serializer("created_at", when_used="json")
    def _in_utc(self, value: datetime) -> str:
        """Emit the timestamp in UTC, whatever offset it arrived with.

        `timestamptz` comes back from the driver in the *session's* time zone,
        so an API process whose session is not UTC would put `+05:30` on the
        wire. The spine's Consistency Conventions fix timestamps as ISO 8601
        UTC, and the twin's `isUtcTimestamp` accepts only a UTC designator — so
        without this, a body this model validated and serialized could be
        rejected by `isAuditLogEntry`, and "one contract in two languages"
        would be true of the key set and false of the values.
        """
        return value.astimezone(UTC).isoformat()
