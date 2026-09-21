"""`/admin/users` — the collection an Administrator writes to, reads back and edits.

Six routes over four paths. `POST /admin/users` provisions somebody else's
login (FR-11), `GET /admin/users` lists every account with its status and last
sign-in (FR-10), `PATCH /admin/users/{user_id}` changes a name, an address or a
role on one of them (FR-12), and Story 1.11 adds the three verbs that take
access away or give it back (FR-13): `POST /admin/users/{user_id}/deactivate`,
`POST /admin/users/{user_id}/activate` and `DELETE /admin/users/{user_id}` —
the first routes in the product that are not about the caller's own identity.
Four things about the write are load-bearing:

**It is the only writer of a `User` row inside the running product.** The one
account before it — the seeded Administrator — is written by the migration
runner, outside the application entirely (`infra/rocell_infra/seed.py`). Every
row after it comes through here, which is what removes the wait FR-11 exists to
remove: granting a member of staff access no longer needs a developer holding
`DATABASE_URL`.

**Its authorization is a dependency, never a line in the handler.**
`api.dependencies.require_administrator` is declared in the signature below and
is what refuses a Staff caller — before the handler runs, before an address is
normalized, and before a single Argon2id hash is spent. It chains on
`require_claimed_user`, so an Administrator still holding a temporary credential
of their own is refused by Story 1.4's gate first and cannot use a note-borne
credential to provision a second one. `tests/test_admin_authorization.py` reads
the requirement off the path: every route under `/admin/` declares it, and every
route declaring it is under `/admin/`.

**The row it writes is the row `infra`'s seeder writes.** Claimed later:
`must_change_password = true` with a 72-hour deadline
(`shared_schema.user.TEMP_CREDENTIAL_LIFETIME_HOURS`, the one statement of it),
computed by Postgres rather than against this host's clock. So the very first
thing the new user meets is Story 1.4's forced change: the credential reaches
the password-change screen and nothing else, and it stops working when the
account is claimed or when the 72 hours run out, whichever comes first. It is
**not** single-use — it signs in as many times as it is tried inside that
window, which is what makes the 72 hours the bound that matters.

**Uniqueness is the database's decision.** A `SELECT` before the `INSERT` would
be a race that hands two people the same login; the unique index over
`lower(email)` is what actually decides, and its `UniqueViolation` is the 409.

**The read is the same collection, under the same guard.** `GET /admin/users`
declares `require_administrator` exactly as the write does, so the authorization
is still read off the path in both directions, and it returns every row the
`users` table holds — the caller's own, deactivated ones, locked ones — as the
same eleven-key `User` the write returns. One `SELECT`, no `WHERE`, no `LIMIT`,
no parameter at all: FR-10 is *every* account.

**The edit is three columns and no more.** `PATCH` writes `name`, `email` and
`role`, in one guarded `UPDATE`, and returns the same eleven-key `User` the
other two routes return. The other eight columns are not things a caller may
supply: `password_hash` is never touched by anything but `api.auth`,
`must_change_password` without a `temp_credential_expires_at` is a bricked
account (DW-44), `id` is the identity being edited, and `last_login_at`,
`locked_until`, `created_at` and `updated_at` are the product's own record of
what happened rather than fields. The body is closed (`extra="forbid"`) and
names the three. **Nothing here touches a session**: AD-3 has `lookup_session`
re-read `role` and `active` from Postgres on every request, so a role change
lands on the target's very next request by itself — FR-12's "live session" half
is proved by `tests/test_edit_user.py` rather than built here, and this handler
must never start managing sessions.

**The three verbs are routes of their own, never a widening of `PATCH`.** The
obvious alternative — `active` on `EditUserRequest` — is refused for three
reasons. `PATCH`'s body is closed and its refusal of `{"active": false}` is
pinned by a shipped test whose comment explains that the route does not
deactivate accounts. The Administrator floor would then have to be evaluated
against both `COALESCE(role)` and `COALESCE(active)` in one statement, which is
a harder rule to read and an easier one to get wrong. And deactivation has a
side effect an edit does not — revoking sessions — which would put a
destructive write inside the route the UI reaches on every name correction.
Three verbs carrying **no request body at all** also means no new request
model, no new `extra="forbid"` surface, and no new code for `apps/web` to
learn. Reactivation is the inverse the other two need: a deactivate with no way
back is a one-way door recoverable only by a developer holding `DATABASE_URL`,
which is the dependency Epic 1 exists to remove, and EXPERIENCE.md:148 already
tells the Administrator facing the floor refusal to "activate or create a
second Administrator first".

**Not here.** No `active` toggle on the edit body, no admin-set password, no
credential reissue, no soft-delete marker column, no session-listing or
per-session-revocation surface — and **no unlock**. Neither destructive verb
touches `login_attempts`: the counter is keyed on the submitted address and is
deliberately not a foreign key to `users`, so a delete leaves it behind, and
clearing it would make "delete the account and recreate it" an unlock — the
same lock-evasion path Story 1.10 refused to open when it carried a rename's
run instead of clearing it (DW-59/DW-91).

The unlock is the one that changed: `throttle.py`, `auth.py` and `README.md`
all used to predict it "in Story 1.10", and epics.md 1.10 scopes that story to
name, email and role, so it was not built and **no story in Epic 1 now owns
it** (DW-64, still open, now with no predicted owner). What the edit does owe
the lockout is `throttle.carry_failures`: a rename moves the account's run of
failures to the new address rather than stranding it on the old string, so that
editing an address is not the unlock this product has decided not to have
(DW-59).

**No mail of any kind**, not a dependency, not a stub, not a "send the
credential" control on the screen: AGENTS.md Policy and FR-11 both put
distribution in the Administrator's hands, and
`tests/test_no_password_reset.py` asserts the absence over the source tree and
the dependency manifests.

**No audit entry** — Story 1.12 owns the append-only log and owes every route
in this module one, and no private log path is built in the meantime, so until
then the only trace of a provisioning is the row's own `created_at`, and of an
edit, a deactivation or a reactivation, its own `updated_at`, which does not
say by whom or what changed. A **delete** leaves no trace at all, which makes
1.12's problem the harder one it now inherits: AD-4 denies the application role
`DELETE` on the audit table and the spine draws `USER ||--o{ AUDIT_LOG_ENTRY`,
so a hard user delete means the actor reference has to be AD-10's denormalised
snapshot rather than a foreign key. That is 1.12's decision to make.

**And no throttle on the one route that spends a hash.** `POST /admin/users` is
the fourth Argon2id-backed endpoint in the product and a direct extension of
DW-40/DW-69, which are open and are decisions about what a counter would be
keyed on — it is also Administrator-only, so the caller is already
authenticated and already named. The five routes beside it hash nothing at all.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a handler's
# annotations at runtime to build its dependency graph, so a name that exists
# only for the type checker fails at import with a bare NameError.
import psycopg
from fastapi import APIRouter, Depends, Response, status
from psycopg import errors as pg_errors
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shared_schema.errors import ApiError
from shared_schema.passwords import hash_password, password_rule_violation
from shared_schema.user import TEMP_CREDENTIAL_LIFETIME_HOURS, Role, User

# `api.auth` owns the two bounds and the rule-naming 422, and this module reads
# them rather than restating them: a second `MAX_EMAIL_LENGTH` is a second
# opinion about what an address is, and a second `422 weak_password` constructor
# is a second opinion about what a refused password looks like. `_weak_password`
# is private to that module in the sense that nothing outside `apps/api` may
# have it — importing it here is what keeps the two refusals one refusal.
#
# `api.sessions` is imported for the same reason and read the same way: Story
# 1.11's deactivation revokes the target's sessions through
# `sessions.delete_sessions_for_user`, which already exists, rather than through
# a second delete statement against that table written here.
# `tests/test_source_guards.py` forbids the second copy outright (AD-3: one
# module owns that table), and the rule is right — a revocation written twice
# is a revocation that drifts.
from api import sessions, throttle
from api.auth import MAX_EMAIL_LENGTH, MAX_PASSWORD_FIELD_LENGTH, _weak_password
from api.db import get_connection
from api.dependencies import NO_STORE, require_administrator

router = APIRouter(tags=["users"])

#: The envelope code for an address this endpoint will not store.
#:
#: A code of its own rather than the generic `validation_error` the request
#: model would produce, because `api.main.validation_error_handler` renders one
#: sentence for every 422 it makes — "the request was not in the expected shape"
#: — and an Administrator who has just mistyped an address needs to be told
#: *which* field and *which* rule (EXPERIENCE.md:87). The rule therefore lives
#: in the handler, where it can carry an answerable code.
INVALID_EMAIL = "invalid_email"

#: The sentence, naming the rule that failed rather than describing the value.
NOT_AN_ADDRESS = "An email address must have exactly one @ sign, with text on each side."

#: The envelope code for an address that is already somebody's login.
#:
#: Distinct from `invalid_email` because the Administrator's answer is
#: different: nothing is wrong with what they typed, the person may simply
#: already have access.
EMAIL_ALREADY_EXISTS = "email_already_exists"

#: What a duplicate is told. It reveals nothing a caller who submitted the
#: address does not already know — and this route is Administrator-only, so the
#: caller is somebody the product already trusts with the whole user list
#: (Story 1.9). It is deliberately not worded as a fact about a *person*: the
#: match is on the address, whoever holds it.
ADDRESS_ALREADY_IN_USE = "A user with that email address already exists."

#: The unique index the `409` is built from, by name.
#:
#: Postgres reports it as `constraint_name` on the `UniqueViolation` it raises,
#: and the handler below answers `email_already_exists` for that name and for no
#: other. The table's other unique constraint is its primary key, whose values
#: come from `gen_random_uuid()` — a clash there is not a duplicate address and
#: must not be described to the Administrator as one. The same is true of any
#: index a later migration adds (Stories 1.9-1.11 all touch this table): an
#: unrecognised clash propagates and is answered as a `500`, which is honest,
#: rather than pointing the Administrator at an email field that is fine.
EMAIL_UNIQUE_INDEX = "users_email_lower_key"

#: The longest name the endpoint will store. Generous for a person's name in any
#: script, and short enough that the column is never handed a payload. `users.name`
#: is `text` with no length of its own, so this is the only bound there is.
MAX_NAME_LENGTH = 200

#: What a blank name is told. Raised from the validator below, so it renders as
#: `api.main`'s generic 422 sentence rather than this one — it is here for the
#: reader and for a `ValidationError` inspected in a test, not for the wire.
BLANK_NAME = "A name must not be blank."

#: And what a name carrying a control character is told, for the same audience.
CONTROL_IN_NAME = "A name must not contain control characters."

#: The envelope code for an id that names no row. Story 1.10's edit.
#:
#: **A `404` rather than a silent no-op**, and the difference is the
#: Administrator's. They are acting on a list they fetched a moment ago, and the
#: row may have been deleted from another tab or another device in between
#: (Story 1.11 adds the verb that does it). A `200` carrying nothing, or a `200`
#: carrying the body they sent, tells them the change landed on an account that
#: no longer exists — and the surface they would go back to check is the same
#: stale list. The refusal is the only thing that sends them to refetch it.
#:
#: Distinguished from the floor refusal below by the locking read, never by
#: guesswork over a zero-row `UPDATE`: two different states must not share one
#: answer just because one statement cannot tell them apart.
USER_NOT_FOUND = "user_not_found"

#: What that is told. It names the row rather than the person: the caller holds
#: an id, and this endpoint has just failed to find anybody behind it.
NO_SUCH_USER = "That user no longer exists. Reload the list."

#: The envelope code for a demotion that would leave nobody in charge.
#:
#: **A `409`, never a `403`.** Nothing is wrong with the caller's authority —
#: they are an Administrator, acting on a route that is theirs, and a `403` would
#: describe their *role* as the problem while their session went on working
#: everywhere else (`api.dependencies.ADMINISTRATOR_REQUIRED` says the same thing
#: from the other side). What refuses them is the product's own state: there is
#: exactly one active Administrator and this would be zero. A conflict is what
#: that is, and it is answerable — promote somebody, then try again.
#:
#: epics.md gives this refusal to Story 1.11 and words it for deactivate and
#: delete. Demoting the last active Administrator reaches the same state by a
#: different verb, from *this* story's route, and the epic states the constraint
#: as a standing property of the product rather than of one handler. 1.11 should
#: reuse `_LOCK_ACTIVE_ADMINISTRATORS` and `_UPDATE_USER`'s predicate rather than
#: writing a second copy of the rule.
LAST_ADMINISTRATOR = "last_administrator"

#: What it says: the rule that failed and the ways out of it, in one sentence
#: (EXPERIENCE.md:87). It names no person — the refusal is about how many active
#: Administrators the product has, not about who the target is.
#:
#: **Both** ways out, since Story 1.11: EXPERIENCE.md:148 tells the Administrator
#: facing this refusal that they "must activate or create a second Administrator
#: first", and `POST /admin/users/{user_id}/activate` is what makes the first
#: half reachable. A refusal that names only the harder remedy is a refusal that
#: hides the easy one.
LAST_ACTIVE_ADMINISTRATOR = (
    "There must always be at least one active Administrator. "
    "Make somebody else an Administrator, or activate one, first."
)


def _has_control_character(value: str) -> bool:
    """Whether `value` holds a character Postgres text cannot carry or display.

    The reason `auth._is_addressable` gives, and it applies to every `text`
    column this module writes rather than only to the address: a C string has no
    way to carry a NUL byte, so Postgres text cannot hold one and psycopg raises
    rather than sending it. That raise would escape as a `500` — after a full
    Argon2id hash had already been paid for — where every other refused body
    gets a `422`. The rest of the control range goes with it: none of it belongs
    in a person's name or an address, and it renders as nothing at all on Story
    1.9's list, which is a user nobody can identify created by a form that
    reported success.

    One function rather than two checks, so `name` and `email` cannot drift
    apart about what a storable string is.
    """
    return any(character < " " or character == "\x7f" for character in value)


def _clean_name(value: str) -> str:
    """The name as it will be stored, or a `ValueError` naming the rule it broke.

    One opinion about what a storable name is, called by both request models in
    this module, because `POST` and `PATCH` writing the same column to two
    different standards is how a name that could not be created becomes a name
    that can be edited into place.

    `min_length=1` alone admits `"   "`, which stores a row whose name renders as
    nothing at all on Story 1.9's list — a user nobody can identify, created by a
    form that reported success. Stripping here rather than in a handler means the
    stored value and the validated value are the same string.

    The control-character screen is `_normalize_email`'s, applied to the sibling
    `text` column for the reason `_has_control_character` gives: a NUL cannot
    survive a Postgres text parameter, and without this check it reaches
    `conn.execute` — after the Argon2id hash has been paid, on the write — and
    answers `500` where every other refused body answers `422`.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError(BLANK_NAME)
    if _has_control_character(stripped):
        raise ValueError(CONTROL_IN_NAME)
    return stripped


