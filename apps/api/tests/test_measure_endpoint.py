"""`POST /scans/measure` — the staff-facing half of marker measurement.

`test_marker_measurement.py` drives the geometry directly against exact
corners. This file drives the **route**: a real JPEG of a real scene, through
intake, detection and the homography, to millimetres and a suggested Size — and
every refusal a staff member can actually hit.

The scene is rendered rather than photographed, because a photograph carries no
ground truth: a measurement that is silently 30% out looks exactly like one that
is right. A `60X30` tile is drawn at a known scale with a printed ArUco card
lying on it, and the whole thing is warped through a known homography into a
frame the way a phone held at an angle would see it.

**What this file is *not* asserting** is that a measurement narrows a search.
It cannot: the Size it suggests only ever pre-fills the Scan screen's picker,
and what reaches `POST /scans` is whatever the staff member then confirms
(AD-19).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
import psycopg
import pytest
import shared_vision
from api.scan import (
    INVALID_CORNERS,
    MARKER_NOT_DETECTED,
    MEASUREMENT_REFUSED,
    UNKNOWN_MARKER,
)
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.user import Role

LOGIN = "/auth/login"
MEASURE = "/scans/measure"
MARKERS = "/admin/markers"

#: The scene, in millimetres. A `60X30` tile — the catalogue's commonest Size —
#: with a 100mm square fiducial card lying on it, offset from the corner so no
#: edge is shared with the tile's.
TILE_WIDTH_MM, TILE_HEIGHT_MM = 600.0, 300.0
CARD_MM = 100.0
CARD_ORIGIN_MM = (250.0, 100.0)

#: How the world is drawn before it is warped: 2 pixels per millimetre, which
#: leaves the card ~240px across in the finished frame — comfortably above
#: `measure.MIN_MARKER_EDGE_PIXELS`, as a real photograph of it would be.
PIXELS_PER_MM = 2

FRAME_WIDTH, FRAME_HEIGHT = 1600, 900

#: Where the tile's four corners land in the frame: an oblique view, the angle
#: somebody actually holds a phone at rather than a copy-stand overhead shot.
VIEW = [[180, 140], [1420, 105], [1480, 780], [120, 720]]

ARUCO_ID = 7
FIDUCIAL_MARKER = {
    "name": "Rocell marker card",
    "width_mm": CARD_MM,
    "height_mm": CARD_MM,
    "aruco_dictionary": "DICT_4X4_50",
    "aruco_id": ARUCO_ID,
}
PLAIN_MARKER = {
    "name": "Bank card",
    "width_mm": 85.6,
    "height_mm": 53.98,
    "aruco_dictionary": None,
    "aruco_id": None,
}

MakeUser = Callable[..., Any]


def sign_in(client: TestClient, account: Any) -> None:
    assert (
        client.post(LOGIN, json={"email": account.email, "password": account.password}).status_code
        == 200
    )


def _homography() -> np.ndarray:
    """World pixels (2 per mm) to the frame, as `VIEW` places the tile."""
    world = np.array(
        [
            [0, 0],
            [TILE_WIDTH_MM * PIXELS_PER_MM, 0],
            [TILE_WIDTH_MM * PIXELS_PER_MM, TILE_HEIGHT_MM * PIXELS_PER_MM],
            [0, TILE_HEIGHT_MM * PIXELS_PER_MM],
        ],
        dtype=np.float32,
    )
    return cv2.getPerspectiveTransform(world, np.array(VIEW, dtype=np.float32))


def _scene(*, with_fiducial: bool = True) -> bytes:
    """One rendered photograph of the tile, as JPEG bytes.

    The tile is given a mottled texture rather than a flat fill: a flat frame
    compresses to almost nothing and is not what the detector meets in a
    showroom, and the surrounding floor is darker so the tile's own edges are
    real edges rather than a boundary only the test knows about.
    """
    world_w = int(TILE_WIDTH_MM * PIXELS_PER_MM)
    world_h = int(TILE_HEIGHT_MM * PIXELS_PER_MM)

    generator = np.random.default_rng(20260928)
    world = np.clip(generator.normal(190, 12, (world_h, world_w, 3)), 0, 255).astype(np.uint8)

    if with_fiducial:
        family = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        side = int(CARD_MM * PIXELS_PER_MM)
        printed = cv2.aruco.generateImageMarker(family, ARUCO_ID, side)
        left = int(CARD_ORIGIN_MM[0] * PIXELS_PER_MM)
        top = int(CARD_ORIGIN_MM[1] * PIXELS_PER_MM)
        world[top : top + side, left : left + side] = printed[:, :, None]

    frame = cv2.warpPerspective(
        world,
        _homography(),
        (FRAME_WIDTH, FRAME_HEIGHT),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(70, 70, 70),
    )

    buffer = io.BytesIO()
    Image.fromarray(frame).save(buffer, format="JPEG", quality=95, subsampling=0)
    return buffer.getvalue()


def _tile_corners() -> tuple[list[float], list[float]]:
    """The tile's corners as the screen would send them: normalized 0-1."""
    xs = [point[0] / FRAME_WIDTH for point in VIEW]
    ys = [point[1] / FRAME_HEIGHT for point in VIEW]
    return xs, ys


