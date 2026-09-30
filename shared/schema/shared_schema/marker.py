"""The `Marker` contract and the measurement it produces, shared by `apps/web` and `apps/api`.

A **Marker** is a physical object of known size that a staff member lays on a
tile before photographing it. It is the scale reference the photo itself cannot
carry: pixels alone say nothing about millimetres (see `CLAUDE.md`, "Source data
quirks" — size and finish are not recoverable from a photo), and a Marker of
known width and height in the same frame is what turns pixel distances into
physical ones.

**A Marker is reference data, not catalogue data.** It names no Tile, no Size
and no Category; it is a ruler. It lives in its own table and its own
Administrator surface for that reason, and nothing here may be joined to a
`Tile` — a Marker that "belonged to" a Size would be a second, silent identity
model of exactly the kind AD-18 retired.

**The measurement this produces is a suggestion, never an answer.** It lands on
the Scan screen's existing Size picker as a pre-filled value a staff member can
change or clear, and only their confirmed choice reaches `POST /scans` as
AD-19's hard pre-filter. That indirection is deliberate: AD-19 states that a
*mis*-declared Size makes the true Tile unreachable rather than merely
lower-ranked, and a measurement taken at a steep angle, or of a marker that
slipped, is exactly such a mis-declaration. Nothing in this module may be wired
straight into the search path.

`shared_schema/ts/marker.ts` is the TypeScript twin. The two files are one
contract in two languages and change together or not at all.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer

#: Bounds on a Marker's name. `tile.MAX_CODE_LENGTH`'s argument, applied to a
#: label a human types: generous, and about the column rather than about what a
#: sensible name looks like.
MAX_MARKER_NAME_LENGTH = 200

#: The physical bounds one Marker edge may declare, in millimetres.
#:
#: **Both ends are about arithmetic, not about taste.** Below the floor, a
#: marker spans so few pixels in a phone photo that one pixel of corner error
#: moves the derived scale by more than the 1.5x gap between `45X90` and
#: `60X30` — the one confusion this whole feature exists to break. Above the
#: ceiling, the "marker" is larger than every tile in the catalogue and is
#: almost certainly a typo of the kind that would silently scale every
#: measurement taken with it.
#:
#: Whole millimetres, as plain integers rather than floats, for the reason
#: `tile.MAX_IMAGE_BYTES` is written out rather than computed: `apps/web`
#: mirrors both onto the Register-a-marker form, and
#: `error-code-parity.test.ts` pins the two together by reading these lines as
#: integers. A `20.0` here would make that comparison compare against nothing.
#: Nothing is lost — `clean_edge_mm` returns a float either way, and a bound on
#: a tape measure has no business carrying a decimal.
MIN_MARKER_EDGE_MM = 20
MAX_MARKER_EDGE_MM = 1000

#: How far a measured edge may sit from a catalogue Size and still be called
#: that Size.
#:
#: **The number follows from the catalogue, not from a feeling about accuracy.**
#: The closest pair the real tree holds is `45X90` (450x900) against `60X30`
#: (600x300) — the long edges are 900 and 600, exactly 1.5x apart, and every
#: other pair is further apart than that or already separated by aspect ratio.
#: Splitting that pair at its geometric mean (735mm) tolerates +22% on the
#: smaller and -18% on the larger, so a tolerance below 18% can never confuse
#: the two. 15% keeps a margin under that and still absorbs the corner-tap
#: error a hand on a phone screen actually produces.
#:
#: A measurement that matches nothing within this band reports its millimetres
#: and matches no Size — it never snaps to the nearest one regardless of
#: distance, because a 300mm-out "nearest" is a wrong answer wearing a right
#: answer's clothes.
SIZE_MATCH_TOLERANCE = 0.15

#: The number of corners a quadrilateral has. Named because three call sites
#: check it and `4` alone at a validation site reads as a magic number.
QUAD_CORNERS = 4

_WHITESPACE = re.compile(r"\s+")

#: `<W>X<H>` as `tile.clean_size` normalizes it — the only Size spelling the
#: catalogue stores, and therefore the only one a measurement can be compared
#: against. Both groups are read as **centimetres**, which is what the folder
#: names in the source tree mean: `45X90` is a 450x900mm tile.
_SIZE_PATTERN = re.compile(r"^(\d{1,3})X(\d{1,3})$")


class ArucoDictionary(StrEnum):
    """The fiducial families a Marker may declare.

    **Four, and deliberately not every family OpenCV ships.** Each entry here
    is a printed card an Administrator has to produce and a staff member has to
    carry, and each additional family is another way for two Rocell sites to
    print incompatible cards that both "work". The detector is asked for
    exactly the family a Marker names, so a wider list would also mean a slower
    detection pass over families nobody uses.

    `DICT_4X4_50` is the default an Administrator should pick unless they have
    a reason not to: the largest cells, so the most robust detection at the
    small on-screen size a card occupies in a tile photo.
    """

    DICT_4X4_50 = "DICT_4X4_50"
    DICT_5X5_100 = "DICT_5X5_100"
    DICT_6X6_250 = "DICT_6X6_250"
    DICT_APRILTAG_36H11 = "DICT_APRILTAG_36h11"


#: How many distinct ids each family carries, and therefore the exclusive upper
#: bound on a Marker's `aruco_id`.
#:
#: Written here rather than read from `cv2` at import time on purpose:
#: `shared-schema` has no OpenCV dependency and must not gain one — it is the
#: contract `apps/web` compiles against through its twin, and a validation rule
#: that only holds where a 53MB native wheel is installed is not a contract.
#: `apps/api/tests/test_marker_dictionaries.py` asserts these against the real
#: `cv2` so the two can never drift.
ARUCO_DICTIONARY_SIZES: dict[ArucoDictionary, int] = {
    ArucoDictionary.DICT_4X4_50: 50,
    ArucoDictionary.DICT_5X5_100: 100,
    ArucoDictionary.DICT_6X6_250: 250,
    ArucoDictionary.DICT_APRILTAG_36H11: 587,
}


def _has_control_character(value: str) -> bool:
    """Whether `value` holds a character Postgres text cannot carry or display.

    `tile._has_control_character`, for its reason: a C string cannot carry a
    NUL, so psycopg raises rather than sending it, and that raise would escape
    as a `500` where every other refused field gets a `422`.
    """
    return any(character < " " or character == "\x7f" for character in value)


def clean_marker_name(value: str) -> str:
    """The Marker name as it will be stored, or a `ValueError` naming the rule.

    Trimmed and internally collapsed, **not uppercased**. A Size is uppercased
    because it is an identifier the catalogue joins on; this is a label a human
    reads off a picker ("Rocell ID badge"), and shouting it would make the one
    screen it appears on harder to scan, not easier.
    """
    normalized = _WHITESPACE.sub(" ", value).strip()
    if not normalized:
        raise ValueError("A marker name must not be blank.")
    if len(normalized) > MAX_MARKER_NAME_LENGTH:
        raise ValueError(f"A marker name must be at most {MAX_MARKER_NAME_LENGTH} characters.")
    if _has_control_character(normalized):
        raise ValueError("A marker name must not contain control characters.")
    return normalized


def clean_edge_mm(value: float, edge: str) -> float:
    """One physical edge length, bounded, or a `ValueError` naming the rule.

    `edge` is the word the message uses ("width", "height") so an Administrator
    who mistyped one field is told which one, rather than being told that "a
    dimension" was wrong on a form holding two.
    """
    if not (value == value) or value in (float("inf"), float("-inf")):  # NaN or infinity
        raise ValueError(f"A marker {edge} must be a real number.")
    if value < MIN_MARKER_EDGE_MM or value > MAX_MARKER_EDGE_MM:
        raise ValueError(
            f"A marker {edge} must be between {MIN_MARKER_EDGE_MM:.0f}mm "
            f"and {MAX_MARKER_EDGE_MM:.0f}mm."
        )
    return float(value)


def size_dimensions_mm(size: str) -> tuple[float, float] | None:
    """`"45X90"` -> `(450.0, 900.0)` in millimetres, or `None` if unreadable.

    **`None` rather than a guess**, which is `tile.face_number`'s rule for the
    same reason: the catalogue's Sizes are free-ish text resolved through
    `tile_size`, and nothing guarantees a future row spells its dimensions the
    way the four in the real tree do. A Size this cannot read simply never
    matches a measurement — the millimetres are still reported, and the staff
    member still picks from the full list.

    The returned pair is **sorted short-edge-first**, so a comparison never has
    to know whether `60X30` or `30X60` was written.
    """
    found = _SIZE_PATTERN.match(size.strip().upper())
    if not found:
        return None
    first_cm, second_cm = int(found.group(1)), int(found.group(2))
    if first_cm <= 0 or second_cm <= 0:
        return None
    short_cm, long_cm = sorted((first_cm, second_cm))
    return float(short_cm * 10), float(long_cm * 10)


def match_size(
    short_mm: float, long_mm: float, sizes: list[str], tolerance: float = SIZE_MATCH_TOLERANCE
) -> str | None:
    """The catalogue Size a measurement supports, or `None` when none is close enough.

    Both edges must land within `tolerance` of the candidate's, and among those
    that do the closest wins. Requiring **both** edges is what makes the check
    shape-aware for free: a 600x300 measurement cannot match `45X90` however
    the tolerance is set, because 300 is nowhere near 450.

    `None` is a first-class answer and the screen renders it as measured
    millimetres with no Size pre-filled. It is not an error, and it must never
    be turned into "the nearest Size anyway" — see `SIZE_MATCH_TOLERANCE`.
    """
    best: tuple[float, str] | None = None
    for size in sizes:
        dimensions = size_dimensions_mm(size)
        if dimensions is None:
            continue
        candidate_short, candidate_long = dimensions
        short_error = abs(short_mm - candidate_short) / candidate_short
        long_error = abs(long_mm - candidate_long) / candidate_long
        if short_error > tolerance or long_error > tolerance:
            continue
        combined = short_error + long_error
        if best is None or combined < best[0]:
            best = (combined, size)
    return None if best is None else best[1]


class Marker(BaseModel):
    """A physical scale reference, as the API renders it.

    Closed shape, for `User`'s reason: the TypeScript twin rejects a body
    carrying any key beyond the contract, and pydantic's default is to accept
    and silently discard.

    **`aruco_dictionary` and `aruco_id` are set together or not at all.** A
    Marker carrying both is detected automatically in the frame; a Marker
    carrying neither is a plain object of known size — a bank card, an ID badge
    — that only the manual corner-tap path can use. Both are legitimate, and the
    pairing is enforced by `validate_aruco_pair` at every write, because half a
    fiducial declaration is a card the detector will never find and nobody will
    be told why.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    #: The printed size of the marker itself, in millimetres. For a fiducial,
    #: this is the **black square's** outer edge, not the paper it sits on —
    #: the detector returns the black square's corners, and measuring to the
    #: paper would scale every result by the width of the quiet zone.
    width_mm: float
    height_mm: float
    aruco_dictionary: ArucoDictionary | None
    aruco_id: int | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_serializer("created_at", "updated_at", when_used="json")
    def _in_utc(self, value: datetime) -> str:
        """Emit every timestamp in UTC, whatever offset it arrived with.

        `user.User._in_utc`'s argument, unchanged: `timestamptz` comes back in
        the session's time zone and the twin's `isUtcTimestamp` accepts only a
        UTC designator.
        """
        return value.astimezone(UTC).isoformat()