class CreateUserRequest(BaseModel):
    """The provisioning body: a name, an address, a role, and a temporary password.

    `extra="forbid"`, like every other body in `apps/api`: a field this endpoint
    does not read is a caller with a different idea of the contract, and
    silently discarding it is how an `active` or a `must_change_password` gets
    sent for a year before anyone notices the row does not honour it. Both of
    those are product rules stated by `_INSERT_USER` and are deliberately not
    things a body can supply.

    `role` is the shared `Role` enum, so `"owner"` is refused by pydantic before
    the handler runs — AGENTS.md Policy's "never a third role" enforced by the
    type rather than by a check somebody has to remember to write. The database's
    own `CHECK (role IN ('staff', 'admin'))` is the second, independent copy.

    **The name's rule lives here and the email's does not**, and that asymmetry
    is deliberate. A name has no rule beyond "present, and bounded" — there is
    nothing for a rejection to name that the field label does not already say —
    so the generic `422 validation_error` is an honest answer for it. An address
    does have a rule, and an Administrator who mistyped one has to be told which
    field and which rule (EXPERIENCE.md:87), which needs a code of its own; only
    the handler can raise one.

    `temporary_password` carries **no minimum** for the same reason
    `PasswordChangeRequest` does not: validation would answer the generic 422,
    and a short temporary password has to come back as `weak_password` with
    `password_rule_violation`'s sentence. `MAX_PASSWORD_FIELD_LENGTH` is not a
    password rule; it is the point past which a body stops being a password at
    all, and nothing past it reaches `hash_password`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)
    role: Role
    temporary_password: str = Field(max_length=MAX_PASSWORD_FIELD_LENGTH)

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        """Strip the name, and refuse a blank one or one carrying a control character.

        The rule itself is `_clean_name`, shared with `EditUserRequest` since
        Story 1.10 rather than restated here: `POST` and `PATCH` write the same
        column, and two opinions about what a storable name is means a name that
        could not be created can still be edited into place.
        """
        return _clean_name(value)


def _normalize_email(email: str) -> str | None:
    """The address as it will be stored, or `None` if it is not one.

    Lowercased and stripped because `users` carries `CHECK (email =
    lower(email))` and its only unique index is `ON (lower(email))`: an address
    stored in the case somebody happened to type would oblige every lookup in
    the product to remember `lower(email) = lower(...)`, and nothing would catch
    the first one that forgot. Doing it here also makes the 409 below reachable
    for two submissions differing only in case or surrounding space, which is
    the realistic duplicate.

    Control characters are refused first, for the reason `_has_control_character`
    gives, and **interior whitespace with them**. The ends are stripped, so what
    is left is a space somebody typed inside the address — among the commonest
    real typos there is, reachable by a stray keystroke or by a copy-paste that
    picked up a line wrap, and never part of an address anyone can sign in with.
    Refusing it here is the difference between an Administrator reading "that is
    not an address" and a colleague who cannot sign in for a reason nobody can
    see on a user list.

    The rest of the shape check is **deliberately the weakest one that catches a
    real typo**: exactly one `@`, with something on each side. Anything stricter
    starts refusing addresses that work — an internal host with no dot in it, a
    local part with a plus or an apostrophe in it, a non-ASCII domain — and the
    cost of that is an Administrator who cannot provision a colleague at all.
    The authoritative test of an address is whether its owner can sign in with
    it, which happens minutes later and needs no help from a regular expression.
    """
    address = email.strip().lower()

    if _has_control_character(address) or any(character.isspace() for character in address):
        return None

    local, separator, domain = address.partition("@")
    if not separator or not local or not domain or "@" in domain:
        return None

    return address


#: The provisioning write, in one statement.
#:
#: `true, true` — `active` and `must_change_password` — are FR-11 and FR-2
#: stated at the one place that writes the row, not left to the column defaults.
#: A default is a schema fact a later migration may change; this is a product
#: rule, and a rule read out of a schema is a rule nobody is holding.
#:
#: **The address is folded by Postgres, not by Python.** `users` carries
#: `CHECK (email = lower(email))`, and `str.lower()` and Postgres's `lower()` are
#: not guaranteed to agree on non-ASCII input — `İ` is the standard example, and
#: which of them moves depends on the server's collation. Where they disagree the
#: row this statement writes fails its own CHECK, and a `CheckViolation` nothing
#: catches is an unexplained `500` in front of an Administrator who typed a
#: perfectly ordinary address. Writing `lower(%s)` makes the constraint
#: unfailable: the value stored is by construction the value the constraint
#: compares against.
#:
#: `_normalize_email` still lowercases in Python, and that is not the same job:
#: it is what makes the shape check case-insensitive and what makes the 409
#: reachable for two submissions differing only in case, because the unique index
#: is `ON (lower(email))` and the *index* has to see the clash. The Python fold is
#: for this module's own decisions; this one is for the column.
#:
#: The deadline is Postgres's own clock (`now() + make_interval(hours => %s)`),
#: never this host's — the same idiom `infra`'s seeder uses, and the reason the
#: hours are a parameter rather than an interval literal. `must_change_password`
#: is never set without it: a flagged row with a NULL expiry is permanently
#: unusable by design (DW-44, and `auth._SELECT_CREDENTIAL`'s fail-closed
#: expression), and this writer cannot produce one.
#:
#: `created_at` and `updated_at` are left to their column DEFAULTs, which is
#: correct on an INSERT and is why DW-17 — `users` has no BEFORE UPDATE trigger,
#: so every *writer* has to set `updated_at` by hand — does not apply here.
#:
#: The `RETURNING` list is `auth._RECORD_LOGIN`'s, `auth._SET_PASSWORD`'s and
#: `auth._CHANGE_PASSWORD`'s, character for character: it is the eleven-column
#: shape `User.model_validate` wants, and the four must not drift. Repeated
#: rather than shared through a constant because `tests/test_source_guards.py`
#: forbids a statement assembled from a value; `tests/test_create_user.py` is
#: what holds the lists together instead.
_INSERT_USER = """
INSERT INTO users (name, email, password_hash, role,
                   active, must_change_password, temp_credential_expires_at)
