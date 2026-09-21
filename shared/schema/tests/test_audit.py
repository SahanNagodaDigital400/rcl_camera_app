"""The `AuditLogEntry` contract is cross-layer, so its exact shape is asserted here.

`test_user.py`'s structure, scoped to `audit.ts`: the two halves are written out
by hand on both sides, and without a test that reads one against the other,
adding a column on one side alone ships green — and the front end simply stops
recognising a body the API considers valid.

Two claims this file makes that its sibling does not. `action` is **not**
narrowed to the known vocabulary on either side — that is the contract, not an
omission, so it is asserted rather than left to a docstring. And the page size
is part of the contract rather than an implementation detail of the route: the
response is a bare array, so a page shorter than `PAGE_SIZE` is the only thing
that tells the screen it has reached the end, and two copies of that number
that disagree are a screen that stops one page early or offers one page too
many with nothing raising.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from shared_schema.audit import CURSOR_PARAM, PAGE_SIZE, AuditAction, AuditLogEntry

EXPECTED_FIELDS = {
    "id",
    "created_at",
    "action",
    "actor_user_id",
    "actor_email",
    "target_user_id",
    "target_email",
    "source_ip",
    "details",
}


def an_entry_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": str(uuid4()),
        "created_at": datetime(2026, 9, 21, 9, 30, tzinfo=UTC).isoformat(),
        "action": AuditAction.USER_EDITED.value,
        "actor_user_id": str(uuid4()),
        "actor_email": "ruwan@rocell.lk",
        "target_user_id": str(uuid4()),
        "target_email": "kasun@rocell.lk",
        "source_ip": "127.0.0.1",
        "details": {"changed": {"role": {"from": "staff", "to": "admin"}}},
    }
    body.update(overrides)
    return body


def test_the_field_set_is_exactly_the_contract() -> None:
    assert set(AuditLogEntry.model_fields) == EXPECTED_FIELDS


def test_an_entry_round_trips() -> None:
    entry = AuditLogEntry.model_validate(an_entry_body())

    assert entry.action == AuditAction.USER_EDITED
    assert entry.details["changed"] == {"role": {"from": "staff", "to": "admin"}}
    assert set(entry.model_dump()) == EXPECTED_FIELDS


def test_an_entry_with_no_actor_is_accepted() -> None:
    # A refused sign-in against an address that is not an account: nobody is
    # known, and both halves of the actor pair are null rather than absent.
    entry = AuditLogEntry.model_validate(
        an_entry_body(actor_user_id=None, actor_email=None, action=AuditAction.LOGIN_FAILED.value)
    )

    assert entry.actor_user_id is None
    assert entry.actor_email is None


def test_an_unrecorded_address_is_accepted() -> None:
    assert AuditLogEntry.model_validate(an_entry_body(source_ip=None)).source_ip is None


@pytest.mark.parametrize(
    "field", ["actor_user_id", "actor_email", "target_user_id", "target_email", "source_ip"]
)
def test_a_nullable_field_is_required_but_nullable(field: str) -> None:
    # Required-but-nullable, so the JSON always carries all nine keys and the
    # TypeScript twin's closed-shape check can look for them. "There was no
    # actor" and "the key never arrived" are different facts, and only the
    # first is ever true of this table.
    body = an_entry_body()
    del body[field]

    with pytest.raises(ValidationError):
        AuditLogEntry.model_validate(body)


def test_details_is_never_null() -> None:
    # The column defaults to `{}`, so a reader never has to tell "no detail"
    # from "not recorded".
    with pytest.raises(ValidationError):
        AuditLogEntry.model_validate(an_entry_body(details=None))

    assert AuditLogEntry.model_validate(an_entry_body(details={})).details == {}


def test_an_action_outside_the_vocabulary_is_served_verbatim() -> None:
    # The deliberate asymmetry: writes take `AuditAction`, reads take `str`.
    # The column has no CHECK, the vocabulary grows with Epics 2 and 3, and a
    # corrective entry is inserted by hand as the owner — so an entry this
    # build has never heard of is an ordinary state, and a viewer that refused
    # to render it would be a less faithful record than the table.
    entry = AuditLogEntry.model_validate(an_entry_body(action="catalogue_tile_added"))

    assert entry.action == "catalogue_tile_added"


def test_a_password_digest_has_nowhere_to_go() -> None:
    # No field holds one, and the shape is closed, so a body carrying one fails
    # loudly instead of being silently dropped.
    assert "password_hash" not in AuditLogEntry.model_fields

    with pytest.raises(ValidationError):
        AuditLogEntry.model_validate(an_entry_body(password_hash="$argon2id$..."))


def test_the_vocabulary_is_the_thirteen_actions_epic_one_writes() -> None:
    assert {member.value for member in AuditAction} == {
        "login_succeeded",
        "login_failed",
        "login_refused_locked",
        "logged_out",
        "password_claimed",
        "password_changed",
        "password_change_refused",
        "sessions_revoked",
        "user_provisioned",
        "user_edited",
        "user_deactivated",
        "user_activated",
        "user_deleted",
    }


# --- The two halves of the contract ------------------------------------------

TS_AUDIT = Path(__file__).resolve().parents[1] / "shared_schema" / "ts" / "audit.ts"


def _ts_source() -> str:
    return TS_AUDIT.read_text(encoding="utf-8")


def _ts_key_array(source: str, name: str) -> set[str]:
    match = re.search(rf"const {name}\s*=\s*\[(.*?)\]\s*as const;", source, re.DOTALL)
    assert match is not None, f"{name} is no longer declared as an array in audit.ts"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_the_typescript_narrowing_check_covers_every_python_field() -> None:
    source = _ts_source()

    # `CONTRACT_KEYS` is where the literals live; `AUDIT_LOG_ENTRY_KEYS` is a
    # sorted copy of it, so reading the sorted export would find a spread and
    # no names.
    match = re.search(r"const CONTRACT_KEYS[^=]*=\s*\[(.*?)\]", source, re.DOTALL)
    assert match is not None, "CONTRACT_KEYS is no longer a literal list in audit.ts"

    keys = set(re.findall(r"'([^']+)'", match.group(1)))
    for spread in re.findall(r"\.\.\.([A-Z_]+)", match.group(1)):
        keys |= _ts_key_array(source, spread)

    assert keys == EXPECTED_FIELDS == set(AuditLogEntry.model_fields)


def test_the_typescript_interface_declares_every_python_field() -> None:
    source = _ts_source()

    match = re.search(r"export interface AuditLogEntry \{(.*?)\n\}", source, re.DOTALL)
    assert match is not None, "the AuditLogEntry interface is no longer declared in audit.ts"

    assert set(re.findall(r"^  (\w+):", match.group(1), re.MULTILINE)) == EXPECTED_FIELDS


def _ts_action_literals(pattern: str) -> set[str]:
    match = re.search(pattern, _ts_source(), re.DOTALL)
    assert match is not None, f"audit.ts no longer matches {pattern}"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_the_twin_names_every_action_in_its_union() -> None:
    # The union is what the screen's label map is keyed on, so a member added
    # here and not there is a `Record<AuditAction, string>` the compiler cannot
    # see is incomplete — the entry would render under a fallback nobody meant.
    declared = _ts_action_literals(r"export type AuditAction =\s*(.*?);")

    assert declared == {member.value for member in AuditAction}


def test_the_twins_iterable_action_list_is_the_union() -> None:
    # `AUDIT_ACTIONS` is what `isAuditAction` reads, so a union member missing
    # from it is a value the type accepts and the narrower rejects.
    listed = _ts_action_literals(r"export const AUDIT_ACTIONS[^=]*=\s*\[(.*?)\];")

    assert listed == {member.value for member in AuditAction}


def test_the_twin_leaves_the_action_field_a_plain_string() -> None:
    # The asymmetry, asserted on the twin as well as on the model. Narrowing
    # this field to the union would make the front end refuse exactly the
    # entries the fallback label exists for.
    match = re.search(r"export interface AuditLogEntry \{(.*?)\n\}", _ts_source(), re.DOTALL)
    assert match is not None

    assert re.search(r"^  action: string;$", match.group(1), re.MULTILINE)


def test_the_page_size_is_the_same_number_in_both_languages() -> None:
    # Read out of the twin's source rather than imported, exactly as the key
    # lists above are: nothing crosses that boundary at build time, so the only
    # way the two can be held together is by one side reading the other's text.
    # `apps/web`'s `error-code-parity.test.ts` reads Python integers the same
    # way in the other direction.
    match = re.search(r"^export const AUDIT_PAGE_SIZE = (\d+);$", _ts_source(), re.MULTILINE)
    assert match is not None, "AUDIT_PAGE_SIZE is no longer a literal integer in audit.ts"

    assert int(match.group(1)) == PAGE_SIZE


def test_the_cursor_parameter_is_the_same_name_in_both_languages() -> None:
    # The product's only query parameter, and the first thing the two halves
    # have had to agree on beyond a path. Read out of the twin's source the way
    # the page size above is. An unpinned rename is worse than a broken path: a
    # wrong path is a 404 the screen reports, while an unknown query parameter
    # is silently ignored and `GET /admin/audit` answers the *first* page to
    # every Load more, so the log repeats its newest entries forever.
    match = re.search(r"^export const AUDIT_CURSOR_PARAM = '([^']+)';$", _ts_source(), re.MULTILINE)
    assert match is not None, "AUDIT_CURSOR_PARAM is no longer a literal string in audit.ts"

    assert match.group(1) == CURSOR_PARAM


def test_the_page_size_is_a_usable_page() -> None:
    # A guard against the two halves being pinned to a number that is wrong on
    # both sides. Zero would make every page empty and the screen would render
    # an empty log forever; one would make the read a request per entry. The
    # bound is deliberately loose — this is the shape of the value, not a
    # second opinion about what it should be.
    assert 1 < PAGE_SIZE <= 500


# --- The two halves agree about *values*, not only about keys -----------------

UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]00:?00)$", re.IGNORECASE
)


def test_the_twins_utc_timestamp_pattern_is_the_one_asserted_here() -> None:
    # Transcribed, so a change to the twin's pattern that this file does not
    # follow is a failure rather than a quiet divergence.
    match = re.search(r"const UTC_TIMESTAMP_PATTERN\s*=\s*\n?\s*/(.+?)/i;", _ts_source(), re.DOTALL)
    assert match is not None, "UTC_TIMESTAMP_PATTERN is no longer a literal regex in audit.ts"
    assert match.group(1).strip() == UTC_TIMESTAMP.pattern


def test_a_naive_timestamp_is_refused() -> None:
    # It carries no instant at all, and the twin will not narrow one.
    with pytest.raises(ValidationError):
        AuditLogEntry.model_validate(an_entry_body(created_at="2026-09-21T09:30:00"))


@pytest.mark.parametrize(
    "arrived_as",
    ["2026-09-21T09:30:00+05:30", "2026-09-21T09:30:00Z", "2026-09-21T09:30:00-08:00"],
)
def test_the_timestamp_is_utc_whatever_it_arrived_as(arrived_as: str) -> None:
    # `timestamptz` comes back from the driver in the session's time zone, so an
    # API process not set to UTC would otherwise put that offset on the wire.
    emitted = json.loads(
        AuditLogEntry.model_validate(an_entry_body(created_at=arrived_as)).model_dump_json()
    )

    assert UTC_TIMESTAMP.match(emitted["created_at"]), emitted["created_at"]
    assert datetime.fromisoformat(emitted["created_at"]) == datetime.fromisoformat(arrived_as)


def test_a_serialized_entry_satisfies_every_rule_the_twin_checks() -> None:
    # The round trip the key-set tests never make: what this model actually
    # emits, against the value rules `isAuditLogEntry` applies to it.
    emitted = json.loads(AuditLogEntry.model_validate(an_entry_body()).model_dump_json())

    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

    assert set(emitted) == set(AuditLogEntry.model_fields)
    assert re.match(uuid_pattern, emitted["id"])
    assert UTC_TIMESTAMP.match(emitted["created_at"])
    assert isinstance(emitted["action"], str)
    assert isinstance(emitted["details"], dict)
    for key in ("actor_user_id", "target_user_id"):
        assert emitted[key] is None or re.match(uuid_pattern, emitted[key])
    for key in ("actor_email", "target_email", "source_ip"):
        assert emitted[key] is None or isinstance(emitted[key], str)