def _card_corners() -> tuple[list[float], list[float]]:
    """The card's corners, normalized — what the manual fallback would send."""
    left, top = CARD_ORIGIN_MM[0] * PIXELS_PER_MM, CARD_ORIGIN_MM[1] * PIXELS_PER_MM
    side = CARD_MM * PIXELS_PER_MM
    world = np.array(
        [[left, top], [left + side, top], [left + side, top + side], [left, top + side]],
        dtype=np.float32,
    ).reshape(1, 4, 2)
    moved = np.asarray(cv2.perspectiveTransform(world, _homography())).reshape(4, 2)
    return [float(p[0]) / FRAME_WIDTH for p in moved], [float(p[1]) / FRAME_HEIGHT for p in moved]


def post_measure(
    client: TestClient,
    marker_id: str,
    *,
    tile: tuple[list[float], list[float]] | None = None,
    card: tuple[list[float], list[float]] | None = None,
    image: bytes | None = None,
) -> Any:
    xs, ys = tile if tile is not None else _tile_corners()
    # A dict of *lists*, which is how httpx encodes a repeated multipart field
    # — the same shape `FormData.append` produces in the browser, and what
    # `Annotated[list[float], Form()]` reads. A list of `(name, value)` pairs
    # is silently not encoded as a body at all.
    data: dict[str, list[str]] = {
        "marker_id": [marker_id],
        "tile_x": [str(value) for value in xs],
        "tile_y": [str(value) for value in ys],
    }
    if card is not None:
        data["marker_x"] = [str(value) for value in card[0]]
        data["marker_y"] = [str(value) for value in card[1]]
    return client.post(
        MEASURE,
        data=data,
        files={"image": ("scene.jpg", image if image is not None else _scene(), "image/jpeg")},
    )


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    account = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    sign_in(client, account)
    return account


@pytest.fixture
def fiducial_id(client: TestClient, administrator: Any, make_user: MakeUser) -> str:
    """A registered fiducial card, with a *staff* session left signed in.

    Measuring is a staff act — `require_claimed_user`, not
    `require_administrator` — so every test below runs as one, and the
    Administrator exists only long enough to register the ruler.
    """
    marker_id: str = client.post(MARKERS, json=FIDUCIAL_MARKER).json()["id"]
    client.post(MARKERS, json=PLAIN_MARKER)
    client.post("/auth/logout")
    sign_in(client, make_user(role=Role.STAFF))
    return marker_id