VALUES (%s, lower(%s), %s, %s, true, true, now() + make_interval(hours => %s))
RETURNING id, name, email, role, active, must_change_password,
          temp_credential_expires_at, last_login_at, locked_until,
          created_at, updated_at
"""


def _invalid_email() -> ApiError:
    """Refuse an address, naming the rule it broke.

    `422`, matching every other body the request contract refuses, and a code of
    its own so `apps/web` can mark and focus the field the Administrator has to
    fix. See `INVALID_EMAIL` for why this is not left to the request model.
    """
    return ApiError(
        INVALID_EMAIL,
        NOT_AN_ADDRESS,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        headers=NO_STORE,
    )


def _email_already_exists() -> ApiError:
    """The address is already somebody's login. Built from the database's own verdict."""
    return ApiError(
        EMAIL_ALREADY_EXISTS,
        ADDRESS_ALREADY_IN_USE,
        status_code=status.HTTP_409_CONFLICT,
        headers=NO_STORE,
    )


@router.post("/admin/users", response_model=User, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> User:
    """FR-11 — write a `Staff` or `Administrator` row an Administrator can hand over.

    **The `administrator` parameter is the authorization, not a value.** It is
    the caller, resolved from the session cookie and re-read from Postgres on
    this request (AD-3) — nothing in the body names who is acting, and nothing
    in the body can. It is unread in the lines below on purpose: declaring the
    dependency is the whole of its job, and the refusal it raises happens before
    this function is entered.

    Sync, not `async def`: psycopg is a synchronous driver and the Argon2id hash
    below is CPU-bound for ~100ms. FastAPI runs a sync endpoint in its
    threadpool; an `async def` around the same calls would block every other
    request in the process.

    The order is the cheap refusals first, so that nothing a rule can reject
    costs a hash: normalize the address, then the length rules
    (`password_rule_violation`, one `len()`), and only then `hash_password`. A
    Staff caller never reaches any of it — `require_administrator` refuses
    before the handler runs at all.

    The response carries a `User`, which has no `password_hash` field to leave
    out, and never the submitted password: the Administrator typed it, the
    screen already has it, and putting it back on the wire would put it in
    whatever wrote the response down. `NO_STORE` for the same reason every other
    authenticated response carries it.

    Story 1.12 owes this endpoint an audit entry — AGENTS.md Policy requires the
    append-only log to cover user changes, and provisioning somebody else's
    access is the clearest one there is. Until that log exists the only record
    of who was given access, by whom, is the row's own `created_at`, which does
    not say by whom. No private log path is built in the meantime. DW-40/DW-69:
    this is the fourth Argon2id-backed endpoint and nothing counts its calls.
    """
    response.headers.update(NO_STORE)

    email = _normalize_email(payload.email)
    if email is None:
        # Before the password is looked at, so a body with two problems in it is
        # answered about the one the Administrator can see is wrong, and nothing
        # is hashed for a row that was never going to be written.
        raise _invalid_email()

    # The length rules, in their one statement (`shared_schema.passwords`), with
    # the sentence that names the rule that failed. Checked before the hash, so a
    # too-short temporary password costs one `len()` rather than 64 MiB.
    violation = password_rule_violation(payload.temporary_password)
    if violation is not None:
        raise _weak_password(violation)

    # Hashed outside any transaction: ~100ms of CPU inside an open one is ~100ms
    # of held locks on `users` for no benefit. The connection is autocommit
    # (`api.db`), and a single INSERT needs no explicit transaction of its own.
    password_hash = hash_password(payload.temporary_password)

    try:
        row = conn.execute(
            _INSERT_USER,
            (
                payload.name,
                email,
                password_hash,
                payload.role.value,
                TEMP_CREDENTIAL_LIFETIME_HOURS,
            ),
        ).fetchone()
    except pg_errors.UniqueViolation as clash:
        # Caught rather than pre-empted by a `SELECT`: a read-then-write is a
        # race that hands two people the same login, and the database is the only
        # thing that can decide between two submissions arriving together. Every
        # other `psycopg.Error` propagates and is answered as a 500, because
        # nothing else about this write is a failure the caller can act on.
        #
        # Narrowed to the one index by name rather than to the exception class:
        # see `EMAIL_UNIQUE_INDEX`. A clash this endpoint cannot explain is
        # re-raised rather than described as a duplicate address.
        if clash.diag.constraint_name != EMAIL_UNIQUE_INDEX:
            raise
        raise _email_already_exists() from clash

    # `INSERT ... RETURNING` yields exactly one row when it writes one, and every
    # way it writes none raises above rather than returning empty.
    return User.model_validate(row)


#: The read, in one statement. FR-10: every account, with its status.
#:
#: **The column list is `_INSERT_USER`'s `RETURNING` list — the same eleven
#: columns, in the same order.** It is the shape `User.model_validate` wants, and
#: the five statements in the product that produce it must not drift apart.
#: Repeated rather than shared through a constant for the reason `_INSERT_USER`
#: gives — `tests/test_source_guards.py` forbids a statement assembled from a
#: value — and `tests/test_user_list.py` is what holds this one to that one. That
#: guard compares the two lists with whitespace collapsed, so each statement is
#: free to indent its own continuation lines the way its own keyword wants.
#:
#: **The order is `lower(name)`, then `email`.** This list is read by a human
#: looking for a person, so it is ordered by the thing they are looking them up
#: by; and it is folded because Postgres's default `C` collation orders by code
#: point, which files every lowercase name after every uppercase one — `ruwan`
#: would sort after `Zoya`, which is not a list anybody can scan. `email` is the
#: tie-break because it is the table's only unique non-opaque column: two people
#: really can share a name, and without a second key their relative order is
#: whatever the planner felt like, which is not something a test can assert.
#:
#: **No `WHERE`, no `LIMIT`, and no parameter at all.** The acceptance clause is
#: every account with its status, and a filter on the one surface whose job is
#: "who has access" hides the row somebody opened the screen to find. A silent
#: `LIMIT` would be worse: it answers "who has access" with "some of them". The
#: table is tens of rows in an internal tool with no self-service registration —
#: bounded by the number of people an Administrator has personally provisioned —
#: and if that ever stops being true, measure before reaching for pagination
#: (CLAUDE.md).
_SELECT_USERS = """
SELECT id, name, email, role, active, must_change_password,
       temp_credential_expires_at, last_login_at, locked_until,
       created_at, updated_at