def validate_aruco_pair(
    dictionary: ArucoDictionary | None, aruco_id: int | None
) -> tuple[ArucoDictionary | None, int | None]:
    """The fiducial declaration, both-or-neither, or a `ValueError`.

    The id is bounded by the declared family's own size: `DICT_4X4_50` holds
    ids 0-49, and a card printed with id 60 in that family does not exist. A
    Marker that declared one would be undetectable, and the Administrator would
    have no way to tell that from "the lighting was bad".
    """
    if dictionary is None and aruco_id is None:
        return None, None
    if dictionary is None or aruco_id is None:
        raise ValueError(
            "A marker needs both a fiducial dictionary and an id, or neither. "
            "Leave both empty for a plain object measured by tapping its corners."
        )
    limit = ARUCO_DICTIONARY_SIZES[dictionary]
    if aruco_id < 0 or aruco_id >= limit:
        raise ValueError(f"{dictionary} holds ids 0 to {limit - 1}.")
    return dictionary, aruco_id


class Point(BaseModel):
    """One corner, in **normalized image coordinates** — `0.0`-`1.0` on each axis.

    Normalized rather than absolute pixels, which is AD-11's rule for the scan
    crop and holds here for the same reason: the browser tapped these on a
    displayed image whose on-screen size is a property of the phone, not of the
    upload, and absolute pixels would silently mean different things on two
    devices. The server multiplies by the decoded frame's real dimensions.
    """

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class TileProposal(BaseModel):
    """Where the tile's four corners probably are — a starting point, not an answer.

    **Always four corners.** The screen that receives this draws draggable
    handles, and a shape to adjust beats an empty frame even when nothing was
    found: `detected` is `False` and the corners are a default rectangle in the
    marker's own plane, already in perspective, so a drag moves a handle along
    the tile rather than across the screen.

    **`detected` is honest about how often that happens.** On seven real
    showroom photographs the detectors find the tile on five; the two they
    miss are a cream tile on pale wood and a marble whose veining spans more
    tone than the gap to the floor, and neither has a boundary to find. The
    screen says which it got, because "we found your tile" and "here is a box
    to drag" are different claims and both happen.

    **Nothing here measures anything.** The corners a staff member confirms are
    what `POST /scans/measure` is then given; this only saves them starting
    from nothing.
    """

    model_config = ConfigDict(extra="forbid")

    #: Normalized 0-1 against the submitted image, in perimeter order —
    #: `Point`'s rule, for its reason.
    corners: list[Point]
    detected: bool
    #: Where the fiducial was found, normalized the same way.
    #:
    #: **Sent so the screen can draw it and a person can check it.** Everything
    #: downstream is scaled by this quadrilateral: if the detector locked onto
    #: something that is not the printed square, every millimetre it produces
    #: is wrong by that ratio and nothing else on the screen would show it.
    #: Drawing it turns an invisible assumption into one glance.
    marker: list[Point]
    #: The 3x3 homography taking a **normalized** image point to millimetres in
    #: the marker's plane, row-major.
    #:
    #: Sent so the screen can put a live measurement under a corner while it is
    #: being dragged, instead of making somebody press Measure to find out
    #: whether they have it right yet. It is a *preview*: `POST /scans/measure`
    #: remains the only thing that produces a measurement anyone acts on, and
    #: it recomputes from the corners it is given rather than trusting this.
    homography: list[float]


