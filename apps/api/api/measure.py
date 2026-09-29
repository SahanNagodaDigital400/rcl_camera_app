"""Marker-based measurement — pixels to millimetres, and nothing else.

A staff member lays a **Marker** of known printed size on a tile, photographs
both together, and this module turns the two quadrilaterals in that frame into a
physical measurement of the tile.

**Why this is not in `shared/vision`.** AD-1 makes `shared/vision` the one
module both pipelines call, byte-for-byte identically, and a change to anything
in it invalidates the index and forces a re-index. Measurement is geometry over
the *uncropped* frame, it never embeds anything, and neither pipeline calls it.
Putting it there would widen the one module this repo may not fork, and would
make a tweak to a corner-ordering rule imply a catalogue rebuild. It lives here
instead: `api.measure` is a leaf, imported only by `api.scan`, and changing it
implies nothing about the index.

**The whole method rests on one physical assumption: the marker lies flat on
the tile.** A homography maps one plane to another, so marker and tile must be
the same plane. A marker propped on a box, or resting on the floor beside a
tile held upright, produces a confident and wrong answer. `_assert_rectangular`
below is the check that catches most of it — a real tile is a rectangle, so if
the rectified quad is not one, the premise was broken — but no check can catch
all of it, which is why the result pre-fills a picker rather than filtering a
search (AD-19).

Nothing here touches the database, the session, or the embedding. It takes
pixels and numbers and returns numbers.
"""

from __future__ import annotations

from typing import Final

import cv2
import numpy as np
from shared_schema.marker import QUAD_CORNERS, ArucoDictionary

#: The shortest edge, in pixels, a marker may span in the frame and still be
#: trusted.
#:
#: **Derived from the tolerance it has to serve, not chosen for feel.** The
#: scale this module produces is `marker_mm / marker_px`, so a corner located
#: `d` pixels off carries a relative scale error of about `d / marker_px`, and
#: that error multiplies straight through onto the tile. Two pixels of error —
#: a realistic fingertip on a phone screen, and about what the detector gives
#: on a soft-focus card — is 3.3% at 60px and 10% at 20px. The size match runs
#: at a 15% tolerance (`shared_schema.marker.SIZE_MATCH_TOLERANCE`), so 60px
#: keeps measurement error well inside it while 20px would spend most of the
#: budget before the tile is even measured.
MIN_MARKER_EDGE_PIXELS: Final = 60.0

#: How far a rectified tile quad may depart from a rectangle before the
#: measurement is refused.
#:
#: A tile *is* a rectangle. Once the homography has mapped the frame onto the
#: marker's physical plane, the tile's two pairs of opposite edges must come
#: back equal and its two diagonals must come back equal — that is what being a
#: rectangle means, and perspective has already been undone. They will not be
#: exactly equal (tapped corners, lens distortion, a marker a millimetre out of
#: plane), so the check is a tolerance rather than an equality.
#:
#: 20%, deliberately looser than the 15% size tolerance: this gate exists to
#: catch a *broken premise* — the marker not coplanar with the tile, corners
#: tapped onto the wrong object, a tile photographed across a corner — not to
#: enforce accuracy. Accuracy is the size tolerance's job, one step later, and a
#: gate tighter than that one would refuse measurements that would have matched
#: the right Size anyway.
RECTANGULARITY_TOLERANCE: Final = 0.20

#: `shared_schema` names the four families; this maps them onto the OpenCV
#: constants. Built at import rather than written as integers because the
#: numeric values are an OpenCV implementation detail that has changed between
#: major versions, and `apps/api/tests/test_marker_dictionaries.py` asserts the
#: id ranges in `shared_schema` against whatever `cv2` is actually installed.
_OPENCV_DICTIONARIES: Final[dict[ArucoDictionary, int]] = {
    ArucoDictionary.DICT_4X4_50: cv2.aruco.DICT_4X4_50,
    ArucoDictionary.DICT_5X5_100: cv2.aruco.DICT_5X5_100,
    ArucoDictionary.DICT_6X6_250: cv2.aruco.DICT_6X6_250,
    ArucoDictionary.DICT_APRILTAG_36H11: cv2.aruco.DICT_APRILTAG_36h11,
}


class MeasurementRefused(ValueError):
    """A measurement that could not be trusted. Never a silently wrong number.

    Every subclass below names a *specific* broken precondition, because the
    screen renders the API's own sentence and "measurement failed" tells a
    staff member nothing they can act on. "Move the marker closer" and "the
    marker must lie flat on the tile" are different instructions.
    """


class MarkerNotDetected(MeasurementRefused):
    """The declared fiducial was not found in the frame."""


class MarkerTooSmall(MeasurementRefused):
    """The marker was found but spans too few pixels to scale from."""


class DegenerateQuad(MeasurementRefused):
    """Four points that do not bound a usable area."""


class NotRectangular(MeasurementRefused):
    """The rectified tile is not a rectangle — the coplanarity premise broke."""


