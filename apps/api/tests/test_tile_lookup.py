"""`GET /admin/tiles/lookup` — an exact Code, one Tile, and nothing that is a search.

The route exists because Story 2.2 ships an Edit tile screen and the Catalogue
list that EXPERIENCE.md opens it from is Story 2.5's. Without a door the screen
would be unreachable; with a *search* this story would have built 2.5's surface
a story early, badly, and with no list to put it on.

So the whole claim of this file is a narrow one, and the second test is the one
that matters most: `?code=RP.CMA` finds nothing while `RP.CMA.0001DJ.SM.0T`
exists. A prefix or substring match here would answer one of several Tiles and
the Administrator would edit whichever row happened to sort first.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.tile import MAX_CODE_LENGTH, UNKNOWN_CATEGORY
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]

ADD_TILE = "/admin/tiles"
LOOKUP = "/admin/tiles/lookup"
LOGIN = "/auth/login"

CODE = "RP.CMA.0001DJ.SM.0T"

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


def add(client: TestClient, code: str = CODE, **fields: Any) -> Any:
    data = {"code": code, "size": "45X90", "category": "CREMA MARMOL", **fields}
    response = client.post(
        ADD_TILE,
        data=data,
        files=[("images", ("reference.jpg", an_image(), "image/jpeg"))],
    )
    assert response.status_code == 201, response.text
    return response.json()


@needs_model
def test_an_exact_code_finds_its_tile(client: TestClient, administrator: Any) -> None:
    created = add(client)

    response = client.get(LOOKUP, params={"code": CODE})

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["id"] == created["id"]
    assert body["code"] == CODE
    assert body["size"] == "45X90"
    assert body["category"] == "CREMA MARMOL"
    assert len(body["reference_images"]) == 1


@needs_model
def test_a_prefix_of_a_real_code_finds_nothing(client: TestClient, administrator: Any) -> None:
    # The line between this route and Story 2.5. Substring matching is the
    # catalogue search's job; here a partial Code names no Tile, and answering
    # one anyway would hand the Administrator whichever row sorted first to
    # edit.
    add(client)

    for partial in ("RP.CMA", "RP.CMA.0001DJ.SM.0", "0001DJ", "rp.cma.0001dj.sm.0t"):
        response = client.get(LOOKUP, params={"code": partial})

        assert response.status_code == 404, partial
        assert response.json()["error"]["code"] == "tile_not_found", partial


@needs_model
def test_the_code_is_trimmed_but_never_case_folded(client: TestClient, administrator: Any) -> None:
    # `clean_code` is the one statement of the rule, and both halves matter: a
    # Code pasted with a trailing space must not miss by a character nobody can
    # see, and `1Jk` is not `1JK` (AD-18) — the case is part of the file name.
    add(client, code="1Jk")

    assert client.get(LOOKUP, params={"code": "  1Jk  "}).status_code == 200
    assert client.get(LOOKUP, params={"code": "1JK"}).status_code == 404


@needs_model
def test_a_code_carrying_a_space_is_found_through_it(
    client: TestClient, administrator: Any
) -> None:
    """The real catalogue's fifth naming convention, on the wire.

    `Copy of 6LD.MA Quarry Stone Natural.jpg` is a real file, so a Code with a
    space in it is an ordinary Code here — and the one character that a query
    string does not carry verbatim. The screen sends this through
    `URLSearchParams` for exactly this reason; nothing pinned that the route can
    read it back, on either side.
    """
    spaced = "6LD.MA Quarry Stone Natural"
    created = add(client, code=spaced)

    response = client.get(LOOKUP, params={"code": spaced})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == created["id"]
    assert body["code"] == spaced
    # Trimmed at the ends and nowhere else: the interior space is part of the
    # Code, and collapsing it would make this Tile unreachable by its own name.
    assert client.get(LOOKUP, params={"code": f"  {spaced} "}).status_code == 200


def test_a_code_no_tile_holds_is_a_404(client: TestClient, administrator: Any) -> None:
    response = client.get(LOOKUP, params={"code": "NOTHING-HOLDS-THIS"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tile_not_found"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "params",
    [
        {"code": ""},
        {"code": "   "},
        {},
        # The other half of `clean_code`. The edit path tests the ceiling; on
        # this route only the blanks were driven, so an overlong Code could
        # have reached the generic handler with nobody noticing.
        {"code": "X" * (MAX_CODE_LENGTH + 1)},
    ],
)
def test_a_code_the_route_will_not_accept_is_refused_by_name(
    client: TestClient, administrator: Any, params: dict[str, str]
) -> None:
    # A named `422` rather than the generic `validation_error`, for the reason
    # every other code in this module has one: the generic handler names no
    # field, so the Administrator would be told nothing they can act on.
    response = client.get(LOOKUP, params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_code"


@needs_model
def test_the_body_is_the_same_closed_tile_shape_the_add_returns(
    client: TestClient, administrator: Any
) -> None:
    # AD-20 and AD-9 on this route too: the contract has no field for a score
    # or a storage reference, and this is what proves nothing put one there.
    created = add(client)

    body = client.get(LOOKUP, params={"code": CODE}).json()

    assert set(body) == set(created)
    assert set(body["reference_images"][0]) == set(created["reference_images"][0])
    rendered = str(body).lower()
    for forbidden in ("score", "similarity", "source_key", "derivative_key", "url", "http"):
        assert forbidden not in rendered, rendered


@needs_model
def test_a_tile_filed_under_the_sentinel_still_reads_back(
    client: TestClient, administrator: Any
) -> None:
    # AD-18: a Tile whose Category could not be recovered is grouped under
    # UNKNOWN, never dropped — and the lookup has to show it that way rather
    # than as an absence.
    add(client, category="")

    body = client.get(LOOKUP, params={"code": CODE}).json()

    assert body["category"] == UNKNOWN_CATEGORY


def _three_image_tile(client: TestClient) -> Any:
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
    return response.json()


@needs_model
def test_a_tile_with_several_images_lists_all_of_them(
    client: TestClient, administrator: Any
) -> None:
    created = _three_image_tile(client)

    body = client.get(LOOKUP, params={"code": CODE}).json()

    assert len(body["reference_images"]) == 3
    assert {image["id"] for image in body["reference_images"]} == {
        image["id"] for image in created["reference_images"]
    }


@needs_model
def test_the_images_come_back_in_a_stable_order(client: TestClient, administrator: Any) -> None:
    """`ORDER BY created_at, id` is the contract, not an accident of the plan.

    Without the clause Postgres is free to return the rows in whatever order the
    scan produced, and the Edit tile screen renders the thumbnails in exactly
    that order — so an Administrator who ticks "Remove" under the second picture
    and saves could be looking at a differently ordered list by then. Nothing
    else in the suite reads more than one image id out of a response, so
    deleting the clause is otherwise green.

    Asserted across two consecutive reads *and* against the edit's own answer,
    because one read can only ever agree with itself and the two routes have to
    agree with each other — they share `_SELECT_TILE_IMAGES` precisely so that
    they cannot show one Administrator two different orders for one tile.

    Deliberately **not** asserted against the add's own response. Three images
    added in one request share a `created_at` — `now()` is the transaction
    timestamp — so the tiebreak is the id, while the add answers in the order
    the parts arrived. That is a real difference and it is harmless: the add
    screen renders a count and no list, so this ordering is the only one any
    surface shows.
    """
    created = _three_image_tile(client)

    first = client.get(LOOKUP, params={"code": CODE}).json()
    second = client.get(LOOKUP, params={"code": CODE}).json()
    order = [image["id"] for image in first["reference_images"]]

    assert len(order) == 3
    assert [image["id"] for image in second["reference_images"]] == order

    edited = client.patch(f"{ADD_TILE}/{created['id']}", data={"size": "60X60"})
    assert edited.status_code == 200, edited.text
    assert [image["id"] for image in edited.json()["reference_images"]] == order

    # And a third read, after a write that touched the tile row, is still the
    # same order: an `UPDATE` must not be able to reshuffle the gallery.
    third = client.get(LOOKUP, params={"code": CODE}).json()
    assert [image["id"] for image in third["reference_images"]] == order
