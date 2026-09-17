"""The `User` contract is cross-layer, so its exact shape is asserted here."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from shared_schema.user import Role, User

EXPECTED_FIELDS = {
    "id",
    "name",
    "email",
    "role",
    "active",
    "must_change_password",
    "temp_credential_expires_at",
    "last_login_at",
    "locked_until",
    "created_at",
    "updated_at",
}


def a_user_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": str(uuid4()),
        "name": "Ruwan Perera",
        "email": "ruwan@rocell.lk",
        "role": "admin",
        "active": True,
        "must_change_password": True,
        "temp_credential_expires_at": datetime(2026, 9, 20, 12, 0, tzinfo=UTC).isoformat(),
        "last_login_at": None,
        "locked_until": None,
        "created_at": datetime(2026, 9, 17, 12, 0, tzinfo=UTC).isoformat(),
        "updated_at": datetime(2026, 9, 17, 12, 0, tzinfo=UTC).isoformat(),
    }
    body.update(overrides)
    return body


def test_the_field_set_is_exactly_the_contract() -> None:
    assert set(User.model_fields) == EXPECTED_FIELDS


def test_a_user_round_trips() -> None:
    user = User.model_validate(a_user_body())

    assert user.role is Role.ADMIN
    assert user.active is True
    assert user.must_change_password is True
    assert user.last_login_at is None
    assert set(user.model_dump()) == EXPECTED_FIELDS


def test_password_hash_is_refused() -> None:
    # The field does not exist on the model, so there is no serializer rule
    # anyone can forget. A body carrying one fails loudly instead of being
    # silently dropped.
    assert "password_hash" not in User.model_fields

    with pytest.raises(ValidationError):
        User.model_validate(a_user_body(password_hash="$argon2id$..."))


@pytest.mark.parametrize("role", ["manager", "Admin", "ADMIN", "staff ", "", "superuser"])
def test_a_role_outside_the_two_is_refused(role: str) -> None:
    with pytest.raises(ValidationError):
        User.model_validate(a_user_body(role=role))


@pytest.mark.parametrize("role", ["staff", "admin"])
def test_both_roles_are_accepted(role: str) -> None:
    assert User.model_validate(a_user_body(role=role)).role.value == role


def test_the_roles_are_exactly_staff_and_administrator() -> None:
    # AGENTS.md Policy: never a third role.
    assert {member.value for member in Role} == {"staff", "admin"}


def test_a_nullable_field_is_required_but_nullable() -> None:
    # Required-but-nullable, so the JSON always carries all eleven keys and the
    # TypeScript twin's closed-shape check can look for them.
    body = a_user_body()
    del body["last_login_at"]

    with pytest.raises(ValidationError):
        User.model_validate(body)


def test_the_lockout_status_is_required_but_nullable() -> None:
    # FR-4's status is nullable — most accounts have never been locked — but it
    # is not optional. Story 1.9's user list renders "Locked" from this key, and
    # a body that simply omitted it would be indistinguishable from one saying
    # "not locked" while the twin's closed-shape check refused the whole thing.
    assert User.model_validate(a_user_body(locked_until=None)).locked_until is None

    body = a_user_body()
    del body["locked_until"]
    with pytest.raises(ValidationError):
        User.model_validate(body)


def test_a_naive_lockout_status_is_refused() -> None:
    # `AwareDatetime`, like every other timestamp on this model: "locked now" is
    # `locked_until > now()`, and a value carrying no offset cannot be compared
    # against an instant without guessing a zone. The twin's `isUtcTimestamp`
    # rejects one too.
    with pytest.raises(ValidationError):
        User.model_validate(a_user_body(locked_until="2026-09-18T12:00:00"))


def test_timestamps_are_timezone_aware() -> None:
    user = User.model_validate(a_user_body())

    assert user.created_at.utcoffset() is not None
    assert user.created_at.astimezone(UTC).hour == 12


# --- The two halves of the contract ------------------------------------------
#
# The Python field set and the TypeScript twin's key list are each written out
# by hand. Without a test that reads one against the other, adding a field on
# one side alone ships green — and the front end simply stops recognising a
# body the API considers valid.

TS_USER = Path(__file__).resolve().parents[1] / "shared_schema" / "ts" / "user.ts"


def _ts_source() -> str:
    return TS_USER.read_text(encoding="utf-8")


def _ts_key_array(source: str, name: str) -> set[str]:
    match = re.search(rf"const {name}\s*=\s*\[(.*?)\]\s*as const;", source, re.DOTALL)
    assert match is not None, f"{name} is no longer declared as an array in user.ts"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_the_typescript_narrowing_check_covers_every_python_field() -> None:
    source = _ts_source()

    # `CONTRACT_KEYS` is where the literals live; `USER_KEYS` is a sorted copy
    # of it, so reading the sorted export would find a spread and no names.
    match = re.search(r"const CONTRACT_KEYS[^=]*=\s*\[(.*?)\]", source, re.DOTALL)
    assert match is not None, "CONTRACT_KEYS is no longer a literal list in user.ts"

    keys = set(re.findall(r"'([^']+)'", match.group(1)))
    for spread in re.findall(r"\.\.\.([A-Z_]+)", match.group(1)):
        keys |= _ts_key_array(source, spread)

    assert keys == EXPECTED_FIELDS == set(User.model_fields)


def test_the_typescript_interface_declares_every_python_field() -> None:
    source = _ts_source()

    match = re.search(r"export interface User \{(.*?)\n\}", source, re.DOTALL)
    assert match is not None, "the User interface is no longer declared in user.ts"

    assert set(re.findall(r"^  (\w+):", match.group(1), re.MULTILINE)) == EXPECTED_FIELDS


# --- The two halves agree about *values*, not only about keys -----------------
#
# The parity tests above compare key names. That left the halves free to
# disagree about what a valid value is, which is exactly where they did: the
# model took `datetime`, so a naive timestamp and a `+05:30` offset were both
# accepted and re-emitted verbatim — and `isUtcTimestamp` in the twin rejects
# both. A body this model had just validated could be refused by `isUser`,
# while every test stayed green.

UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]00:?00)$", re.IGNORECASE
)


def test_the_twins_utc_timestamp_pattern_is_the_one_asserted_here() -> None:
    # Transcribed, so a change to the twin's pattern that this file does not
    # follow is a failure rather than a quiet divergence.
    match = re.search(r"const UTC_TIMESTAMP_PATTERN\s*=\s*\n?\s*/(.+?)/i;", _ts_source(), re.DOTALL)
    assert match is not None, "UTC_TIMESTAMP_PATTERN is no longer a literal regex in user.ts"
    assert match.group(1).strip() == UTC_TIMESTAMP.pattern


def test_a_naive_timestamp_is_refused() -> None:
    # It carries no instant at all, and the twin will not narrow one.
    body = a_user_body()
    body["created_at"] = "2026-09-17T12:00:00"

    with pytest.raises(ValidationError):
        User.model_validate(body)


@pytest.mark.parametrize(
    "arrived_as",
    ["2026-09-17T12:00:00+05:30", "2026-09-17T12:00:00Z", "2026-09-17T12:00:00-08:00"],
)
def test_every_serialized_timestamp_is_utc_whatever_it_arrived_as(arrived_as: str) -> None:
    # `timestamptz` comes back from the driver in the session's time zone, so an
    # API process not set to UTC would otherwise put that offset on the wire.
    body = a_user_body()
    body["created_at"] = arrived_as
    body["temp_credential_expires_at"] = arrived_as

    emitted = json.loads(User.model_validate(body).model_dump_json())

    assert UTC_TIMESTAMP.match(emitted["created_at"]), emitted["created_at"]
    assert UTC_TIMESTAMP.match(emitted["temp_credential_expires_at"])
    assert datetime.fromisoformat(emitted["created_at"]) == datetime.fromisoformat(arrived_as)


def test_a_lockout_status_is_emitted_in_utc() -> None:
    # The serializer's field list is written out by hand, so a new timestamp
    # added to the model and forgotten there reaches the wire in whatever offset
    # the driver's session produced — and `isUtcTimestamp` refuses it.
    body = a_user_body(locked_until="2026-09-18T12:00:00+05:30")

    emitted = json.loads(User.model_validate(body).model_dump_json())

    assert UTC_TIMESTAMP.match(emitted["locked_until"]), emitted["locked_until"]


def test_a_serialized_user_satisfies_every_rule_the_twin_checks() -> None:
    # The round trip the key-set tests never made: what this model actually
    # emits, against the value rules `isUser` applies to it.
    emitted = json.loads(User.model_validate(a_user_body()).model_dump_json())

    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

    assert set(emitted) == set(User.model_fields)
    assert re.match(uuid_pattern, emitted["id"])
    assert emitted["role"] in {"staff", "admin"}
    for key in ("created_at", "updated_at"):
        assert UTC_TIMESTAMP.match(emitted[key]), (key, emitted[key])
    for key in ("temp_credential_expires_at", "last_login_at", "locked_until"):
        assert emitted[key] is None or UTC_TIMESTAMP.match(emitted[key])