def detect_marker(
    image: np.ndarray, dictionary: ArucoDictionary, aruco_id: int
) -> np.ndarray | None:
    """The declared fiducial's four corners in pixels, or `None` if it is absent.

    `image` is RGB, as Pillow produces it. Detection runs on greyscale, which
    is what the detector wants anyway, and skips the RGB/BGR question entirely
    — a channel swap would silently halve detection on coloured card stock.

    **Only the declared id counts.** The detector returns every marker of the
    family it finds, and a frame can hold more than one — a second card left on
    the bench, a poster on the wall. Scanning for "any marker" would scale the
    measurement by whichever one OpenCV happened to list first. The Marker the
    staff member picked names exactly one id, and that is the one used.

    Corner order is the detector's own — the printed marker's top-left, then
    clockwise — and it is **relative to the marker's printed orientation**, not
    to the image. That is what makes the automatic path immune to the
    width/height ambiguity `order_corners` has to resolve by hand: a card
    photographed sideways still reports its own top-left first.
    """
    grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(_OPENCV_DICTIONARIES[dictionary]),
        cv2.aruco.DetectorParameters(),
    )
    corners, ids, _ = detector.detectMarkers(grey)
    if ids is None:
        return None
    for found, found_id in zip(corners, ids.ravel().tolist(), strict=True):
        if found_id == aruco_id:
            return np.asarray(found, dtype=np.float64).reshape(QUAD_CORNERS, 2)
    return None


def order_corners(points: np.ndarray) -> np.ndarray:
    """Four points, canonically ordered: top-left, then clockwise in image space.

    **For the manual path only.** The detector already reports its corners in
    the printed marker's own frame, and re-ordering those would discard the
    orientation information that makes the automatic path unambiguous.

    Sorted by angle about the centroid rather than by the sum/difference trick
    that is usually written for this. The trick picks corners by `x+y` and
    `x-y` extremes, which silently returns the same point twice for a quad
    rotated near 45 degrees — a tile photographed diamond-on, which is an
    ordinary thing to do. An angular sort is correct for any convex quad, and
    the roll afterwards fixes which corner is called first.

    Image coordinates run y-downward, so ascending `atan2` is clockwise on
    screen.
    """
    points = np.asarray(points, dtype=np.float64).reshape(QUAD_CORNERS, 2)
    centre = points.mean(axis=0)
    offsets = points - centre
    clockwise = points[np.argsort(np.arctan2(offsets[:, 1], offsets[:, 0]))]
    start = int(np.argmin(clockwise.sum(axis=1)))
    return np.roll(clockwise, -start, axis=0)


def _edge_lengths(quad: np.ndarray) -> tuple[float, float, float, float]:
    """The four side lengths of an ordered quad, walking its perimeter."""
    rolled = np.roll(quad, -1, axis=0)
    lengths = np.linalg.norm(rolled - quad, axis=1)
    return float(lengths[0]), float(lengths[1]), float(lengths[2]), float(lengths[3])


def _marker_destination(
    corners: np.ndarray, width_mm: float, height_mm: float, *, oriented: bool
) -> np.ndarray:
    """Where the marker's four corners sit on the physical plane, in millimetres.

    `oriented` is true for the detector's corners, which already arrive in the
    printed marker's own frame: the first corner *is* the marker's top-left, so
    the mapping is direct and no guessing is needed.

    For tapped corners it is false, and the width/height assignment has to be
    recovered. A non-square marker photographed sideways has its printed width
    running down the screen, and mapping the on-screen top edge to `width_mm`
    would transpose the scale — which does not fail, it just returns a
    measurement wrong by the marker's own aspect ratio.

    It is recovered from the observed shape: compare the ratio of the two
    on-screen edges against the printed ratio both ways round, and take the
    closer. Perspective distorts that ratio, but only mildly for a small card
    photographed roughly face-on, and the two candidates differ by the marker's
    full aspect ratio — so the comparison is decided by a wide margin for any
    marker that is not nearly square. For a square marker both candidates are
    identical and the choice does not matter.
    """
    if not oriented:
        top, right, _, _ = _edge_lengths(corners)
        if right > 0 and height_mm > 0:
            observed = top / right
            if abs(observed - width_mm / height_mm) > abs(observed - height_mm / width_mm):
                width_mm, height_mm = height_mm, width_mm
    return np.array(
        [[0.0, 0.0], [width_mm, 0.0], [width_mm, height_mm], [0.0, height_mm]],
        dtype=np.float64,
    )


def _assert_usable(quad: np.ndarray, what: str) -> None:
    """Refuse four points that do not bound a usable area.

    Two failures, one check. A quad with repeated or collinear points has no
    area and yields a singular homography; one that is self-intersecting (a
    bow-tie, from corners tapped in the wrong order) has area but describes no
    rectangle. `contourArea` on the ordered perimeter answers both: the
    degenerate case is zero, and the bow-tie's two lobes cancel toward zero.

    The floor is relative to the quad's own bounding box rather than absolute,
    so it means the same thing for a marker 80 pixels across and a tile
    spanning the frame.
    """
    area = abs(float(cv2.contourArea(quad.astype(np.float32))))
    spread = quad.max(axis=0) - quad.min(axis=0)
    bounding = float(spread[0] * spread[1])
    if bounding <= 0.0 or area < 0.10 * bounding:
        raise DegenerateQuad(
            f"The {what} corners do not form a usable shape. "
            "Tap the four corners in order around the edge."
        )