FROM users
ORDER BY lower(name), email
"""


@router.get("/admin/users", response_model=list[User])
def list_users(
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> list[User]:
    """FR-10 — every account, with its status and its last sign-in.

    **The `administrator` parameter is the authorization, not a value.** As on
    the write above: it is the caller, resolved from the session cookie and
    re-read from Postgres on this request (AD-3), and declaring the dependency is
    the whole of its job. A Staff caller is refused before this function is
    entered, and an Administrator still holding a temporary credential is refused
    before that by `require_claimed_user`, which `require_administrator` chains
    on.

    Sync, not `async def`: psycopg is a synchronous driver (AD-3,
    `tests/test_source_guards.py`), and FastAPI runs a sync endpoint in its
    threadpool.

    **A bare JSON array, not an envelope.** There is no cursor, no total and no
    page to carry, and inventing `{"users": [...]}` to leave room for one is a
    shape the product would have to keep honouring after pagination never
    arrives. `GET /auth/session` already returns a bare `User`; this returns bare
    `User`s. The classic argument against a top-level array — JSON hijacking
    through `<script src>` — needs an overridable `Array` constructor, which no
    browser has had since ES5, and this response is `no-store`, cookie-gated and
    `SameSite=Strict` besides. When a cursor is genuinely needed, both halves of
    the contract change together.

    **Every row, including the caller's own.** An Administrator auditing who has
    access is one of the people who has it, and a list that quietly omitted the
    reader would be answering a different question. Deactivated rows and locked
    rows are in it for the same reason: FR-10 asks for every account *with its
    status*, so a filter would delete the very thing being asked about.

    **`locked_until` is rendered and never decided from.** `shared_schema.user`
    says it in the field's own docstring: the lock is status, never enforcement,
    the column is never cleared, and a client that treats a past value as "locked"
    is reading it wrong. This list is the surface FR-4 meant by "visible to
    Administrators on that user's status", which closes DW-64's *rendering* half.
    It does not close the other half: there is still no unlock, and since Story
    1.10 shipped without one — its clauses are name, email and role — no story in
    Epic 1 owes it either.

    `NO_STORE` for the reason every other authenticated response carries it —
    and more so here, because this body names every member of staff the product
    knows about. `User` has no `password_hash` field to leave out.
    """
    response.headers.update(NO_STORE)

    # `model_validate` per row rather than a bulk construction: it is the same
    # gate the write goes through, so a column that stopped matching the contract
    # fails loudly here instead of reaching the wire as an extra key.
    return [User.model_validate(row) for row in conn.execute(_SELECT_USERS)]


#: What an explicit `null` is told. Raised from the validator below, so it
#: renders as `api.main`'s generic 422 sentence rather than this one — it is here
#: for the reader and for a `ValidationError` inspected in a test.
NULL_FIELD = "A field that is sent must carry a value; omit it to leave it alone."

#: And what a body naming none of the three fields is told, for the same
#: audience. See `EditUserRequest._changes_something` for why it is refused.
NOTHING_TO_CHANGE = "Send at least one of name, email or role."


class EditUserRequest(BaseModel):
    """The edit body: any of a name, an address and a role, and nothing else.

    `extra="forbid"`, like every other body in `apps/api`, and it is carrying
    more weight here than anywhere else in the module: `users` has eleven
    columns and this route may write three, so every other column has to be
    refused rather than discarded. A body sending `{"active": false}` is a
    caller who believes this endpoint deactivates accounts — it does not, Story
    1.11 owns that verb — and answering `200` to it would be the product
    reporting a deactivation it never performed.

    **Absent and `null` are not the same request.** Absent means "leave this
    column alone", which is the whole point of a `PATCH`; `null` is a caller
    with a different idea of the contract, and none of these three columns is
    nullable. `_not_null` refuses it `mode="before"`, so it is a refusal about
    the request rather than a `None` that quietly reaches `COALESCE` and reads
    as "leave it alone" — two different intentions with one outcome is how a
    client bug becomes a silent no-op nobody can see.

    `role` is the shared `Role` enum, so `"owner"` is refused by pydantic before
    the handler runs — AGENTS.md Policy's "never a third role" enforced by the
    type rather than by a check somebody has to remember to write. The database's
    own `CHECK (role IN ('staff', 'admin'))` is the second, independent copy.

    The bounds are `CreateUserRequest`'s, exactly: the same two columns, written
    by the same table, so a name or an address this endpoint accepts and that one
    refuses would be a row the product can edit into a shape it cannot create.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    email: str | None = Field(default=None, min_length=1, max_length=MAX_EMAIL_LENGTH)
    role: Role | None = None

    @field_validator("name", "email", "role", mode="before")
    @classmethod
    def _not_null(cls, value: object) -> object:
        """Refuse an explicit `null`. See the class docstring.

        `mode="before"` because it has to run on the value as it arrived: after
        type validation a `None` is indistinguishable from the default, and the
        default is the one thing this must not refuse.
        """
        if value is None:
            raise ValueError(NULL_FIELD)
        return value

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        """The stored name, through the same rule `POST` applies (`_clean_name`)."""
        return _clean_name(value)

    @model_validator(mode="after")
    def _changes_something(self) -> EditUserRequest:
        """Refuse a body that asks for nothing.

        `{}` satisfies every field rule above — all three are optional — and
        would reach the `UPDATE` as three `COALESCE`s that each keep the column
        they found, writing nothing but `updated_at = now()`. That is a request
        that moves a timestamp for no reason, on the one column DW-63 has not
        yet decided the meaning of, and it is a client bug reported as success.
        One field is the floor.
        """
        if self.name is None and self.email is None and self.role is None:
            raise ValueError(NOTHING_TO_CHANGE)
        return self


