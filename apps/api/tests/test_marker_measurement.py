"""`api.measure` — pixels to millimetres, and the refusals that keep it honest.

**No database and no app.** Every test here drives the geometry directly, by
projecting a known scene through a known homography and asking whether the
measured millimetres come back. That is the only way to test this: a real photo
has no ground truth attached, and a measurement that is silently 30% out looks
exactly like one that is right.

The scene is always the same and always real: a `60X30` tile (600x300mm) with a
bank card (85.60x53.98mm — ISO/IEC 7810 ID-1, the one every staff member is
already carrying) lying on it. The catalogue's own hardest pair is `45X90`
against `60X30`, which differ by exactly 1.5x, so the assertions below are
written against the tolerance that pair actually demands rather than a
comfortable one.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from api.measure import (
    MIN_MARKER_EDGE_PIXELS,
    DegenerateQuad,
    MarkerTooSmall,
    NotRectangular,
    detect_marker,
    measure_tile,
    order_corners,
)
from shared_schema.marker import ArucoDictionary, match_size

#: ISO/IEC 7810 ID-1 — a bank card, to the tenth of a millimetre.
CARD_WIDTH_MM = 85.60
CARD_HEIGHT_MM = 53.98

#: The tile under it, in millimetres: the catalogue's commonest Size.
TILE_SHORT_MM = 300.0
TILE_LONG_MM = 600.0

#: The tile's own corners on the physical plane, short edge vertical.
TILE_MM = np.array(
    [[0, 0], [TILE_LONG_MM, 0], [TILE_LONG_MM, TILE_SHORT_MM], [0, TILE_SHORT_MM]],
    dtype=np.float32,
)

#: Where the card lies on it — offset from the corner, so no edge is shared and
#: a bug that measured the card instead of the tile cannot coincidentally pass.
CARD_MM = np.array(
    [
        [250.0, 120.0],
        [250.0 + CARD_WIDTH_MM, 120.0],
        [250.0 + CARD_WIDTH_MM, 120.0 + CARD_HEIGHT_MM],
        [250.0, 120.0 + CARD_HEIGHT_MM],
    ],
    dtype=np.float32,
)

#: Three viewpoints, from a scan taken directly overhead to one taken at the
#: angle a person actually holds a phone at. Each is where the tile's four
#: corners land in the frame.
VIEWPOINTS = {
    "head-on": [[100, 100], [1300, 100], [1300, 700], [100, 700]],
    "oblique": [[180, 140], [1290, 95], [1360, 690], [105, 640]],
    "steep": [[300, 200], [1200, 120], [1390, 640], [150, 700]],
    # Photographed corner-first. This is the case the usual sum/difference
    # corner-ordering trick returns the same point twice for, which is why
    # `order_corners` sorts by angle instead.
    "diamond": [[700, 80], [1250, 450], [700, 820], [150, 450]],
}


def homography_for(viewpoint: str) -> np.ndarray:
    """The image projection that puts the tile where `viewpoint` says."""
    return cv2.getPerspectiveTransform(TILE_MM, np.array(VIEWPOINTS[viewpoint], dtype=np.float32))


def project(homography: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Physical millimetres to image pixels."""
    moved = cv2.perspectiveTransform(
        np.asarray(points, dtype=np.float32).reshape(1, -1, 2), homography
    )
    return np.asarray(moved, dtype=np.float64).reshape(-1, 2)