def index_a_size(conn: psycopg.Connection, size: str) -> None:
    """Put one Tile of `size` into an active generation.

    Written as SQL rather than through `POST /admin/tiles` on purpose: that
    route runs the real ONNX embedding, which costs seconds and proves nothing
    this file is about. `indexed_sizes` reads the *index* rather than
    `tile_size`, so what it needs is a reference embedding in the active
    generation — and a zero vector is a perfectly good one for a query that
    never measures a distance.
    """
    size_id = conn.execute(
        "INSERT INTO tile_size (name) VALUES (%s) RETURNING id", (size,)
    ).fetchone()
    assert size_id is not None
    tile_id = conn.execute(
        "INSERT INTO tile (code, size_id) VALUES (%s, %s) RETURNING id",
        (f"CODE-{uuid4().hex[:8]}", size_id["id"]),
    ).fetchone()
    assert tile_id is not None
    image_id = conn.execute(
        """
        INSERT INTO reference_image
            (tile_id, source_key, derivative_key, sha256, width, height,
             source_bytes, derivative_bytes, pixel_std)
        VALUES (%s, 's', 'd', 'x', 10, 10, 1, 1, 50.0) RETURNING id
        """,
        (tile_id["id"],),
    ).fetchone()
    assert image_id is not None
    generation = conn.execute(
        """
        INSERT INTO embedding_generation (pipeline_version, config_hash, is_active)
        VALUES (%s, %s, true)
        ON CONFLICT (is_active) WHERE is_active DO NOTHING
        RETURNING id
        """,
        (shared_vision.PIPELINE_VERSION, shared_vision.config_hash()),
    ).fetchone()
    if generation is None:
        generation = conn.execute("SELECT id FROM embedding_generation WHERE is_active").fetchone()
    assert generation is not None
    conn.execute(
        """
        INSERT INTO reference_embedding
            (reference_image_id, generation_id, embedding, view_kind, view_index)
        VALUES (%s, %s, %s::vector, 'rotation', 0)
        """,
        (image_id["id"], generation["id"], "[" + ",".join(["0"] * 1536) + "]"),
    )


class TestMeasuringThroughTheRoute:
    def test_a_detected_card_measures_the_tile(self, client: TestClient, fiducial_id: str) -> None:
        """End to end: a rendered photograph in, millimetres out.

        The tolerance is 3%, not the geometry tests' 0.1%: the card here is
        found by the detector on JPEG-compressed pixels rather than supplied as
        exact corners, so this is the accuracy the *product* has rather than
        the accuracy the arithmetic has.
        """
        answer = post_measure(client, fiducial_id)

        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["auto_detected"] is True
        assert body["short_mm"] == pytest.approx(TILE_HEIGHT_MM, rel=0.03)
        assert body["long_mm"] == pytest.approx(TILE_WIDTH_MM, rel=0.03)

    def test_the_measurement_suggests_the_catalogue_size(
        self, client: TestClient, fiducial_id: str, conn: psycopg.Connection
    ) -> None:
        """The point of the whole feature, through the route that serves it."""
        index_a_size(conn, "60X30")

        assert post_measure(client, fiducial_id).json()["matched_size"] == "60X30"

    def test_a_size_the_index_cannot_answer_for_is_never_suggested(
        self, client: TestClient, fiducial_id: str, conn: psycopg.Connection
    ) -> None:
        """Compared against the *index*, not `tile_size`.

        Suggesting a Size with no indexed Tile behind it would pre-fill a
        filter that can only ever return nothing.
        """
        index_a_size(conn, "45X90")

        answer = post_measure(client, fiducial_id).json()
        # The millimetres are still reported — only the suggestion is withheld.
        assert answer["matched_size"] is None
        assert answer["long_mm"] == pytest.approx(TILE_WIDTH_MM, rel=0.03)

    def test_tapped_card_corners_measure_the_same_tile(
        self, client: TestClient, fiducial_id: str
    ) -> None:
        """The manual path, and `auto_detected` says which one ran.

        Surfaced because a tapped measurement is only as good as the taps, and
        the staff member is the only one who knows how carefully they placed
        them.
        """
        answer = post_measure(client, fiducial_id, card=_card_corners())

        assert answer.status_code == 200, answer.text
        assert answer.json()["auto_detected"] is False
        assert answer.json()["long_mm"] == pytest.approx(TILE_WIDTH_MM, rel=0.03)

    def test_a_plain_marker_measures_through_tapped_corners(
        self, client: TestClient, administrator: Any, make_user: MakeUser
    ) -> None:
        """A bank card has no fiducial. Tapping is the only path it has."""
        plain_id = client.post(MARKERS, json={**PLAIN_MARKER, "name": "Card two"}).json()["id"]
        client.post("/auth/logout")
        sign_in(client, make_user(role=Role.STAFF))

        # Measured as if the 100mm square card were an 85.6x53.98 bank card:
        # the answer is wrong, but the *route* is what is under test, and the
        # geometry's own accuracy is asserted in `test_marker_measurement.py`.
        answer = post_measure(client, plain_id, card=_card_corners())

        assert answer.status_code == 200, answer.text
        assert answer.json()["auto_detected"] is False