#: The locking read that tells `404` from the floor refusal, and hands the
#: handler the address the counter carry needs.
#:
#: `FOR UPDATE` rather than a plain `SELECT`: the row is about to be written, and
#: taking the lock here means the `UPDATE` below cannot be raced between the two
#: statements — in particular, it cannot find zero rows because somebody else
#: deleted the row in between and have that reported as the Administrator floor.
#:
#: Four columns and not eleven. `email` is the *old* address, which
#: `throttle.carry_failures` needs and which the `UPDATE`'s `RETURNING` (the new
#: one) can no longer supply; `role` and `active` are for the reader. The row the
#: caller gets back is the `UPDATE`'s, never this one.
#:
#: PostgreSQL 18's `RETURNING OLD.*` would replace this statement outright and is
#: deliberately not used: `infra/migrations` states in as many words that this
#: repo's SQL stays inside what a 16.x cluster also has, and the test suite's own
#: ephemeral cluster is whatever `initdb` is on PATH.
_SELECT_USER_FOR_UPDATE = """
SELECT id, email, role, active
  FROM users
 WHERE id = %s
   FOR UPDATE
"""

#: Every active Administrator, locked — issued **only** when the requested role
#: is `staff`.
#:
#: What makes the floor airtight rather than nearly airtight. `_UPDATE_USER`'s
#: own predicate closes most of it, but two Administrators demoting each other at
#: the same instant would each evaluate `EXISTS (... other active administrator)`
#: against a snapshot in which the other is still an Administrator, and both
#: would succeed. Locking the active-Administrator rows first makes the second
#: transaction wait and re-evaluate the predicate against the first's committed
#: result, which is the only version of this check that is actually a check.
#:
#: **`ORDER BY id` is what keeps two demotions from deadlocking**: both lock the
#: same rows, so they must lock them in the same order or each can hold what the
#: other wants. The target row's own lock is taken *after* this, so a plain
#: rename — which takes no Administrator lock at all — can never be on the other
#: side of a cycle.
#:
#: Only for a demotion, because only a demotion can reduce the count. A promotion
#: or a rename paying for this lock would serialise every edit in the product
#: behind every other one, for a rule neither of them can break.
_LOCK_ACTIVE_ADMINISTRATORS = """
SELECT id
  FROM users
 WHERE role = 'admin'
   AND active
 ORDER BY id
   FOR UPDATE
"""

#: FR-12's write, in one statement: whichever of the three columns arrived, plus
#: the Administrator floor, plus `updated_at`.
#:
#: **`COALESCE` rather than SQL assembled from the fields that arrived.** The
#: obvious implementation collects a `SET` fragment per present field and joins
#: them, which is precisely the shape `tests/test_source_guards.py` forbids — and
#: it is forbidden for a reason beyond injection: a fragment list built in Python
#: is a place where a field can be dropped silently, and a `RETURNING` shape that
#: varies with the request is a place where `User.model_validate` starts failing
#: for one caller in twenty. One statement has a fixed parameter list, a fixed
#: `RETURNING` shape, and no branch that can forget a column.
#:
#: **The address is folded by Postgres, not by Python**, for `_INSERT_USER`'s
#: reason: `users` carries `CHECK (email = lower(email))`, and `str.lower()` and
#: Postgres's `lower()` are not guaranteed to agree on non-ASCII input. Writing
#: `lower(%s)` makes the constraint unfailable. `lower(NULL)` is `NULL`, so an
#: absent address still coalesces to the column.
#:
#: **`updated_at` is set by hand.** `users` carries no BEFORE UPDATE trigger
#: (DW-17) and the column's DEFAULT applies to inserts only, so every writer sets
#: it — `auth`'s three do, `throttle._MIRROR_LOCK` does, and this one does.
#:
#: **The floor is a predicate here rather than a `SELECT count(*)` in Python.**
#: A count read a moment earlier is the read-then-write AD-8 rejects for the
#: throttle and it fails the same way: two demotions each see the other and both
#: succeed. Inside the statement it is evaluated against the rows as they are
#: locked. It reads: the row ends up an Administrator, **or** it was not one to
#: begin with, **or** it is deactivated (a deactivated account is not one of the
#: active Administrators the floor counts), **or** somebody else is an active
#: Administrator. Zero rows written therefore means the floor refused — the id is
#: already known to exist, because `_SELECT_USER_FOR_UPDATE` found and locked it.
#:
#: The `RETURNING` list is `_INSERT_USER`'s and `_SELECT_USERS`' column list,
#: character for character: the eleven-column shape `User.model_validate` wants.
#: Repeated rather than shared through a constant because
#: `tests/test_source_guards.py` forbids a statement assembled from a value;
#: `tests/test_edit_user.py` is what holds the three lists together instead.
_UPDATE_USER = """
UPDATE users
   SET name = COALESCE(%s::text, name),
       email = COALESCE(lower(%s::text), email),
       role = COALESCE(%s::text, role),
       updated_at = now()
 WHERE id = %s
   AND (COALESCE(%s::text, role) = 'admin'
        OR role = 'staff'
        OR NOT active
        OR EXISTS (SELECT 1
                     FROM users AS other
                    WHERE other.id <> users.id
                      AND other.role = 'admin'
                      AND other.active))
RETURNING id, name, email, role, active, must_change_password,
          temp_credential_expires_at, last_login_at, locked_until,
          created_at, updated_at
"""