def _assert_rectangular(quad_mm: np.ndarray) -> None:
    """Refuse a rectified tile that is not a rectangle. See `RECTANGULARITY_TOLERANCE`.

    Both pairs of opposite edges and the two diagonals are compared, because
    the edge test alone passes a parallelogram: a marker lying on a surface at
    an angle to the tile shears the plane, and a sheared rectangle keeps its
    opposite edges equal while its diagonals diverge.
    """
    top, right, bottom, left = _edge_lengths(quad_mm)
    first = np.linalg.norm(quad_mm[2] - quad_mm[0])
    second = np.linalg.norm(quad_mm[3] - quad_mm[1])

    for a, b in ((top, bottom), (right, left), (float(first), float(second))):
        longest = max(a, b)
        if longest <= 0.0 or abs(a - b) / longest > RECTANGULARITY_TOLERANCE:
            raise NotRectangular(
                "That does not measure as a rectangle. The marker has to lie flat "
                "on the tile, in the same plane, with all four tile corners tapped."
            )


def measure_tile(
    marker_corners: np.ndarray,
    marker_width_mm: float,
    marker_height_mm: float,
    tile_corners: np.ndarray,
    *,
    marker_oriented: bool,
) -> tuple[float, float]:
    """The tile's two edge lengths in millimetres, short edge first.

    `marker_oriented` says whether `marker_corners` arrived from the detector
    (already in the printed marker's frame) or from taps — see
    `_marker_destination`.

    The sequence is four steps and each one can refuse:

    1. Both quads must bound a usable area (`_assert_usable`).
    2. The marker must span enough pixels for its scale to mean anything
       (`MIN_MARKER_EDGE_PIXELS`).
    3. The homography from image plane to the marker's physical plane is solved
       from exactly four correspondences — `getPerspectiveTransform`, not
       `findHomography`, because there is nothing to fit robustly and the RANSAC
       path would only add a way to silently drop a corner.
    4. The tile's corners are carried through it, and the result must be a
       rectangle (`_assert_rectangular`).

    Opposite edges are averaged rather than one of each pair being taken: both
    are measurements of the same physical edge, and the average halves the
    error of a single tapped corner.
    """
    # The detector's corners are already in the printed marker's own frame and
    # must not be touched — that ordering is what `_marker_destination` relies
    # on to skip the width/height guess. Tapped corners arrive in whatever
    # order a thumb produced them and have to be put in perimeter order first,
    # or every step below reads a bow-tie.
    marker_corners = (
        np.asarray(marker_corners, dtype=np.float64).reshape(QUAD_CORNERS, 2)
        if marker_oriented
        else order_corners(marker_corners)
    )
    tile_corners = order_corners(tile_corners)

    _assert_usable(marker_corners, "marker")
    _assert_usable(tile_corners, "tile")

    if min(_edge_lengths(marker_corners)) < MIN_MARKER_EDGE_PIXELS:
        raise MarkerTooSmall(
            "The marker is too small in the frame to measure from. "
            "Move closer, or use a larger marker."
        )

    destination = _marker_destination(
        marker_corners, marker_width_mm, marker_height_mm, oriented=marker_oriented
    )
    homography = cv2.getPerspectiveTransform(
        marker_corners.astype(np.float32), destination.astype(np.float32)
    )
    if homography is None or not np.all(np.isfinite(homography)):
        raise DegenerateQuad(
            "The marker corners do not describe a flat surface. Retake the photo "
            "with the whole marker visible."
        )

    projected = cv2.perspectiveTransform(
        tile_corners.reshape(1, QUAD_CORNERS, 2).astype(np.float32), homography
    )
    quad_mm = np.asarray(projected, dtype=np.float64).reshape(QUAD_CORNERS, 2)
    if not np.all(np.isfinite(quad_mm)):
        # A tile corner on the homography's horizon line projects to infinity.
        # Geometrically it is a corner the marker's plane cannot see, which in
        # practice means an extremely oblique photograph.
        raise NotRectangular(
            "That does not measure as a rectangle. Retake the photo looking "
            "more directly down at the tile."
        )

    _assert_rectangular(quad_mm)

    top, right, bottom, left = _edge_lengths(quad_mm)
    horizontal = (top + bottom) / 2.0
    vertical = (right + left) / 2.0
    short_mm, long_mm = sorted((horizontal, vertical))
    if short_mm <= 0.0:
        raise DegenerateQuad("The tile corners do not form a usable shape.")
    return short_mm, long_mm
