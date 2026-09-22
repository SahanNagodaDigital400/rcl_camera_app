"""`GET /admin/tiles?q=` — FR-18's Catalogue, and the substring match that narrows it.

The whole claim of this file is the one `test_tile_lookup.py` is the mirror of:
`?q=CMA` answers *every* Tile whose Code contains `CMA`, in either case, while
`?code=CMA` answers `404`. Two routes, two questions, and the suite for each
exists so that neither quietly becomes the other.

Four properties get more attention here than their line count suggests:

**The pattern metacharacters.** `?q=%` and `?q=_` have to mean the characters,
and `?q=\\` has to mean a backslash rather than a malformed pattern Postgres
raises on. The escaping happens on the parameter (`catalogue._pattern`), and
nothing else in the suite would notice if it stopped: a search for `%` that
returned the whole Catalogue reads as a working search.

**Two Tiles of one range.** Two Codes differing only in their numeric segment,
under the same Size and the same Category, are two rows with two ids — never
merged, never deduplicated, never reported as a conflict (AD-18). An
implementation that grouped by `size + category` would answer one of them and
look tidy doing it.

**No audit entry, for any number of searches.** A read changes nothing, and
FR-20 covers changes; an entry per search would bury the entries the log exists
for.

**The statement's own text.** The behavioural tests here create a handful of
Tiles, so a `LIMIT` added later is invisible to every one of them — the suite
would stay green while "which tiles match" started answering "some of them".
This is `test_user_list.py`'s guard inverted: that statement must carry no
`WHERE`, and this one must.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any
from uuid import UUID

import numpy as np
import psycopg
import pytest
from api import catalogue
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.tile import MAX_CODE_LENGTH, UNKNOWN_CATEGORY
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]
AuditRows = Callable[[psycopg.Connection], list[dict[str, object]]]

ADD_TILE = "/admin/tiles"
SEARCH = "/admin/tiles"
LOGIN = "/auth/login"

#: `test_tile_lookup.py`'s own fixture Code, and its two siblings from the same
#: range: `45X90/CREMA MARMOL` really does hold several files whose Codes differ
#: only in the numeric segment, and those are different Tiles (AD-18).
CODE = "RP.CMA.0001DJ.SM.0T"
SIBLING = "RP.CMA.0011DJ.SM.0T"

#: The third and fourth naming conventions in the real tree — a bare face
#: number and a bare integer — here to prove the search is over the Code as
#: stored and carries no assumption about its shape.
BARE = "61M"

needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)


def an_image(seed: int = 4) -> bytes:
    rng = np.random.default_rng(seed)
    image = Image.fromarray(rng.integers(0, 255, (160, 160, 3), dtype=np.uint8), "RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    account = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200
    return account


def add(client: TestClient, code: str = CODE, seed: int = 4, **fields: Any) -> Any:
    """One Tile through the real add path. `test_tile_lookup.py`'s `add`.

    Every Tile in this file is created through `POST /admin/tiles` rather than
    inserted directly, for the reason that file gives: what the search has to
    find is what the write stores, and a fixture that wrote its own rows could
    agree with the search while both disagreed with the product.
    """
    data = {"code": code, "size": "45X90", "category": "CREMA MARMOL", **fields}
    response = client.post(
        ADD_TILE,
        data=data,
        files=[("images", ("reference.jpg", an_image(seed), "image/jpeg"))],
    )
    assert response.status_code == 201, response.text
    return response.json()


#: Seed a Tile with **no embedding**, for the checks that are about SQL rather
#: than about the pixel pipeline.
#:
#: Written out as two literal statements rather than reached through the route,
#: because the route runs sixteen forward passes per image and therefore needs
#: the ONNX artifact — which would put `@needs_model` on a test whose whole
#: claim is that Postgres treats an escaped `%` as a character. On a machine
#: without the artifact that test would skip and the claim would go unmade.
#:
#: `reference_image` is deliberately not written: a Tile with no image is a row
#: the search still has to answer (`_search_images` returns an empty list for
#: it), so leaving it out exercises that path for free.
_SEED_SIZE = """
INSERT INTO tile_size (name) VALUES (%s)
ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
RETURNING id
"""

_SEED_TILE = """
INSERT INTO tile (code, size_id) VALUES (%s, %s)
"""


def seed(conn: psycopg.Connection, code: str, size: str = "45X90") -> None:
    """One Tile row, straight into the table the route reads. See `_SEED_TILE`."""
    row = conn.execute(_SEED_SIZE, (size,)).fetchone()
    assert row is not None
    conn.execute(_SEED_TILE, (code, row["id"]))


def search(client: TestClient, **params: str) -> Any:
    response = client.get(SEARCH, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def codes(body: Any) -> list[str]:
    return [tile["code"] for tile in body]


# --- Matching -----------------------------------------------------------------


@needs_model
def test_a_fragment_finds_every_code_that_contains_it(
    client: TestClient, administrator: Any
) -> None:
    # FR-18: partial matches included, not just exact. The fragment sits in the
    # middle of the Code, which is the case an anchored `LIKE 'CMA%'` would
    # miss — and the one an Administrator who remembers the range but not the
    # whole file name actually types.
    add(client, CODE)
    add(client, SIBLING, seed=5)
    add(client, BARE, seed=6)

    body = search(client, q="CMA")

    assert codes(body) == [CODE, SIBLING]
    for tile in body:
        assert tile["size"] == "45X90"
        assert tile["category"] == "CREMA MARMOL"
        assert len(tile["reference_images"]) == 1


@needs_model
def test_the_match_folds_case_even_though_the_code_does_not(
    client: TestClient, administrator: Any
) -> None:
    # `clean_code` preserves case because the case is part of the identity
    # (AD-18); the *match* folds it because somebody typing a fragment into a
    # search box has no reason to reproduce it. Both halves are asserted, so a
    # change to either is visible.
    add(client, CODE)
    add(client, SIBLING, seed=5)

    for fragment in ("cma", "CMA", "cMa", "rp.cma"):
        assert codes(search(client, q=fragment)) == [CODE, SIBLING], fragment


@needs_model
def test_a_lowercase_code_is_found_by_an_uppercase_fragment(
    client: TestClient, administrator: Any
) -> None:
    # The other direction, and the one a naive `lower(code) LIKE %s` would get
    # right by accident while getting this wrong: the *stored* Code carries the
    # case, so folding has to happen on both sides of the comparison.
    add(client, "1Jk")

    assert codes(search(client, q="1jK")) == ["1Jk"]
    assert codes(search(client, q="1Jk")) == ["1Jk"]


@needs_model
def test_a_blank_query_browses_the_whole_catalogue(client: TestClient, administrator: Any) -> None:
    # EXPERIENCE.md:35 is "Search/**browse** Tiles". The screen opens on the
    # full list and narrows from there, so its own first request carries no
    # query at all — and an absent `q` and an empty one are the same request.
    add(client, CODE)
    add(client, SIBLING, seed=5)
    add(client, BARE, seed=6)

    ordered = [BARE, CODE, SIBLING]
    assert codes(search(client)) == ordered
    assert codes(search(client, q="")) == ordered
    assert codes(search(client, q="   ")) == ordered


@needs_model
def test_the_order_is_stable_across_reads_and_loses_no_row(
    client: TestClient, administrator: Any
) -> None:
    """The claim is **stability and completeness**, not a particular sequence.

    `ORDER BY t.code` orders by the *database's* collation, and this suite has
    no business asserting which one the cluster runs: `en_US.UTF-8` ignores
    punctuation at the primary level and folds case, while `C` compares code
    points, so `RP.CMA...`, `rp-cma...` and `61M` come back in different orders
    under the two and both are correct. An earlier version of this test
    asserted `first == sorted(first)` — Python's code-point order — which
    agreed only because every fixture Code was upper-case and free of
    punctuation, and would have failed on the mixed-case, dotted, spaced Codes
    the real tree actually holds.

    What the clause does buy, and what is asserted here, is that the order is
    **total** — the Code is the table's only unique non-opaque column, so
    nothing is left for the planner to decide — which means two reads paint the
    rows the same way and the Administrator who scrolls back up finds the row
    where they left it. Without the clause that is exactly what breaks, and it
    breaks non-deterministically. The clause's presence is pinned separately, in
    `test_the_search_is_a_filter_with_no_page_and_no_cap`.
    """
    wanted = [
        "RP.CMA.0003DJ.SM.0T",
        "rp.cma.0001dj.sm.0t",
        "6LD.MA Quarry Stone Natural",
        "61M",
        "279",
        "RC-001-OHA-156-MA-J2",
    ]
    for index, code in enumerate(wanted):
        add(client, code, seed=index + 7)

    first = codes(search(client))
    second = codes(search(client))

    assert sorted(first) == sorted(wanted)
    assert second == first
    # And the same order under a query that narrows it, since the clause is one
    # clause and not two.
    narrowed = codes(search(client, q="cma"))
    assert narrowed == [code for code in first if "cma" in code.lower()]
    assert codes(search(client, q="cma")) == narrowed


def test_a_query_nothing_matches_is_an_empty_array_and_never_a_404(
    client: TestClient, administrator: Any
) -> None:
    # "Nothing matches that fragment" is an answer. The lookup's `404` is for a
    # different question — an exact Code that names no Tile — and answering one
    # here would make the screen render a failure for a search that worked.
    response = client.get(SEARCH, params={"q": "ZZZZ"})

    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["cache-control"] == "no-store"


def test_an_empty_catalogue_browses_to_an_empty_array(
    client: TestClient, administrator: Any
) -> None:
    assert search(client) == []


# --- The pattern language stays out of the query ------------------------------


@needs_model
@pytest.mark.parametrize("metacharacter", ["%", "_", "\\", "%%", "\\%", "a%b", "_M"])
def test_a_pattern_metacharacter_is_matched_literally(
    client: TestClient, administrator: Any, metacharacter: str
) -> None:
    # Escaped on the parameter, never a wildcard. Without it `?q=%` is "every
    # tile" and `?q=_` is "every tile with at least one character" — a search
    # that looks like it worked and answers the whole Catalogue — and `?q=\`
    # is a malformed pattern Postgres raises on, which is a `500` behind a
    # character somebody can type by accident.
    add(client, CODE)
    add(client, SIBLING, seed=5)

    response = client.get(SEARCH, params={"q": metacharacter})

    assert response.status_code == 200, response.text
    assert response.json() == [], metacharacter


def test_a_metacharacter_matches_only_the_codes_that_hold_it(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    """The escaping, proved against Postgres, on a machine with no model.

    Every other metacharacter test here creates its Tiles through
    `POST /admin/tiles`, which embeds — so all of them carry `@needs_model`, and
    on a run without the ONNX artifact the only surviving coverage was the
    pure-string `_pattern(...)` assertion further down. That assertion shows
    Python builds `%\\%%`; it shows nothing about whether *Postgres* reads the
    backslash as an escape, which is the actual claim — `ILIKE` takes `\\` as
    its escape character by default and `_SEARCH_TILES` writes no `ESCAPE`
    clause, so if that default ever stopped holding the escaping would silently
    become decoration and `?q=%` would answer the whole Catalogue.

    Seeded through `conn` instead, so nothing is embedded and nothing skips.
    """
    seed(conn, "RP_CMA%0001")
    seed(conn, "RP.CMA.0001DJ.SM.0T")
    seed(conn, "61M")

    # Each metacharacter finds the one Code that really contains it, and not
    # the two that do not — which is the whole difference between an escaped
    # pattern and a wildcard.
    assert codes(search(client, q="%")) == ["RP_CMA%0001"]
    assert codes(search(client, q="_")) == ["RP_CMA%0001"]
    assert codes(search(client, q="_CMA%")) == ["RP_CMA%0001"]
    # And a lone backslash is a character nothing holds, rather than the
    # malformed pattern Postgres raises a `500` on.
    assert search(client, q="\\") == []
    # The control: the whole catalogue is three rows, so an unescaped `%` would
    # have answered three above rather than one.
    assert len(search(client)) == 3
    # A Tile with no reference image still comes back, with an empty list
    # rather than a `KeyError` from the grouping.
    [held] = search(client, q="RP_")
    assert held["reference_images"] == []


@needs_model
def test_a_code_that_really_holds_a_metacharacter_is_found_by_it(
    client: TestClient, administrator: Any
) -> None:
    # The other half, and the one that proves the escaping is escaping rather
    # than stripping: a Code containing the character is found by searching for
    # it, and its neighbours are not.
    held = "RP_CMA%0001"
    add(client, held)
    add(client, CODE, seed=5)

    assert codes(search(client, q="%")) == [held]
    assert codes(search(client, q="_CMA%")) == [held]
    assert codes(search(client, q=".")) == [CODE]


@needs_model
def test_a_code_carrying_a_space_is_found_through_it(
    client: TestClient, administrator: Any
) -> None:
    # `Copy of 6LD.MA Quarry Stone Natural.jpg` is a real file, so an interior
    # space is part of an ordinary Code — and it is the one character a query
    # string does not carry verbatim.
    spaced = "6LD.MA Quarry Stone Natural"
    add(client, spaced)

    assert codes(search(client, q="Quarry Stone")) == [spaced]
    # Trimmed at the ends and nowhere else, so the fragment still finds it.
    assert codes(search(client, q="  Quarry ")) == [spaced]


# --- Two Tiles of one range (AD-18) -------------------------------------------


@needs_model
def test_two_codes_from_one_range_are_two_rows_and_never_merged(
    client: TestClient, administrator: Any
) -> None:
    # The varying numeric segment distinguishes different Tiles, not faces of
    # one (AD-18). Grouping or deduplicating by `size + category` would answer
    # one of these and look tidy doing it — and would hide the correct answer
    # exactly half the time.
    first = add(client, CODE)
    second = add(client, SIBLING, seed=5)

    body = search(client, q="RP.CMA")

    assert len(body) == 2
    assert {tile["id"] for tile in body} == {first["id"], second["id"]}
    assert first["id"] != second["id"]
    assert {tile["size"] for tile in body} == {"45X90"}
    assert {tile["category"] for tile in body} == {"CREMA MARMOL"}


@needs_model
def test_a_tile_under_the_sentinel_category_is_listed_as_written(
    client: TestClient, administrator: Any
) -> None:
    # AD-18: a Tile whose Category could not be recovered is grouped under
    # UNKNOWN rather than dropped, and the list has to show it that way rather
    # than hide it or render it as an absence.
    add(client, CODE, category="")

    [tile] = search(client, q="CMA")

    assert tile["category"] == UNKNOWN_CATEGORY


@needs_model
def test_size_and_category_are_displayed_and_never_searched(
    client: TestClient, administrator: Any
) -> None:
    # The one query shape CLAUDE.md forbids outright. Both values are on every
    # row and neither is matchable: searching for the Size or the Category
    # finds nothing, because `q` is a substring of the **Code**.
    add(client, CODE)

    assert codes(search(client, q="45X90")) == []
    assert codes(search(client, q="CREMA")) == []
    [tile] = search(client, q="CMA")
    assert tile["size"] == "45X90"
    assert tile["category"] == "CREMA MARMOL"


# --- The rows the list carries ------------------------------------------------


@needs_model
def test_a_row_is_the_same_closed_tile_shape_the_add_returns(
    client: TestClient, administrator: Any
) -> None:
    # AD-9 and AD-20 on this route too: the contract has no field for a storage
    # reference or a similarity value, and this is what proves nothing put one
    # there. The list adds no field of its own either — `Tile` is
    # `extra="forbid"`, so a "matched" or "rank" key could not survive.
    created = add(client)

    [tile] = search(client, q="CMA")

    assert set(tile) == set(created)
    assert set(tile["reference_images"][0]) == set(created["reference_images"][0])
    rendered = str(tile).lower()
    for forbidden in ("score", "similarity", "source_key", "derivative_key", "url", "http"):
        assert forbidden not in rendered, rendered


@needs_model
def test_a_tile_with_several_images_carries_all_of_them_in_order(
    client: TestClient, administrator: Any
) -> None:
    # The grouping in Python, end to end. The screen renders the first image as
    # the row's thumbnail, so the order is what decides which picture an
    # Administrator sees — and it has to be the order the lookup gives for the
    # same Tile, since both are the same list of the same images.
    response = client.post(
        ADD_TILE,
        data={"code": CODE, "size": "45X90"},
        files=[
            ("images", ("a.jpg", an_image(1), "image/jpeg")),
            ("images", ("b.jpg", an_image(2), "image/jpeg")),
            ("images", ("c.jpg", an_image(3), "image/jpeg")),
        ],
    )
    assert response.status_code == 201, response.text

    [tile] = search(client, q="CMA")
    order = [image["id"] for image in tile["reference_images"]]

    assert len(order) == 3
    looked_up = client.get(f"{ADD_TILE}/lookup", params={"code": CODE}).json()
    assert [image["id"] for image in looked_up["reference_images"]] == order


@needs_model
def test_every_row_gets_its_own_images_and_no_other_row_s(
    client: TestClient, administrator: Any
) -> None:
    # One statement answers every row's images at once, so the grouping is the
    # thing that can go wrong: a key built from the wrong column would hand one
    # Tile another's picture, which on screen is a Code beside the wrong tile —
    # the one failure this surface exists to prevent.
    first = add(client, CODE)
    second = add(client, SIBLING, seed=5)

    body = search(client, q="RP.CMA")
    by_id = {tile["id"]: tile for tile in body}

    for created in (first, second):
        listed = by_id[created["id"]]
        assert [image["id"] for image in listed["reference_images"]] == [
            image["id"] for image in created["reference_images"]
        ]


# --- Immediately, and for real ------------------------------------------------


@needs_model
def test_a_tile_added_in_the_same_session_is_in_the_next_search(
    client: TestClient, administrator: Any
) -> None:
    # The epic's acceptance criterion on every write story, read from the list
    # side: no re-index step, no cache to clear, no ticket.
    assert search(client, q="CMA") == []

    created = add(client)

    [tile] = search(client, q="CMA")
    assert tile["id"] == created["id"]


@needs_model
def test_a_renamed_tile_is_found_under_its_new_code_and_not_its_old(
    client: TestClient, administrator: Any
) -> None:
    created = add(client)

    renamed = client.patch(f"{ADD_TILE}/{created['id']}", data={"code": "ASTORIA.0004"})
    assert renamed.status_code == 200, renamed.text

    assert codes(search(client, q="ASTORIA")) == ["ASTORIA.0004"]
    assert search(client, q="CMA") == []


@needs_model
def test_a_removed_tile_is_absent_from_every_later_search(
    client: TestClient, administrator: Any
) -> None:
    # Hard delete, so there is no soft-delete predicate for this call site to
    # forget (AD-5). Asserted against a blank query as well as a matching one:
    # browsing the whole Catalogue is the read most likely to surface a row a
    # filter was meant to hide.
    created = add(client)
    add(client, SIBLING, seed=5)

    removed = client.delete(f"{ADD_TILE}/{created['id']}")
    assert removed.status_code == 204, removed.text

    assert codes(search(client, q="CMA")) == [SIBLING]
    assert codes(search(client)) == [SIBLING]


# --- Refusals -----------------------------------------------------------------


@pytest.mark.parametrize(
    "q",
    [
        # One character over the bound. Refused rather than truncated: a query
        # silently cut short answers a different question from the one asked.
        "X" * (MAX_CODE_LENGTH + 1),
        # The case that would otherwise be a `500`. A C string cannot carry a
        # NUL, so Postgres text cannot hold one and psycopg raises before the
        # statement is sent.
        "CMA\x00",
        "\x00",
        "CMA\x7f",
    ],
)
def test_a_query_the_route_will_not_run_is_refused_by_name(
    client: TestClient, administrator: Any, q: str
) -> None:
    response = client.get(SEARCH, params={"q": q})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_query"
    assert set(response.json()) == {"error"}
    assert response.headers["cache-control"] == "no-store"


def test_the_refusal_names_the_rule_and_the_way_through(
    client: TestClient, administrator: Any
) -> None:
    # A code of its own rather than the generic `validation_error`, for the
    # reason every other code in `api.catalogue` has one: the generic handler
    # renders one sentence for every 422 in the product and names no field.
    # `clean_query` names the rule and `BAD_QUERY` names the fix, in that order.
    response = client.get(SEARCH, params={"q": "X" * (MAX_CODE_LENGTH + 1)})

    message = response.json()["error"]["message"]
    assert str(MAX_CODE_LENGTH) in message
    assert catalogue.BAD_QUERY in message


@needs_model
def test_a_refused_query_returns_no_row_at_all(client: TestClient, administrator: Any) -> None:
    add(client)

    response = client.get(SEARCH, params={"q": "CMA\x00"})

    assert response.status_code == 422
    assert CODE not in response.text


# --- A read changes nothing (FR-20) -------------------------------------------


@needs_model
def test_no_number_of_searches_writes_an_audit_entry(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    audit_rows: AuditRows,
) -> None:
    # `lookup_tile`'s own argument, on the route that will be called far more
    # often: an entry per search would bury the entries FR-20 exists for. The
    # add's entry is the control — it proves the log is reachable from this
    # test, so "no new entry" is a statement about the search and not about a
    # log nothing can write to.
    add(client)
    before = len(audit_rows(conn))
    assert before > 0

    for q in ("CMA", "", "ZZZZ", "%"):
        assert client.get(SEARCH, params={"q": q}).status_code == 200

    assert len(audit_rows(conn)) == before


# --- The grant, and the statements' own text ----------------------------------


@needs_model
def test_the_read_works_under_the_application_role_s_grant(
    client: TestClient, administrator: Any, app_role_conn: psycopg.Connection
) -> None:
    # `rocell_app` holds `SELECT` on all six catalogue tables from the
    # migration, so this story adds no DDL and no grant — and this is what says
    # so rather than the migration saying it about itself. Run through the
    # product's own pool constructor (see `conftest.app_role_conn`), so a test
    # that passed while the role option was dropped is not possible.
    created = add(client)

    rows = app_role_conn.execute(catalogue._SEARCH_TILES, (catalogue._pattern("CMA"),)).fetchall()

    assert [row["code"] for row in rows] == [CODE]
    images = catalogue._search_images(app_role_conn, [UUID(created["id"])])
    assert [str(image.id) for image in images[UUID(created["id"])]] == [
        created["reference_images"][0]["id"]
    ]


def _normalized(statement: str) -> str:
    return " ".join(statement.split())


def test_the_search_is_a_filter_with_no_page_and_no_cap() -> None:
    # `test_user_list.py`'s guard, inverted. That statement must carry no
    # `WHERE`; this one is the filter, so it must — and a `LIMIT` added later is
    # invisible to every behavioural test above, which never creates more than
    # three Tiles. The suite would stay green while "which tiles match" started
    # answering "some of them".
    #
    # `FETCH` is named beside `LIMIT` because `FETCH FIRST` is the standard
    # spelling of the same clause, and a guard that missed it would be a guard
    # against one way of writing the mistake.
    statement = _normalized(catalogue._SEARCH_TILES).upper()

    assert "WHERE" in statement
    assert "ILIKE" in statement
    assert "LIMIT" not in statement
    assert "OFFSET" not in statement
    assert "FETCH" not in statement
    assert "ORDER BY T.CODE" in statement


def test_the_pattern_is_the_parameter_and_never_the_statement() -> None:
    # One placeholder, and no interpolation of any kind.
    # `tests/test_source_guards.py` fails on a SQL verb sharing a line with an
    # f-string or a `+`; this is the positive statement of the same rule, and it
    # is what would fail if the `%`-wrapping ever moved into the text.
    written = _normalized(catalogue._SEARCH_TILES)

    assert written.count("%s") == 1
    assert "%(" not in written
    assert catalogue._pattern("CMA") == "%CMA%"
    # A blank query is a pattern matching everything, which is what makes
    # browsing need no second statement and no branch.
    assert catalogue._pattern("") == "%%"
    # And the three characters the pattern language owns come back escaped.
    assert catalogue._pattern("a%b_c\\d") == "%a\\%b\\_c\\\\d%"


def test_the_selected_columns_cover_the_contract_and_carry_no_storage_key() -> None:
    # Parsed from the module's own source rather than retyped: `Tile` is
    # `extra="forbid"`, so a column the contract does not carry fails
    # `model_validate` at run time — this fails it at collection time, and it is
    # also what says no storage key was ever selected (AD-9).
    written = _normalized(catalogue._SEARCH_TILES)

    for column in ("t.id", "t.code", "t.face_number", "t.created_at", "t.updated_at"):
        assert column in written, column
    assert "s.name AS size" in written
    assert "c.name AS category" in written
    for forbidden in ("source_key", "derivative_key", "embedding", "pixel_std"):
        assert forbidden not in written, forbidden


def test_the_images_statement_selects_its_grouping_key_and_orders_stably() -> None:
    # `tile_id` is what the grouping is keyed on and the one column
    # `_SELECT_TILE_IMAGES` does not select; the order has to match that
    # statement's `created_at, id` so one Tile's images read the same whether
    # they were reached from the Catalogue or from the lookup.
    written = _normalized(catalogue._SEARCH_TILE_IMAGES)

    assert "tile_id" in written
    assert "ORDER BY tile_id, created_at, id" in written
    assert "LIMIT" not in written.upper()
    for forbidden in ("source_key", "derivative_key", "sha256", "source_bytes"):
        assert forbidden not in written, forbidden


def test_the_exact_match_statement_was_not_widened_into_the_search() -> None:
    # The two live side by side and answer different questions. A prefix or
    # substring match on the lookup would hand the Edit tile screen whichever
    # row sorted first, which is the failure `test_tile_lookup.py` is about —
    # asserted here too, because this is the story that had a reason to widen
    # it.
    exact = _normalized(catalogue._SELECT_TILE_BY_CODE).upper()

    assert "WHERE T.CODE = %S" in exact
    assert "ILIKE" not in exact
    assert "LIKE" not in exact