class TestMeasuresTheRealScene:
    @pytest.mark.parametrize("viewpoint", sorted(VIEWPOINTS))
    def test_recovers_the_tile_from_every_viewpoint(self, viewpoint: str) -> None:
        """The measurement is the geometry's, not the camera's.

        A homography is exact, so with exact corners the answer is exact from
        any viewpoint — including the corner-first one. Anything else here
        would mean the projection is being approximated somewhere.
        """
        homography = homography_for(viewpoint)
        short_mm, long_mm = measure_tile(
            project(homography, CARD_MM),
            CARD_WIDTH_MM,
            CARD_HEIGHT_MM,
            project(homography, TILE_MM),
            marker_oriented=True,
        )
        assert short_mm == pytest.approx(TILE_SHORT_MM, rel=1e-3)
        assert long_mm == pytest.approx(TILE_LONG_MM, rel=1e-3)

    def test_the_measurement_identifies_the_size(self) -> None:
        """The whole point, end to end: this tile is a `60X30` and not a `45X90`.

        Those two are the catalogue's hardest pair — both 2:1, so no amount of
        shape reasoning separates them, and only true millimetres can.
        """
        homography = homography_for("oblique")
        short_mm, long_mm = measure_tile(
            project(homography, CARD_MM),
            CARD_WIDTH_MM,
            CARD_HEIGHT_MM,
            project(homography, TILE_MM),
            marker_oriented=True,
        )
        assert match_size(short_mm, long_mm, ["30X90", "40X40", "45X90", "60X30"]) == "60X30"

    def test_tap_error_stays_far_inside_the_size_tolerance(self) -> None:
        """Two pixels of error on every tapped corner must not change the answer.

        The tolerance `match_size` runs at is 15%. This asserts the *measurement*
        spends only a small part of that budget, so the margin is left for the
        things a test cannot model — a card not quite flat, a lens that is not
        quite a pinhole.
        """
        homography = homography_for("oblique")
        card_px = project(homography, CARD_MM)
        tile_px = project(homography, TILE_MM)
        generator = np.random.default_rng(20260928)

        worst = 0.0
        for _ in range(200):
            jittered = tile_px + generator.normal(0.0, 2.0, tile_px.shape)
            short_mm, long_mm = measure_tile(
                card_px, CARD_WIDTH_MM, CARD_HEIGHT_MM, jittered, marker_oriented=True
            )
            worst = max(
                worst,
                abs(short_mm - TILE_SHORT_MM) / TILE_SHORT_MM,
                abs(long_mm - TILE_LONG_MM) / TILE_LONG_MM,
            )
        assert worst < 0.03


class TestTheManualPath:
    """Corners tapped by a thumb: any order, and a card lying any way round."""

    def test_tapped_corners_need_no_order(self) -> None:
        """`order_corners` is what lets the screen accept four taps as four taps.

        Requiring a staff member to tap clockwise from the top-left would be a
        rule nobody reads and everybody breaks, and breaking it silently
        produces a bow-tie rather than a rectangle.
        """
        homography = homography_for("oblique")
        card_px = project(homography, CARD_MM)
        tile_px = project(homography, TILE_MM)

        short_mm, long_mm = measure_tile(
            card_px[[3, 1, 2, 0]],
            CARD_WIDTH_MM,
            CARD_HEIGHT_MM,
            tile_px[[1, 3, 0, 2]],
            marker_oriented=False,
        )
        assert short_mm == pytest.approx(TILE_SHORT_MM, rel=1e-3)
        assert long_mm == pytest.approx(TILE_LONG_MM, rel=1e-3)

    def test_a_card_turned_sideways_still_measures(self) -> None:
        """The width/height assignment is recovered from the observed shape.

        Nothing tells the server which way the card was lying. Mapping the
        on-screen top edge to the printed width would transpose the scale, and
        a transposed scale does not fail — it returns a measurement wrong by
        the card's own aspect ratio, which is 1.59x and would turn a `60X30`
        into nothing the catalogue recognises.
        """
        homography = homography_for("oblique")
        turned = np.array(
            [
                [250.0, 100.0],
                [250.0 + CARD_HEIGHT_MM, 100.0],
                [250.0 + CARD_HEIGHT_MM, 100.0 + CARD_WIDTH_MM],
                [250.0, 100.0 + CARD_WIDTH_MM],
            ],
            dtype=np.float32,
        )
        short_mm, long_mm = measure_tile(
            project(homography, turned),
            CARD_WIDTH_MM,
            CARD_HEIGHT_MM,
            project(homography, TILE_MM),
            marker_oriented=False,
        )
        assert short_mm == pytest.approx(TILE_SHORT_MM, rel=1e-3)
        assert long_mm == pytest.approx(TILE_LONG_MM, rel=1e-3)

    def test_order_corners_survives_the_diamond(self) -> None:
        """The case the sum/difference trick gets wrong, asserted directly."""
        diamond = np.array([[700, 80], [1250, 450], [700, 820], [150, 450]], dtype=np.float64)
        ordered = order_corners(diamond[[2, 0, 3, 1]])
        assert len({tuple(corner) for corner in ordered}) == 4
        assert np.allclose(sorted(map(tuple, ordered)), sorted(map(tuple, diamond)))