class Measurement(BaseModel):
    """What one measurement concluded.

    **Millimetres are reported and a Size is only suggested.** The two are not
    the same claim: the millimetres are what the geometry produced, and
    `matched_size` is `None` whenever nothing in the catalogue sits within
    `SIZE_MATCH_TOLERANCE` of them. A screen renders both, and the staff
    member's confirmed pick — not this — is what reaches `POST /scans`.

    **Physical millimetres are not AD-20's forbidden number.** AD-20 bans
    rendering a *similarity* score, because a cosine distance reads as
    confidence while carrying almost none. A measured edge length is an
    observation with a unit, it is falsifiable against a tape measure, and
    withholding it would leave a staff member unable to tell a good measurement
    from a marker that slipped.
    """

    model_config = ConfigDict(extra="forbid")

    #: Sorted short-edge-first, matching `size_dimensions_mm`, so a reader
    #: never has to know which way the tile was lying.
    short_mm: float
    long_mm: float
    #: The catalogue Size these millimetres support, or `None` when none is
    #: within tolerance. Never "the nearest one anyway".
    matched_size: str | None
    #: Whether the fiducial was found automatically, or the corners arrived
    #: from the manual fallback. Surfaced so a staff member can tell a detected
    #: measurement from one that depends on how carefully they tapped.
    auto_detected: bool