class TestRefusals:
    def test_an_unregistered_marker_is_refused(self, client: TestClient, fiducial_id: str) -> None:
        answer = post_measure(client, str(uuid4()))

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == UNKNOWN_MARKER

    @pytest.mark.parametrize(
        "corners",
        [
            ([0.1, 0.2, 0.3], [0.1, 0.2, 0.3]),
            ([0.1, 0.2, 0.3, 0.4, 0.5], [0.1, 0.2, 0.3, 0.4, 0.5]),
            ([0.1, 0.2, 0.3, 1.4], [0.1, 0.2, 0.3, 0.4]),
            ([0.1, 0.2, 0.3, -0.1], [0.1, 0.2, 0.3, 0.4]),
        ],
    )
    def test_corners_that_are_not_four_points_inside_the_image(
        self, client: TestClient, fiducial_id: str, corners: tuple[list[float], list[float]]
    ) -> None:
        """Three points, five points, and two outside the frame."""
        answer = post_measure(client, fiducial_id, tile=corners)

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == INVALID_CORNERS

    def test_an_absent_fiducial_asks_for_the_corners_instead(
        self, client: TestClient, fiducial_id: str
    ) -> None:
        """**The signal the screen acts on**, not a dead end.

        A creased card, a glare, a card outside the frame — all of them arrive
        here, and all of them are answered by offering the manual path rather
        than by failing the measurement.
        """
        answer = post_measure(client, fiducial_id, image=_scene(with_fiducial=False))

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == MARKER_NOT_DETECTED
        # The sentence has to say what to do next, because the screen renders
        # the API's own words.
        assert "corners" in answer.json()["error"]["message"]

    def test_a_marker_with_no_fiducial_and_no_taps_is_refused(
        self, client: TestClient, administrator: Any, make_user: MakeUser
    ) -> None:
        """A plain object has only the manual path, and the caller did not use it."""
        plain_id = client.post(MARKERS, json={**PLAIN_MARKER, "name": "Card three"}).json()["id"]
        client.post("/auth/logout")
        sign_in(client, make_user(role=Role.STAFF))

        answer = post_measure(client, plain_id)

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == MARKER_NOT_DETECTED

    def test_a_tile_that_does_not_rectify_as_a_rectangle_is_refused(
        self, client: TestClient, fiducial_id: str
    ) -> None:
        """The coplanarity premise, checked where it actually breaks.

        These corners are not the tile's — they describe a quadrilateral the
        marker's plane cannot map to a rectangle, which is what a card propped
        out of plane, or corners tapped onto the wrong object, produces.
        """
        skewed = ([0.11, 0.89, 0.56, 0.08], [0.16, 0.12, 0.87, 0.80])

        answer = post_measure(client, fiducial_id, tile=skewed)

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == MEASUREMENT_REFUSED

    def test_an_unreadable_upload_is_refused(self, client: TestClient, fiducial_id: str) -> None:
        answer = post_measure(client, fiducial_id, image=b"not a jpeg at all")

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == "unreadable_image"


class TestAuthorization:
    def test_a_signed_out_caller_is_refused(self, client: TestClient) -> None:
        answer = post_measure(client, str(uuid4()))

        assert answer.status_code == 401

    def test_staff_may_measure(self, client: TestClient, fiducial_id: str) -> None:
        """`require_claimed_user`, never `require_administrator`.

        Measuring is part of scanning and every claimed account scans. The
        Administrator boundary is on registering the ruler, not on using it —
        `test_admin_authorization.py`'s route-table guard holds both directions.
        """
        assert post_measure(client, fiducial_id).status_code == 200

    def test_staff_may_read_the_marker_list(self, client: TestClient, fiducial_id: str) -> None:
        answer = client.get("/scans/markers")

        assert answer.status_code == 200
        assert len(answer.json()) == 2
