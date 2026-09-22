"""The `Tile` contract, and the twin that has to agree with it.

Written in `test_user.py`'s shape: the model's own rules, then the two halves
read against each other out of the TypeScript source, because nothing crosses
that boundary at build time and the only way to hold them together is for one
side to read the other's text.

Three claims here are not about keys at all and are the reason this file
exists: `Product` and `Face` appear nowhere (AD-18 retires them), no field
anywhere carries a similarity value (AD-20), and no field anywhere carries a
storage key or URL (AD-9). Each is an absence, and an absence is exactly what
a review stops noticing.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from shared_schema.tile import (
    MAX_BULK_ROWS,
    MAX_CODE_LENGTH,
    UNKNOWN_CATEGORY,
    ReferenceImage,
    Tile,
    clean_category,
    clean_code,
    clean_query,
    clean_size,
    face_number,
    normalize_label,
)

TS_TILE = Path(__file__).resolve().parents[1] / "shared_schema" / "ts" / "tile.ts"


def an_image_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "id": str(uuid4()),
        "width": 2048,
        "height": 1365,
        "featureless": False,
        "created_at": "2026-09-21T10:00:00Z",
    }
    body.update(overrides)
    return body


def a_tile_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "id": str(uuid4()),
        "code": "RP.CMA.0001DJ.SM.0T",
        "size": "45X90",
        "category": "CREMA MARMOL",
        "face_number": None,
        "reference_images": [an_image_body()],
        "created_at": "2026-09-21T10:00:00Z",
        "updated_at": "2026-09-21T10:00:00Z",
    }
    body.update(overrides)
    return body


# --- Normalization ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("45X90", "45X90"),
        (" 45x90 ", "45X90"),
        ("Crema  Marmol", "CREMA MARMOL"),
        ("\tmono colour\nglossy ", "MONO COLOUR GLOSSY"),
    ],
)
def test_a_label_normalizes_to_one_stored_form(raw: str, expected: str) -> None:
    # The POC's `normalize_folder` rule, and the one statement of it: two
    # writers resolving against the same create-if-missing lookup cannot drift
    # into near-duplicate rows nothing can join on.
    assert normalize_label(raw) == expected


def test_the_code_keeps_its_case_where_a_size_does_not() -> None:
    # The Code is a file name, cleaned. Uppercasing it the way a Size is
    # uppercased would turn `1Jk` into `1JK`, which is a different string from
    # the one on the tile — and the Code is the identity (AD-18).
    assert clean_code(" 1Jk ") == "1Jk"
    assert clean_size(" 45x90 ") == "45X90"


@pytest.mark.parametrize("value", ["", "   ", "x" * (MAX_CODE_LENGTH + 1), "with\x00nul"])
def test_a_code_the_product_will_not_store_is_refused(value: str) -> None:
    with pytest.raises(ValueError):
        clean_code(value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A blank query is the Catalogue screen's own first request: the screen
        # opens on the whole list and narrows from there (EXPERIENCE.md:35,
        # "Search/**browse** Tiles"). Refusing it the way `clean_code` refuses a
        # blank Code would make browsing an error.
        ("", ""),
        ("   ", ""),
        # Trimmed at the ends, and nowhere else: the real catalogue holds
        # `6LD.MA Quarry Stone Natural`, so an interior space is part of what
        # somebody may be searching for.
        ("  cma  ", "cma"),
        ("6LD.MA Quarry", "6LD.MA Quarry"),
        # A query as long as a Code may be is still a query.
        ("x" * MAX_CODE_LENGTH, "x" * MAX_CODE_LENGTH),
    ],
)
def test_a_query_is_trimmed_and_a_blank_one_browses(raw: str, expected: str) -> None:
    assert clean_query(raw) == expected


def test_a_query_is_never_case_folded() -> None:
    # Neither uppercased nor lowercased. The match is case-insensitive at the
    # database (FR-18), so folding here would be work that changes nothing —
    # and a function that returned `CMA` for `cma` would read as though the
    # stored Code had been folded too, which is the one thing `clean_code`
    # exists to say never happens (AD-18).
    assert clean_query("cma") == "cma"
    assert clean_query("CMA") == "CMA"
    assert clean_query("1Jk") == "1Jk"


@pytest.mark.parametrize(
    "value",
    [
        # One character over the bound, not ten: an off-by-one here is a `500`
        # from psycopg or a scan nothing needed, and only the boundary case
        # fails on it.
        "x" * (MAX_CODE_LENGTH + 1),
        # The case that would otherwise surface as a `500` rather than a `422`:
        # a C string cannot carry a NUL, so Postgres text cannot hold one and
        # psycopg raises before the statement is sent.
        "cma\x00",
        "\x00",
        "cma\x7f",
        "cma\nma",
    ],
)
def test_a_query_the_search_will_not_run_is_refused(value: str) -> None:
    with pytest.raises(ValueError):
        clean_query(value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_absent_category_becomes_the_sentinel_rather_than_a_refusal(
    value: str | None,
) -> None:
    # AD-18: a Tile with no recoverable Category is indexed under an explicit
    # unknown marker and flagged for follow-up. Dropping it would remove a real
    # tile over a grouping attribute that is not its identity.
    assert clean_category(value) == UNKNOWN_CATEGORY


# --- The trailing number (a hint, never an identity) ---------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        # The five naming conventions that genuinely coexist in the real Drive
        # tree, in the spellings `poc/tests/test_catalog.py` pinned them from —
        # the POC read them off the actual files, so these are examples and not
        # invented cases.
        ("RP.CMA.0008DJ.SM.0T", "8"),  # structured code, number as a segment
        ("77DH.MA_F3", "3"),  # underscore-F suffix
        ("1Jk", "1"),  # bare leading number
        ("61M", "61"),
        ("279", "279"),  # bare integer
        ("6LD.MA Quarry Stone Natural", "6"),  # free text trailing the code
    ],
)
def test_the_trailing_number_is_recovered_from_every_convention_that_carries_one(
    code: str, expected: str
) -> None:
    assert face_number(code) == expected


def test_a_code_with_no_recoverable_number_answers_none_rather_than_guessing() -> None:
    # The dash-delimited names carry four digit groups and no trailing number.
    # Returning `001` or `156` would put a number on screen that is not the
    # tile's — and the Code alone identifies the Tile anyway (AD-18), so the
    # honest answer is that there is nothing to show.
    assert face_number("RC-001-OHA-156-MA-J2") is None


def test_the_structured_rule_wins_over_the_leading_number_rule() -> None:
    # Ordering, asserted rather than assumed: the patterns are tried
    # most-specific-first, and a Code that both rules could read must be read
    # by the one written for it.
    assert face_number("RP.CMA.0008DJ.SM.0T") == "8"
    assert face_number("0008DJ") == "8"


def test_leading_zeros_go_and_an_all_zero_number_survives_as_zero() -> None:
    # `lstrip("0")` alone turns `0000` into the empty string, which renders as
    # a missing value rather than as the number it is.
    assert face_number("RP.CMA.0000DJ.SM.0T") == "0"


def test_the_row_cap_is_a_bound_the_two_writers_share() -> None:
    # `apps/api`'s bulk route refuses a longer manifest and the Bulk upload
    # screen refuses one before uploading it. A bound that existed on one side
    # only would be a batch travelling in full to be refused at the far end.
    assert MAX_BULK_ROWS > 0
    match = re.search(r"^export const MAX_BULK_ROWS = (\d+);$", _ts(), re.MULTILINE)
    assert match is not None, "MAX_BULK_ROWS is no longer an integer literal in tile.ts"
    assert int(match.group(1)) == MAX_BULK_ROWS


# --- The model ----------------------------------------------------------------


def test_a_tile_round_trips() -> None:
    tile = Tile.model_validate(a_tile_body())

    assert tile.code == "RP.CMA.0001DJ.SM.0T"
    assert tile.reference_images[0].width == 2048


def test_the_shape_is_closed() -> None:
    # An extra key must be a loud failure, not a quiet drop: a `score` or a
    # `source_key` added by a later change has to fail here rather than arrive
    # on the wire (AD-9, AD-20).
    with pytest.raises(ValidationError):
        Tile.model_validate(a_tile_body(score=0.918))
    with pytest.raises(ValidationError):
        ReferenceImage.model_validate(an_image_body(source_key="tiles/x/y/source.jpg"))


def test_a_naive_timestamp_is_refused_and_a_serialized_one_is_utc() -> None:
    with pytest.raises(ValidationError):
        Tile.model_validate(a_tile_body(created_at="2026-09-21T10:00:00"))

    tile = Tile.model_validate(
        a_tile_body(created_at=datetime(2026, 9, 21, 15, 30, tzinfo=UTC).astimezone())
    )
    assert tile.model_dump(mode="json")["created_at"].endswith("+00:00")


def test_the_category_may_be_null_and_the_face_number_is_only_ever_a_hint() -> None:
    tile = Tile.model_validate(a_tile_body(category=None, face_number="3"))

    assert tile.category is None
    assert tile.face_number == "3"


# --- The two halves -----------------------------------------------------------


def _ts() -> str:
    return TS_TILE.read_text(encoding="utf-8")


def _interface(name: str) -> set[str]:
    match = re.search(rf"export interface {name} \{{(.*?)\n\}}", _ts(), re.DOTALL)
    assert match is not None, f"the {name} interface is no longer declared in tile.ts"
    return set(re.findall(r"^  (\w+):", match.group(1), re.MULTILINE))


@pytest.mark.parametrize(("model", "name"), [(Tile, "Tile"), (ReferenceImage, "ReferenceImage")])
def test_the_typescript_interface_declares_every_python_field(model: Any, name: str) -> None:
    assert _interface(name) == set(model.model_fields)


def _key_array(name: str, seen: frozenset[str] = frozenset()) -> set[str]:
    """The string literals in a `const NAME = [...]`, following any spread.

    `seen` is not defensive tidiness: a mis-written pattern that failed to
    anchor on the closing bracket once matched an array containing a spread of
    itself, and the recursion took the whole file down with a `RecursionError`
    instead of reporting a bad pattern. A guard turns that into an assertion.

    Both array forms in `tile.ts` are accepted — `] as const;` for the narrow
    tuples the compiler checks against `keyof`, and `];` for the exported
    lists.
    """
    assert name not in seen, f"{name} refers to itself; the pattern below is wrong"
    match = re.search(rf"const {name}[^=]*=\s*\[(.*?)\]\s*(?:as const)?;", _ts(), re.DOTALL)
    assert match is not None, f"{name} is no longer a literal list in tile.ts"

    keys = set(re.findall(r"'([^']+)'", match.group(1)))
    for spread in re.findall(r"\.\.\.([A-Z_]+)", match.group(1)):
        keys |= _key_array(spread, seen | {name})
    return keys


@pytest.mark.parametrize(
    ("model", "array"),
    [(Tile, "TILE_CONTRACT_KEYS"), (ReferenceImage, "IMAGE_CONTRACT_KEYS")],
)
def test_the_narrowing_check_covers_every_python_field(model: Any, array: str) -> None:
    # `isTile` and `isReferenceImage` compare a sorted `Object.keys` against
    # these, so a field the Python model gained and the array did not is a body
    # the twin would reject outright.
    assert _key_array(array) == set(model.model_fields)


def test_the_sentinel_is_the_same_word_in_both_languages() -> None:
    match = re.search(r"^export const UNKNOWN_CATEGORY = '([^']+)';$", _ts(), re.MULTILINE)
    assert match is not None, "UNKNOWN_CATEGORY is no longer a literal string in tile.ts"

    assert match.group(1) == UNKNOWN_CATEGORY


# --- Three absences -----------------------------------------------------------


@pytest.mark.parametrize("retired", ["Product", "Face", "product", "face"])
def test_the_retired_words_appear_in_neither_half(retired: str) -> None:
    # AD-18 retires `Product` and `Face`: they encoded the identity model it
    # corrects, and a field or a type carrying either would reintroduce it by
    # vocabulary. `face_number` is the one permitted survivor — a nullable
    # display hint — so the scan is over declarations rather than over prose.
    python_names = set(Tile.model_fields) | set(ReferenceImage.model_fields)
    assert {name for name in python_names if retired.lower() in name.lower()} <= {"face_number"}

    declared = _interface("Tile") | _interface("ReferenceImage")
    assert {name for name in declared if retired.lower() in name.lower()} <= {"face_number"}


def test_no_field_can_carry_a_similarity_value() -> None:
    # AD-20: the score decides ranking and lives in the API's own logs; it
    # never reaches a screen. The way to keep that true is to give the contract
    # nowhere to put one.
    names = set(Tile.model_fields) | set(ReferenceImage.model_fields) | _interface("Tile")
    for forbidden in ("score", "similarity", "confidence", "rank", "distance"):
        assert not any(forbidden in name for name in names), forbidden


def test_no_field_can_carry_a_storage_reference() -> None:
    # AD-9: `apps/web` never receives a presigned or otherwise directly-usable
    # storage URL. The image is fetched through an authenticated endpoint built
    # from the ids, and the contract has no other handle to offer.
    names = (
        set(Tile.model_fields)
        | set(ReferenceImage.model_fields)
        | _interface("Tile")
        | _interface("ReferenceImage")
    )
    for forbidden in ("url", "key", "href", "src", "path", "bucket"):
        assert not any(forbidden in name for name in names), forbidden