class TestRefusesRatherThanGuessing:
    """Every refusal names a broken precondition — never a silently wrong number."""

    def test_a_marker_too_small_to_scale_from(self) -> None:
        """Below `MIN_MARKER_EDGE_PIXELS` one pixel of error swamps the answer."""
        homography = homography_for("head-on")
        tiny = np.array(
            [[250, 120], [262, 120], [262, 127.6], [250, 127.6]],
            dtype=np.float32,
        )
        with pytest.raises(MarkerTooSmall):
            measure_tile(
                project(homography, tiny),
                12.0,
                7.6,
                project(homography, TILE_MM),
                marker_oriented=True,
            )

    def test_a_marker_that_is_not_coplanar_with_the_tile(self) -> None:
        """The one physical assumption the method rests on, checked.

        A card propped up, or resting on the floor beside a tile held upright,
        breaks the single-plane premise a homography needs. There is no way to
        detect that directly — but a tile that rectifies into something that is
        not a rectangle is the symptom, and it is the symptom this catches.
        """
        homography = homography_for("oblique")
        sheared = np.array([[180, 140], [1290, 95], [900, 690], [105, 640]], dtype=np.float64)
        with pytest.raises(NotRectangular):
            measure_tile(
                project(homography, CARD_MM),
                CARD_WIDTH_MM,
                CARD_HEIGHT_MM,
                sheared,
                marker_oriented=True,
            )

    def test_four_points_that_bound_nothing(self) -> None:
        """Repeated or collinear taps have no area and no usable homography."""
        homography = homography_for("head-on")
        with pytest.raises(DegenerateQuad):
            measure_tile(
                project(homography, CARD_MM),
                CARD_WIDTH_MM,
                CARD_HEIGHT_MM,
                np.array([[10, 10], [10, 10], [20, 20], [30, 30]], dtype=np.float64),
                marker_oriented=True,
            )

    def test_the_pixel_floor_is_the_one_the_module_declares(self) -> None:
        """The bound is read from the module, so a change to it changes this test.

        A literal `60.0` here would keep passing after someone lowered the
        floor, which is the one thing this assertion exists to notice.
        """
        assert MIN_MARKER_EDGE_PIXELS >= 40.0


class TestFiducialDetection:
    """The automatic path, against images OpenCV itself generated."""

    @pytest.mark.parametrize("dictionary", list(ArucoDictionary))
    def test_a_printed_marker_is_found_in_every_family(self, dictionary: ArucoDictionary) -> None:
        """Round trip: generate the card this Marker declares, then find it.

        Parametrized over every family the contract offers, because each one is
        a card an Administrator can register and a staff member can print — a
        family that does not round-trip is a Marker that can never be measured
        with, and nobody would be told why.
        """
        from api.measure import _OPENCV_DICTIONARIES

        printed = cv2.aruco.generateImageMarker(
            cv2.aruco.getPredefinedDictionary(_OPENCV_DICTIONARIES[dictionary]), 7, 240
        )
        frame = np.full((600, 800), 255, dtype=np.uint8)
        frame[180:420, 280:520] = printed
        rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)

        corners = detect_marker(rgb, dictionary, 7)
        assert corners is not None
        assert corners.shape == (4, 2)
        # The detector's own corners, at the square's edges where it was drawn.
        assert corners[:, 0].min() == pytest.approx(280.0, abs=2.0)
        assert corners[:, 1].min() == pytest.approx(180.0, abs=2.0)

    def test_only_the_declared_id_is_returned(self) -> None:
        """A frame can hold more than one card. The wrong one must not be used.

        Scanning for "any marker" would scale the measurement by whichever one
        OpenCV happened to list first — a second card left on the bench, a
        poster on the wall — and the Marker the staff member picked names
        exactly one id.
        """
        from api.measure import _OPENCV_DICTIONARIES

        family = cv2.aruco.getPredefinedDictionary(
            _OPENCV_DICTIONARIES[ArucoDictionary.DICT_4X4_50]
        )
        frame = np.full((600, 900), 255, dtype=np.uint8)
        frame[180:420, 60:300] = cv2.aruco.generateImageMarker(family, 7, 240)
        frame[180:420, 560:800] = cv2.aruco.generateImageMarker(family, 11, 240)
        rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)

        wanted = detect_marker(rgb, ArucoDictionary.DICT_4X4_50, 11)
        assert wanted is not None
        # The one on the right, not the one the detector may well list first.
        assert wanted[:, 0].min() == pytest.approx(560.0, abs=2.0)

        assert detect_marker(rgb, ArucoDictionary.DICT_4X4_50, 23) is None

    def test_an_empty_frame_answers_none_rather_than_raising(self) -> None:
        """`None` is the signal the screen turns into "tap the corners instead".

        A raise here would make an absent, creased or glared-out card an error
        rather than the ordinary condition it is, and the manual fallback
        exists precisely for it.
        """
        blank = np.full((400, 400, 3), 255, dtype=np.uint8)
        assert detect_marker(blank, ArucoDictionary.DICT_4X4_50, 0) is None
