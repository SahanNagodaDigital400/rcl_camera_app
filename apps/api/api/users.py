"""`POST /admin/users` — an Administrator provisions somebody else's login.

FR-11, and the first route in the product that is not about the caller's own
identity. Four things about it are load-bearing:

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

**Not here.** No list, no edit, no deactivate, no delete — Stories 1.9, 1.10 and
1.11 own those, and this module serves one route until they arrive. **No mail of
any kind**, not a dependency, not a stub, not a "send the credential" control on
the screen: AGENTS.md Policy and FR-11 both put distribution in the
Administrator's hands, and `tests/test_no_password_reset.py` asserts the absence
over the source tree and the dependency manifests. **No audit entry** — Story
1.12 owns the append-only log and owes this endpoint one, and no private log path
is built in the meantime, so until then the only trace of a provisioning is the
row's own `created_at`. And **no throttle**: this is the fourth Argon2id-backed
endpoint in the product and a direct extension of DW-40/DW-69, which are open
and are decisions about what a counter would be keyed on — it is also
Administrator-only, so the caller is already authenticated and already named.
"""

from __future__ import annotations

from typing import Annotated

# Imported for real, not under TYPE_CHECKING: FastAPI resolves a handler's
# annotations at runtime to build its dependency graph, so a name that exists
# only for the type checker fails at import with a bare NameError.
import psycopg
from fastapi import APIRouter, Depends, Response, status
from psycopg import errors as pg_errors
from pydantic import BaseModel, ConfigDict, Field, field_validator
from shared_schema.errors import ApiError
from shared_schema.passwords import hash_password, password_rule_violation
from shared_schema.user import TEMP_CREDENTIAL_LIFETIME_HOURS, Role, User

# `api.auth` owns the two bounds and the rule-naming 422, and this module reads
# them rather than restating them: a second `MAX_EMAIL_LENGTH` is a second
# opinion about what an address is, and a second `422 weak_password` constructor
# is a second opinion about what a refused password looks like. `_weak_password`
# is private to that module in the sense that nothing outside `apps/api` may
# have it — importing it here is what keeps the two refusals one refusal.
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

        `min_length=1` alone admits `"   "`, which stores a row whose name
        renders as nothing at all on Story 1.9's list — a user nobody can
        identify, created by a form that reported success. Stripping here rather
        than in the handler means the stored value and the validated value are
        the same string.

        The control-character screen is `_normalize_email`'s, applied to the
        sibling `text` column for the reason `_has_control_character` gives: a
        NUL cannot survive a Postgres text parameter, and without this check it
        reaches `conn.execute` — after the Argon2id hash has been paid — and
        answers `500` where every other refused body answers `422`.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError(BLANK_NAME)
        if _has_control_character(stripped):
            raise ValueError(CONTROL_IN_NAME)
        return stripped


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