def _user_not_found() -> ApiError:
    """The id names no row. `404`, so the Administrator refetches the list."""
    return ApiError(
        USER_NOT_FOUND,
        NO_SUCH_USER,
        status_code=status.HTTP_404_NOT_FOUND,
        headers=NO_STORE,
    )


def _last_administrator() -> ApiError:
    """The demotion would leave the product with nobody in charge. See the code."""
    return ApiError(
        LAST_ADMINISTRATOR,
        LAST_ACTIVE_ADMINISTRATOR,
        status_code=status.HTTP_409_CONFLICT,
        headers=NO_STORE,
    )


@router.patch("/admin/users/{user_id}", response_model=User)
def edit_user(
    user_id: UUID,
    payload: EditUserRequest,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> User:
    """FR-12 — change a user's name, email or role, and nothing else.

    **The `administrator` parameter is the authorization, not a value.** As on
    the other two routes: it is the caller, resolved from the session cookie and
    re-read from Postgres on this request (AD-3), and declaring the dependency is
    the whole of its job. It is unread below on purpose — nothing in the body
    names who is acting, and nothing in the body can. A Staff caller is refused
    before this function is entered, and an Administrator still holding a
    temporary credential is refused before that by `require_claimed_user`.

    **AD-3 is what makes a role change land on the live session, so this handler
    does nothing about sessions at all and must never start.** `lookup_session`
    re-reads `role` and `active` on every request, so the target's very next
    request is served under the new role — no sign-out, no re-login, and no
    change to `api/sessions.py`. FR-12's "not only at next authentication" half
    is a property the product already had; this story proves it with a test
    rather than building a mechanism for it.

    **An address change revokes nothing.** The target's existing sessions stay
    valid and their very next request is served as before — only the address they
    sign in *with* has moved. That is deliberate: a corrected typo is an
    Administrator fixing their own mistake, not evidence that the account is
    compromised, and signing somebody out of a shift for it would make the
    correction cost more than the mistake. Revocation belongs to the events that
    are actually about the credential — a password change (`api.auth`), and
    deactivation, which is Story 1.11's. The lockout counter is the one thing
    that follows the address, and it follows it *as it is* (DW-59): a rename is
    not an unlock.

    **A caller may edit their own row**, including demoting themselves while
    another active Administrator exists. There is nothing to protect them from:
    the row is theirs, the floor below still refuses the demotion that would
    leave nobody in charge, and an Administrator who wants to stop being one
    should not need a second Administrator to do it for them. `apps/web` adopts
    the returned row as the session's cached user when the id is the caller's.

    Sync, not `async def`: psycopg is a synchronous driver
    (`tests/test_source_guards.py`), and FastAPI runs a sync endpoint in its
    threadpool. No hash is spent here — this route touches no credential.

    The order is the cheap refusal first. The address is normalized and refused
    before anything is locked, so a mistyped one costs no row lock at all; then
    one transaction holds the Administrator lock (for a demotion only), the
    locking read that tells a `404` from the floor refusal, the `UPDATE`, and the
    counter carry, because a rename that committed without its carry is the
    stranded lockout DW-59 describes.

    `NO_STORE` for the reason every authenticated response carries it. The
    response is a `User`, which has no `password_hash` field to leave out.

    Story 1.12 owes this endpoint an audit entry — AGENTS.md Policy requires the
    append-only log to cover user changes, and changing somebody's role is one.
    Until that log exists the only trace of an edit is the row's `updated_at`,
    which says neither who changed it nor what changed. No private log path is
    built in the meantime.
    """
    response.headers.update(NO_STORE)

    email: str | None = None
    if payload.email is not None:
        email = _normalize_email(payload.email)
        if email is None:
            # Before anything is locked, so a body with a typo in it holds no row
            # in the table while it is being refused.
            raise _invalid_email()

    role = None if payload.role is None else payload.role.value

    # One unit of work. The carry below and the rename above it must commit
    # together or not at all: a carry without its rename moves a lock onto an
    # address nobody uses, and a rename without its carry strands the run on the
    # old string (DW-59). `api.db` hands out autocommit connections, so this is
    # the explicit transaction that makes the two statements one.
    with conn.transaction():
        if role == Role.STAFF.value:
            # Only for a demotion, and before the target row's own lock. See
            # `_LOCK_ACTIVE_ADMINISTRATORS` for both halves of why.
            conn.execute(_LOCK_ACTIVE_ADMINISTRATORS)

        current = conn.execute(_SELECT_USER_FOR_UPDATE, (user_id,)).fetchone()
        if current is None:
            # Distinguished from the floor refusal by this read rather than by
            # guessing at a zero-row `UPDATE`: two different states must not
            # share one answer because one statement cannot tell them apart.
            raise _user_not_found()

        try:
            row = conn.execute(
                _UPDATE_USER,
                (payload.name, email, role, user_id, role),
            ).fetchone()
        except pg_errors.UniqueViolation as clash:
            # `_INSERT_USER`'s reasoning, unchanged: the unique index over
            # `lower(email)` is the only thing that can decide between two
            # requests arriving together, and it is narrowed to that index by
            # name. A clash this endpoint cannot explain is re-raised and
            # answered as a 500, which is honest, rather than pointing the
            # Administrator at an email field that is fine.
            if clash.diag.constraint_name != EMAIL_UNIQUE_INDEX:
                raise
            raise _email_already_exists() from clash

        if row is None:
            # The id exists — it was found and locked above — so the only way the
            # statement matched nothing is its own floor predicate.
            raise _last_administrator()

        if email is not None:
            # **The counter's key is the Python fold, not the stored column.**
            # `api.auth.login` keys `login_attempts` on `payload.email.strip()
            # .lower()`, while `users.email` holds *Postgres's* `lower()` of the
            # same string — and the two are not guaranteed to agree on non-ASCII
            # input. `İ` is the standard example, and it is the whole reason
            # `_INSERT_USER` writes `lower(%s)` rather than folding in Python.
            # Handing `current["email"]` to the carry would therefore look up a
            # key that has no row wherever the folds differ: the delete would
            # remove nothing, the run would stay on the address sign-in actually
            # uses, and DW-59 would be reproduced by the code written to close
            # it. Folding the stored address the way `login` folds a submitted
            # one is what names the same key.
            old_key = current["email"].strip().lower()
            # Compared against `email`, which `_normalize_email` produced and
            # which is itself a Python fold — like with like. Comparing the
            # request against the raw column would compare the two folds and
            # call an unchanged address a rename (or the reverse) on exactly the
            # input where it matters.
            if old_key != email:
                # The account's run of failures follows the account, so a rename
                # is not a way around a lockout (DW-59). Inside this
                # transaction, and only when the address actually moved. The
                # carry re-mirrors `users.locked_until` itself — see its
                # docstring for why that is not something the rename already did.
                carried = throttle.carry_failures(conn, old_key, email, user_id)
                if carried is not None:
                    # `_UPDATE_USER`'s `RETURNING` was taken before that mirror,
                    # so the one column it can now be stale about is this one —
                    # and it is the column FR-4 asks an Administrator to read.
                    # Corrected from the carry's own answer rather than by
                    # re-selecting the row: a second `SELECT` would need a fourth
                    # copy of the eleven-column list for one value that is
                    # already in hand. `updated_at` needs no such correction:
                    # `now()` is the transaction timestamp, so the mirror wrote
                    # the instant the rename already returned.
                    row["locked_until"] = carried

    return User.model_validate(row)


#: FR-13's first write: flip `active` off, behind the Administrator floor.
#:
#: **The floor is `_UPDATE_USER`'s predicate, arm for arm.** Story 1.10 built
#: it, this statement copies it, and `_DELETE_USER` below copies it again —
#: one rule, one code, one sentence across demote, deactivate and delete. The
#: one arm `_UPDATE_USER` carries that is missing here is the
#: `COALESCE(%s::text, role) = 'admin'` head, which asks "does the row end up an
#: Administrator": that arm belongs to a statement that can *change* the role,
#: and this one cannot. What is left is Story 1.10's three: the row was never an
#: Administrator, **or** it is already deactivated (a deactivated account is not
#: one of the active Administrators the floor counts, so deactivating it again
#: is idempotent rather than refused), **or** somebody else is an active
#: Administrator.
#:
#: A predicate inside the statement rather than a `SELECT count(*)` in Python,
#: for `_UPDATE_USER`'s reason and AD-8's: a count read a moment earlier is the
#: read-then-write that lets two concurrent deactivations each see the other and
#: both succeed. Zero rows written therefore means the floor refused — the id is
#: already known to exist, because `_SELECT_USER_FOR_UPDATE` found and locked it.
#:
#: **`updated_at` is set by hand.** `users` carries no BEFORE UPDATE trigger
#: (DW-17 names this story explicitly) and the column's DEFAULT applies to
#: inserts only, so every writer sets it.
#:
#: Nothing else moves. `must_change_password`, `temp_credential_expires_at`,
#: `locked_until` and `password_hash` are all left exactly as they were: a
#: deactivation is the removal of access, not a credential event, and a
#: reactivation has to put the account back the way it was rather than the way a
#: fresh one starts.
#:
#: The `RETURNING` list is `_INSERT_USER`'s, `_SELECT_USERS`' and
#: `_UPDATE_USER`'s, character for character — the eleven-column shape
#: `User.model_validate` wants. Repeated rather than shared through a constant
#: because `tests/test_source_guards.py` forbids a statement assembled from a
#: value; `tests/test_deactivate_user.py` is what holds the lists together.
_DEACTIVATE_USER = """
UPDATE users
   SET active = false,
       updated_at = now()
 WHERE id = %s
   AND (role = 'staff'
        OR NOT active
        OR EXISTS (SELECT 1
                     FROM users AS other
                    WHERE other.id <> users.id
                      AND other.role = 'admin'
                      AND other.active))
RETURNING id, name, email, role, active, must_change_password,
          temp_credential_expires_at, last_login_at, locked_until,
          created_at, updated_at
"""

#: The inverse, and **deliberately without a floor predicate**.
#:
#: Raising the number of active Administrators can never reduce it, so there is
#: no state this write can reach that the floor exists to prevent. Copying the
#: predicate here "for symmetry" would be a guard that can never fire — dead
#: code reading as though reactivation were a counted decision — and the
#: verification step for this story is to add one and watch nothing fail.
#:
#: **It restores nothing else.** No session comes back (the rows were deleted,
#: not disabled — see `deactivate_user`), no temporary credential is reissued,
#: no password is set, and `must_change_password` is untouched. Reactivation is
#: the exact inverse of the flag and of nothing else: the account resumes with
#: the credential it already had, and the person signs in again.
#:
#: Idempotent on an already-active row, which is why it carries no `AND active
#: IS false`: a second press writes the same value and answers the same row,
#: where a predicate would answer a zero-row result that the handler would have
#: to describe as something. `updated_at` moves either way (DW-17).
_ACTIVATE_USER = """
UPDATE users
   SET active = true,
       updated_at = now()
 WHERE id = %s
RETURNING id, name, email, role, active, must_change_password,
          temp_credential_expires_at, last_login_at, locked_until,
          created_at, updated_at
"""

#: FR-13's hard delete, behind the identical floor.
#:
#: The same three arms as `_DEACTIVATE_USER`, for the same reason and worded the
#: same way: one rule across all three verbs, so an Administrator refused a
#: deactivation and an Administrator refused a delete are told the same thing
#: by the same code. A deactivated Administrator deletes freely — the `NOT
#: active` arm — because the floor counts *active* Administrators and that row
#: was never one of them.
#:
#: **`RETURNING id` is what makes a zero-row result readable.** A bare `DELETE`
#: reports a row count and nothing else, and zero would then mean either "no
#: such row" or "the floor refused" with no way to tell them apart. The locking
#: read above has already settled the first, so `RETURNING` here is belt to that
#: brace: the statement answers a row when it removed one, and nothing when the
#: predicate held it back.
#:
#: **Nothing cleans up after it.** `sessions.user_id` carries `ON DELETE
#: CASCADE` (`infra/migrations/20260917T1300_create_sessions.up.sql` says in as
#: many words that it is there for this), so the target's sessions go with the
#: row and no application code has to remember. `login_attempts` deliberately
#: does *not* go: it is keyed on the submitted address and is not a foreign key
#: to `users`, so a lockout survives the account it was earned on — clearing it
#: would make delete-and-recreate an unlock (DW-59/DW-91). `users.locked_until`
#: does go, and that is correct: it is a mirror of the counter, not the counter.
_DELETE_USER = """
DELETE FROM users
 WHERE id = %s
   AND (role = 'staff'
        OR NOT active
        OR EXISTS (SELECT 1
                     FROM users AS other
                    WHERE other.id <> users.id
                      AND other.role = 'admin'
                      AND other.active))
RETURNING id
"""


@router.post("/admin/users/{user_id}/deactivate", response_model=User)
def deactivate_user(
    user_id: UUID,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> User:
    """FR-13 — take an account's access away, on the target's very next request.

    **The `administrator` parameter is the authorization, not a value.** As on
    every other route in this module: it is the caller, resolved from the
    session cookie and re-read from Postgres on this request (AD-3), and
    declaring the dependency is the whole of its job. It is unread below on
    purpose. A Staff caller is refused before this function is entered, and an
    Administrator still holding a temporary credential is refused before that by
    `require_claimed_user`, which `require_administrator` chains on.

    **No request body at all**, so there is no shape of request to this route
    that says anything but "this id, off". The id is in the path and the verb is
    the route.

    **Both halves of the revocation, and neither is redundant.**
    `sessions._SELECT_SESSION` joins `AND u.active`, so the flag alone makes the
    target's very next request a `401` the instant it lands (AD-3, and the whole
    of FR-13's "not just future logins" clause — proved by a test rather than
    built here). Deleting the rows is what makes it *durable*: without it a
    later reactivation would bring every still-unexpired session back to life,
    handing back access the Administrator believed they had revoked, and that is
    two clicks away now that `activate_user` exists. AGENTS.md line 18 says
    *revoke*, not *refuse*, and this is what revoking is.
    `sessions.delete_sessions_for_user` is reused rather than copied — AD-3
    keeps every statement against that table in one module.

    **The Administrator lock is taken unconditionally**, where `edit_user` takes
    it only for a demotion. `edit_user` can read the intent off the body; this
    route has no body, so the target's role is not known until a row is read —
    and reading the target first is precisely the lock-ordering inversion
    `_LOCK_ACTIVE_ADMINISTRATORS`'s `ORDER BY id` exists to prevent. That widens
    DW-94 (a bogus id still serialises the Administrator set) from one route to
    three, which is accepted rather than overlooked: the caller is already an
    authenticated Administrator and these are rare operations.

    **Idempotent.** Deactivating an already-deactivated account answers `200`
    with the same row and still sweeps any session rows left behind — a row that
    survived an earlier failure is a live credential, and the second press is
    exactly when somebody would notice.

    **A caller may deactivate their own row**, while another active
    Administrator exists. The answer lands, and their own next request is the
    `401` this route just made it — `apps/web` drops to Login on it. There is
    nothing to protect them from that the floor below does not already refuse.

    Sync, not `async def`: psycopg is a synchronous driver
    (`tests/test_source_guards.py`), and FastAPI runs a sync endpoint in its
    threadpool. No hash is spent here — this route touches no credential.

    `NO_STORE` for the reason every authenticated response carries it. The
    response is a `User`, which has no `password_hash` field to leave out.

    Story 1.12 owes this endpoint an audit entry: removing somebody's access is
    the clearest "user change" AGENTS.md Policy's log is for. No private log
    path is built in the meantime, so the only trace today is the row's own
    `updated_at`, which says neither who nor what.
    """
    response.headers.update(NO_STORE)

    # One unit of work. The flag and the session sweep must commit together or
    # not at all: a flag without its sweep leaves rows a reactivation would
    # resurrect, and a sweep without its flag signs somebody out of a shift for
    # nothing.
    with conn.transaction():
        # Unconditionally, and before the target row's own lock. See the
        # docstring above and `_LOCK_ACTIVE_ADMINISTRATORS` for both halves.
        conn.execute(_LOCK_ACTIVE_ADMINISTRATORS)

        current = conn.execute(_SELECT_USER_FOR_UPDATE, (user_id,)).fetchone()
        if current is None:
            # Distinguished from the floor refusal by this read rather than by
            # guessing at a zero-row write: two different states must not share
            # one answer because one statement cannot tell them apart.
            raise _user_not_found()

        row = conn.execute(_DEACTIVATE_USER, (user_id,)).fetchone()
        if row is None:
            # The id exists — it was found and locked above — so the only way
            # the statement matched nothing is its own floor predicate. The
            # raise rolls the transaction back, which is what leaves the row and
            # its sessions untouched rather than merely unwritten.
            raise _last_administrator()

        # After the flag, inside the same transaction. The order is not load
        # bearing for correctness — nothing between them can be observed — but
        # it reads the way the rule does: the account is closed, then what it
        # had open is closed with it.
        sessions.delete_sessions_for_user(conn, user_id)

    return User.model_validate(row)


@router.post("/admin/users/{user_id}/activate", response_model=User)
def activate_user(
    user_id: UUID,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> User:
    """FR-13's inverse — give a deactivated account its access back.

    **Why it exists at all.** Neither of Story 1.11's two named verbs is this
    one, and a third route is a real widening. It is here because a deactivate
    with no inverse is a one-way door recoverable only by a developer holding
    `DATABASE_URL` — the exact dependency Epic 1 exists to remove — and because
    the binding UX spine already presumes the control: EXPERIENCE.md:148 tells
    the Administrator facing the last-Administrator refusal that they must
    "activate or create a second Administrator first".

    **No floor, and no lock.** Raising the number of active Administrators can
    never reduce it, so there is no counted decision here and nothing to
    serialise. Paying for `_LOCK_ACTIVE_ADMINISTRATORS` on this route would
    queue every reactivation behind every deactivation for a rule this statement
    cannot break.

    **It restores the flag and nothing else.** No session comes back — the rows
    were deleted, so there is nothing to restore, which is the durable half of
    what `deactivate_user` did. No temporary credential is reissued and no
    password is set: `must_change_password` and `temp_credential_expires_at` are
    left exactly as they were, so an account that was claimed resumes claimed
    and one that never was resumes with whatever is left of its 72 hours. The
    person signs in again with the credential they already had.

    **The lockout comes back with it**, because it never went: `login_attempts`
    is keyed on the address and `users.locked_until` rides on the row. A
    deactivation is not an unlock and neither is a reactivation (DW-59/DW-91,
    DW-64 — no unlock exists anywhere in Epic 1).

    Idempotent on an already-active account: `200`, same row, nothing to say.

    The `administrator` parameter, the sync `def`, `NO_STORE` and Story 1.12's
    owed audit entry are all as on `deactivate_user` above.
    """
    response.headers.update(NO_STORE)

    # One unit of work for two statements, so the row this answers with is the
    # row the locking read found. `api.db` hands out autocommit connections.
    with conn.transaction():
        current = conn.execute(_SELECT_USER_FOR_UPDATE, (user_id,)).fetchone()
        if current is None:
            raise _user_not_found()

        row = conn.execute(_ACTIVATE_USER, (user_id,)).fetchone()
        if row is None:  # pragma: no cover - the row is locked one line above
            # Unreachable: the statement carries no predicate and the row it
            # names is held under `FOR UPDATE`, so the only zero-row result
            # would be a row that vanished while locked. Answered as the `404`
            # it would be rather than as a `500`, and never as the floor — this
            # route has no floor to refuse from.
            raise _user_not_found()

    return User.model_validate(row)


@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    response: Response,
    administrator: Annotated[User, Depends(require_administrator)],
    conn: Annotated[psycopg.Connection, Depends(get_connection)],
) -> None:
    """FR-13 — remove the account outright. A hard delete, not a marker column.

    **`204`, with no body.** There is no row left to return, and answering with
    the row that was deleted would be the product describing something that no
    longer exists. `apps/web`'s `apiRequest` answers `null` for a `204` without
    trying to parse a body, so nothing on the client has to learn a new shape.

    **The sessions go by cascade, not by code.** `sessions.user_id` carries `ON
    DELETE CASCADE` and the migration that wrote it says it is there for exactly
    this, so the target's very next request is a `401` with no session logic on
    this path at all. `deactivate_user` calls
    `sessions.delete_sessions_for_user` because a flag has no cascade behind it;
    a delete does.

    **The lockout does not go.** `login_attempts` is keyed on the submitted
    address and deliberately not on `users.id`, so a live lock outlives the
    account. That is the point: clearing it would make "delete the account and
    recreate it" the admin unlock this product has decided not to have
    (DW-59/DW-91, DW-64). The row ages out through the existing sweep.

    **The address is freed.** The unique index is over `lower(users.email)`, so
    once the row is gone the address can be provisioned again — which closes the
    delete half of DW-79: a mistyped address is no longer consumed forever.

    **The floor is the same rule, and a deactivated Administrator is not on the
    right side of it by accident.** `_DELETE_USER` carries `_DEACTIVATE_USER`'s
    three arms unchanged, so deleting the last *active* Administrator is refused
    with the same `409` and the same sentence, while deleting a deactivated one
    is allowed — the floor counts active Administrators, and that row was never
    one of them.

    The Administrator lock is taken unconditionally, for the reason
    `deactivate_user` gives at length: no body means no way to know the target's
    role before a row is read, and reading first is the lock-ordering inversion
    `ORDER BY id` exists to prevent (DW-94, widened here on purpose).

    **A caller may delete their own row** while another active Administrator
    exists — the same reasoning as a self-demotion or a self-deactivation. Their
    next request is a `401` and `apps/web` drops to Login.

    The `administrator` parameter, the sync `def` and `NO_STORE` are as on the
    two routes above. Story 1.12 owes this one an audit entry and inherits a
    harder problem with it: a deleted user cannot be a foreign key from an audit
    row (AD-4 grants the application role no `DELETE` on that table), so the
    actor and target references have to be AD-10's denormalised snapshot.
    """
    response.headers.update(NO_STORE)

    with conn.transaction():
        # Unconditionally, and before the target row's own lock — see
        # `deactivate_user`.
        conn.execute(_LOCK_ACTIVE_ADMINISTRATORS)

        current = conn.execute(_SELECT_USER_FOR_UPDATE, (user_id,)).fetchone()
        if current is None:
            raise _user_not_found()

        if conn.execute(_DELETE_USER, (user_id,)).fetchone() is None:
            # The id exists, so the only way the statement matched nothing is
            # its own floor predicate. The raise rolls back, leaving the row and
            # every session it holds exactly as they were.
            raise _last_administrator()
