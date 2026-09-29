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


#: The window, in millimetres, the tile is looked for inside — a square of this
#: side centred on the marker. Wide enough for the largest plausible tile with
#: the marker anywhere on it, and no wider: every extra millimetre is warped
#: pixels nobody reads.
PROPOSAL_REACH_MM: Final = 3200.0

#: The plausible bounds on a tile edge. Narrower at the bottom than
#: `shared_schema.marker`'s size tolerance because this one is rejecting
#: *shapes*, not measurements: below the floor the candidate is the marker's
#: own paper, above the ceiling it is the floor the tile is lying on.
MIN_TILE_EDGE_MM: Final = 250.0
MAX_TILE_EDGE_MM: Final = 1500.0

#: What a proposal falls back to when nothing is found: a square of this side,
#: centred on the marker, **in the marker's own plane** — so it arrives already
#: in perspective and a drag moves a corner along the tile rather than across
#: the screen.
FALLBACK_TILE_MM: Final = 600.0


def _rectify(
    image: np.ndarray, marker_corners: np.ndarray, width_mm: float, height_mm: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The rectified frame, the transform, and where the photograph reaches.

    One millimetre per pixel, so every threshold below is in millimetres and a
    question like "could this be a tile" is answerable rather than a guess
    about pixels at an unknown distance.
    """
    destination = np.array(
        [[0, 0], [width_mm, 0], [width_mm, height_mm], [0, height_mm]], dtype=np.float32
    )
    offset = np.array(
        [[1, 0, PROPOSAL_REACH_MM / 2], [0, 1, PROPOSAL_REACH_MM / 2], [0, 0, 1]],
        dtype=np.float32,
    )
    transform = offset @ cv2.getPerspectiveTransform(marker_corners.astype(np.float32), destination)
    side = int(PROPOSAL_REACH_MM)
    flat = cv2.warpPerspective(image, transform, (side, side))
    # Where the photograph actually reaches, in the same frame. Warping leaves
    # everything outside the source as a flat fill, and the boundary between
    # the two is the strongest straight edge in the rectified image — a
    # rectangle of a plausible size, containing the marker, that is never a
    # tile. Eroded, so a candidate merely *touching* that boundary is out too.
    covered = cv2.warpPerspective(np.full(image.shape[:2], 255, np.uint8), transform, (side, side))
    covered = cv2.erode(covered, np.ones((9, 9), np.uint8), iterations=2)
    return flat, transform, covered


def _plausible(quad_mm: np.ndarray, centre: np.ndarray, covered: np.ndarray) -> bool:
    """Whether a rectified quad could be the tile the marker is lying on.

    Three questions, and the first is the one that does the work: **the marker
    is on the tile**, so a candidate that does not contain it is the floor, a
    neighbouring sample, or a shoe. The other two ask whether it is a rectangle
    and whether it is a tile-sized one.
    """
    here = (float(centre[0]), float(centre[1]))
    if cv2.pointPolygonTest(quad_mm.astype(np.float32), here, False) < 0:
        return False

    # **Every corner inside the photograph's own reach.** See `_rectify`: the
    # boundary of the warped source is a confident rectangle of a plausible
    # size containing the marker, and it is never a tile.
    height, width = covered.shape[:2]
    for x, y in quad_mm:
        column, row = int(round(x)), int(round(y))
        if not (0 <= column < width and 0 <= row < height) or covered[row, column] == 0:
            return False

    ordered = order_corners(quad_mm)
    top, right, bottom, left = _edge_lengths(ordered)
    first = float(np.linalg.norm(ordered[2] - ordered[0]))
    second = float(np.linalg.norm(ordered[3] - ordered[1]))
    for a, b in ((top, bottom), (right, left), (first, second)):
        longest = max(a, b)
        if longest <= 0.0 or abs(a - b) / longest > RECTANGULARITY_TOLERANCE:
            return False

    short_mm, long_mm = sorted(((top + bottom) / 2.0, (right + left) / 2.0))
    return MIN_TILE_EDGE_MM <= short_mm and long_mm <= MAX_TILE_EDGE_MM


def _from_contours(flat: np.ndarray, centre: np.ndarray, covered: np.ndarray) -> np.ndarray | None:
    """The largest plausible 4-gon around the marker, from edges.

    Works when the tile has a visible outline. On a showroom floor it often
    does not: samples are butted against neighbours of near-identical tone, and
    the tile's own veining is a stronger edge than its boundary.
    """
    grey = cv2.bilateralFilter(cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY), 9, 60, 60)
    edges = cv2.morphologyEx(cv2.Canny(grey, 30, 110), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    best: tuple[float, np.ndarray] | None = None
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        approximated = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approximated) != QUAD_CORNERS or not cv2.isContourConvex(approximated):
            continue
        quad = approximated.reshape(QUAD_CORNERS, 2).astype(np.float64)
        if not _plausible(quad, centre, covered):
            continue
        area = abs(float(cv2.contourArea(quad.astype(np.float32))))
        if best is None or area > best[0]:
            best = (area, quad)
    return None if best is None else best[1]


def _from_surface(
    flat: np.ndarray, centre: np.ndarray, marker_mm: float, covered: np.ndarray
) -> np.ndarray | None:
    """The extent of the surface the marker is lying on, as a rectangle.

    Asks "which pixels are the same surface as the one under the marker"
    rather than "where is the outline", so a grout line or a shadow crossing
    the tile does not break it. `minAreaRect` returns a rectangle by
    construction, so there is no 4-gon approximation to fail.
    """
    lab = cv2.cvtColor(cv2.GaussianBlur(flat, (5, 5), 0), cv2.COLOR_BGR2LAB)
    pad = marker_mm * 0.75
    x0, y0 = int(centre[0] - pad), int(centre[1] - pad)
    x1, y1 = int(centre[0] + pad), int(centre[1] + pad)

    ring = np.zeros(lab.shape[:2], np.uint8)
    reach = int(marker_mm * 1.8)
    cv2.rectangle(ring, (x0 - reach, y0 - reach), (x1 + reach, y1 + reach), 255, -1)
    cv2.rectangle(ring, (x0, y0), (x1, y1), 0, -1)
    if cv2.countNonZero(ring) == 0:
        return None

    mean = np.array(cv2.mean(lab, mask=ring)[:3], np.float32)
    surface = (np.linalg.norm(lab.astype(np.float32) - mean, axis=2) < 26).astype(np.uint8) * 255
    cv2.rectangle(surface, (x0, y0), (x1, y1), 255, -1)
    surface = cv2.morphologyEx(surface, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    surface = cv2.morphologyEx(surface, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))

    count, labels = cv2.connectedComponents(surface)
    mine = labels[int(centre[1]), int(centre[0])]
    if count < 2 or mine == 0:
        return None
    contours, _ = cv2.findContours(
        (labels == mine).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    biggest = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(biggest)
    if rect[1][0] <= 0 or rect[1][1] <= 0:
        return None
    # A tile fills its own bounding rectangle; two samples merged across a
    # seam make an L and do not.
    if cv2.contourArea(biggest) / (rect[1][0] * rect[1][1]) < 0.85:
        return None
    quad = cv2.boxPoints(rect).astype(np.float64)
    return quad if _plausible(quad, centre, covered) else None


def propose_tile_quad(
    image: np.ndarray,
    marker_corners: np.ndarray,
    marker_width_mm: float,
    marker_height_mm: float,
) -> tuple[np.ndarray, bool]:
    """A starting quadrilateral for the tile, and whether it was really found.

    **Always returns four corners.** The caller is a screen with draggable
    handles, and a proposal it can adjust is more useful than an empty frame
    even when the detector found nothing — so a failure falls back to a
    `FALLBACK_TILE_MM` square centred on the marker, in the marker's plane, and
    says so with `False`.

    **Expect the fallback often.** Measured on real showroom photographs, both
    detectors below found nothing usable on 5 of 5: samples are laid against
    neighbours of near-identical tone, and the gradient across a tile's
    boundary (33-52) is no stronger than the variation within its own surface
    (38-67). There is no outline there to find, and no threshold recovers a
    signal that is absent. This is a convenience over the manual path, never a
    replacement for it — which is why nothing here decides a measurement and
    the corners it returns are the ones the staff member then moves.
    """
    marker_corners = np.asarray(marker_corners, dtype=np.float64).reshape(QUAD_CORNERS, 2)
    flat, transform, covered = _rectify(image, marker_corners, marker_width_mm, marker_height_mm)
    centre = np.array(
        [
            PROPOSAL_REACH_MM / 2 + marker_width_mm / 2,
            PROPOSAL_REACH_MM / 2 + marker_height_mm / 2,
        ]
    )

    found = _from_contours(flat, centre, covered)
    if found is None:
        found = _from_surface(flat, centre, max(marker_width_mm, marker_height_mm), covered)

    detected = found is not None
    if found is None:
        half = FALLBACK_TILE_MM / 2.0
        found = np.array(
            [
                [centre[0] - half, centre[1] - half],
                [centre[0] + half, centre[1] - half],
                [centre[0] + half, centre[1] + half],
                [centre[0] - half, centre[1] + half],
            ],
            dtype=np.float64,
        )

    back = np.linalg.inv(transform)
    projected = cv2.perspectiveTransform(found.reshape(1, QUAD_CORNERS, 2).astype(np.float32), back)
    return np.asarray(projected, dtype=np.float64).reshape(QUAD_CORNERS, 2), detected


def normalized_to_millimetres(
    marker_corners: np.ndarray,
    marker_width_mm: float,
    marker_height_mm: float,
    image_width: int,
    image_height: int,
) -> list[float]:
    """The homography from a **normalized** image point to millimetres, row-major.

    The same transform `measure_tile` solves, composed with the normalization
    the wire uses, so a screen holding four normalized corners can put a live
    measurement under the one being dragged instead of making somebody press
    Measure to find out whether they have it right yet.

    **A preview, and the server does not trust it back.** `POST /scans/measure`
    recomputes everything from the corners it is sent — including the
    rectangularity check that catches a marker out of plane — so a client that
    got this arithmetic wrong produces a wrong number on its own screen and
    never a wrong measurement in the product.

    No origin offset: the caller measures distances between transformed points
    and a translation cancels in every one of them.
    """
    marker_corners = np.asarray(marker_corners, dtype=np.float64).reshape(QUAD_CORNERS, 2)
    destination = np.array(
        [
            [0, 0],
            [marker_width_mm, 0],
            [marker_width_mm, marker_height_mm],
            [0, marker_height_mm],
        ],
        dtype=np.float32,
    )
    to_millimetres = cv2.getPerspectiveTransform(marker_corners.astype(np.float32), destination)
    # Normalized -> pixels is a scale, and it goes on the input side.
    scale = np.array(
        [[float(image_width), 0.0, 0.0], [0.0, float(image_height), 0.0], [0.0, 0.0, 1.0]]
    )
    return [float(value) for value in (to_millimetres @ scale).ravel()]
