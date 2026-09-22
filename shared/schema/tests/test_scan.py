"""The `ScanCandidate` contract, and the twin that has to agree with it.

Written in `test_tile.py`'s shape: the model's own rules, then the two halves
read against each other out of the TypeScript source, because nothing crosses
that boundary at build time and the only way to hold them together is for one
side to read the other's text.

Two absences are the reason this file exists as more than a round-trip check:
no field anywhere carries a similarity value (AD-20), and no field anywhere
carries a storage key or URL (AD-9). Each is an absence, and an absence is
exactly what a review stops noticing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from shared_schema.scan import ScanCandidate

TS_SCAN = Path(__file__).resolve().parents[1] / "shared_schema" / "ts" / "scan.ts"


def a_candidate_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "tile_id": str(uuid4()),
        "code": "RP.CMA.0001DJ.SM.0T",
        "size": "45X90",
        "category": "CREMA MARMOL",
        "image_id": str(uuid4()),
    }
    body.update(overrides)
    return body


# --- The model ------------------------------------------------------------


def test_a_candidate_round_trips() -> None:
    candidate = ScanCandidate.model_validate(a_candidate_body())

    assert candidate.code == "RP.CMA.0001DJ.SM.0T"
    assert candidate.size == "45X90"
    assert candidate.category == "CREMA MARMOL"


def test_the_shape_is_closed() -> None:
    # An extra key must be a loud failure, not a quiet drop: a `score` added
    # by a later change has to fail here rather than arrive on the wire
    # (AD-20).
    with pytest.raises(ValidationError):
        ScanCandidate.model_validate(a_candidate_body(score=0.918))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tile_id", "not-a-uuid"),
        ("tile_id", None),
        ("code", 123),
        ("code", None),
        ("size", 123),
        ("size", None),
        ("category", 123),
        ("image_id", "not-a-uuid"),
        ("image_id", None),
    ],
)
def test_a_wrong_typed_field_is_refused(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        ScanCandidate.model_validate(a_candidate_body(**{field: value}))


def test_the_category_may_be_null() -> None:
    candidate = ScanCandidate.model_validate(a_candidate_body(category=None))

    assert candidate.category is None


# --- The two halves ---------------------------------------------------------


def _ts() -> str:
    return TS_SCAN.read_text(encoding="utf-8")


def _interface(name: str) -> set[str]:
    match = re.search(rf"export interface {name} \{{(.*?)\n\}}", _ts(), re.DOTALL)
    assert match is not None, f"the {name} interface is no longer declared in scan.ts"
    return set(re.findall(r"^  (\w+):", match.group(1), re.MULTILINE))


def test_the_typescript_interface_declares_every_python_field() -> None:
    assert _interface("ScanCandidate") == set(ScanCandidate.model_fields)


def _key_array(name: str, seen: frozenset[str] = frozenset()) -> set[str]:
    """`test_tile.py`'s own reader, unchanged in shape. See that file."""
    assert name not in seen, f"{name} refers to itself; the pattern below is wrong"
    match = re.search(rf"const {name}[^=]*=\s*\[(.*?)\]\s*(?:as const)?;", _ts(), re.DOTALL)
    assert match is not None, f"{name} is no longer a literal list in scan.ts"

    keys = set(re.findall(r"'([^']+)'", match.group(1)))
    for spread in re.findall(r"\.\.\.([A-Z_]+)", match.group(1)):
        keys |= _key_array(spread, seen | {name})
    return keys


def test_the_narrowing_check_covers_every_python_field() -> None:
    # `isScanCandidate` compares a sorted `Object.keys` against this, so a
    # field the Python model gained and the array did not is a body the twin
    # would reject outright.
    assert _key_array("CANDIDATE_CONTRACT_KEYS") == set(ScanCandidate.model_fields)


# --- Two absences ------------------------------------------------------------


def test_no_field_can_carry_a_similarity_value() -> None:
    # AD-20: the score decides ranking and lives in the API's own logs; it
    # never reaches a screen. The way to keep that true is to give the
    # contract nowhere to put one.
    names = set(ScanCandidate.model_fields) | _interface("ScanCandidate")
    for forbidden in ("score", "similarity", "confidence", "rank", "distance"):
        assert not any(forbidden in name for name in names), forbidden


def test_no_field_can_carry_a_storage_reference() -> None:
    # AD-9: `apps/web` never receives a presigned or otherwise directly-usable
    # storage URL. The image is fetched through an authenticated endpoint
    # built from the ids, and the contract has no other handle to offer.
    names = set(ScanCandidate.model_fields) | _interface("ScanCandidate")
    for forbidden in ("url", "key", "href", "src", "path", "bucket"):
        assert not any(forbidden in name for name in names), forbidden
