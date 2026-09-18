"""The `User` contract, shared by `apps/web` and `apps/api`.

The field set is the architecture spine's ERD `USER` block plus the two the PRD
needs on the admin screens: `name` and `email` (FR-11) and `last_login_at`
(FR-10). The glossary names are used verbatim — the entity is a `User` and its
roles are `Staff` and `Administrator`, stored as the lowercase values `staff`
and `admin`.

**`password_hash` is deliberately absent.** It is not excluded by a serializer
that a later change could forget; the field does not exist on this model, so
there is no code path that can put a digest on the wire. `infra`'s seed and
`apps/api`'s login verifier read that column directly and never through here.

`shared_schema/ts/user.ts` is the TypeScript twin. The two files are one
contract in two languages and change together or not at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_serializer

#: AGENTS.md Policy: an admin-issued temporary credential expires after 72
#: hours, without exception.
#:
#: It lives here, in the contract both writers already depend on, because there
#: are now two of them: `infra`'s migration-time seeder writes the first
#: Administrator's credential and `apps/api`'s admin surface writes every one
#: after it. `shared/*` is the only direction both may point — `apps/api`
#: depends on `shared-schema` and may not depend on `infra` — so a second copy
#: of the number would be the only alternative, and a deadline that is 72 hours
#: in one writer and something else in the other is AGENTS.md's rule holding for
#: some accounts and not others, with nothing raising.
#:
#: The deadline itself is always computed by Postgres (`now() + make_interval`),
#: never against a writing host's clock; this is only how many hours to add.
TEMP_CREDENTIAL_LIFETIME_HOURS = 72


class Role(StrEnum):
    """The complete set of roles. AGENTS.md Policy: never a third one."""

    STAFF = "staff"
    ADMIN = "admin"


class User(BaseModel):
    """A `Staff` or `Administrator` account, as the API renders it.

    Closed shape, for the same reason `ErrorEnvelope` is closed: the TypeScript
    twin's `isUser` rejects a body carrying any key beyond the contract, and
    pydantic's default is to accept and silently discard. `password_hash`
    arriving from anywhere must be a loud failure, not a quiet drop.

    Nullable fields are required-but-nullable rather than optional, so the JSON
    the API emits always carries all eleven keys and the twin can check for
    them.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    email: str
    role: Role
    active: bool
    must_change_password: bool
    # Set when an Administrator issues a temporary credential; AGENTS.md Policy
    # gives it 72 hours. Read and compared as UTC (the column is `timestamptz`).
    #
    # `AwareDatetime`, not `datetime`: a naive value carries no instant at all,
    # and the twin's `isUtcTimestamp` rejects one. Accepting it here would make
    # the two halves disagree about a body pydantic had already validated.
    temp_credential_expires_at: AwareDatetime | None
    last_login_at: AwareDatetime | None
    # FR-4's lockout, as an Administrator sees it on the account's status.
    #
    # **Status, never enforcement.** "Locked now" is `locked_until > now()`;
    # a value in the past means the account was locked recently and is not
    # locked any more, and the column is never cleared, so it is history as
    # much as state. Nothing decides anything from it — `apps/api`'s login
    # throttle reads its own `login_attempts` row and only mirrors its decision
    # here. A client that treats a past value as "locked" is reading it wrong;
    # one that treats it as authoritative is reading a copy.
    locked_until: AwareDatetime | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_serializer(
        "temp_credential_expires_at",
        "last_login_at",
        "locked_until",
        "created_at",
        "updated_at",
        when_used="json",
    )
    def _in_utc(self, value: datetime | None) -> str | None:
        """Emit every timestamp in UTC, whatever offset it arrived with.

        `timestamptz` comes back from the driver in the *session's* time zone,
        so an API process whose session is not UTC would put `+05:30` on the
        wire. The spine's Consistency Conventions fix timestamps as ISO 8601
        UTC, and the twin's `isUtcTimestamp` accepts only a UTC designator — so
        without this, a body this model validated and serialized could be
        rejected by `isUser`, and "one contract in two languages" would be true
        of the key set and false of the values.
        """
        return None if value is None else value.astimezone(UTC).isoformat()
