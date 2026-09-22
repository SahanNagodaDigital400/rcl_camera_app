"""AD-7's intake and AD-17's derivative, where the values are produced.

`apps/api/tests/test_add_tile.py` drives both through the real endpoint, which
proves they are wired up. This file asserts the two numbers they compute —
the quality flag and the derivative's encode floor — at the level that
computes them, because neither is observable from a fixture: a flag read back
out of a column is a value this code put there, and an inverted comparison or
a step past the floor would leave every one of those assertions green.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image
from shared_vision import intake


def jpeg(image: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def textured(seed: int = 5, size: tuple[int, int] = (320, 320)) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


# --- FR-19's quality flag, over real pixels -----------------------------------


def test_a_flat_reference_is_flagged_and_a_textured_one_is_not() -> None:
    """The comparison, asserted in the direction it is written.

    Inverting `std < FEATURELESS_STD` would report every plain tile as fine
    and every detailed one as unretrievable, and nothing that reads the stored
    value back could tell.
    """
    flat = intake.intake_image(jpeg(Image.new("RGB", (400, 400), (176, 176, 176))))
    detailed = intake.intake_image(jpeg(textured()))

    assert flat.pixel_std < intake.FEATURELESS_STD < detailed.pixel_std
    assert flat.featureless is True
    assert detailed.featureless is False


def test_the_flag_tracks_the_threshold_rather_than_the_other_way_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A threshold nothing reads is a constant, not a threshold. Raised above
    # the textured fixture's own deviation, the same image is flagged.
    detailed = intake.intake_image(jpeg(textured()))
    assert detailed.featureless is False

    monkeypatch.setattr(intake, "FEATURELESS_STD", detailed.pixel_std + 1)

    assert intake.intake_image(jpeg(textured())).featureless is True


def test_the_measure_is_the_deviation_of_the_whole_rgb_array() -> None:
    """What the ported measure actually is, written down where it is computed.

    The POC takes the standard deviation of the *whole* array, so the spread
    between a tile's channels counts towards it exactly as spatial texture
    does — a perfectly flat but coloured tile measures well above the
    threshold and is not flagged. That is the shipped behaviour and this
    asserts it rather than wishing otherwise; whether the measure should be
    per-channel is recorded as deferred work.
    """
    flat_but_coloured = intake.intake_image(jpeg(Image.new("RGB", (400, 400), (182, 176, 168))))

    assert flat_but_coloured.pixel_std > intake.FEATURELESS_STD
    assert flat_but_coloured.featureless is False


# --- AD-17's derivative -------------------------------------------------------


def _quality_of(data: bytes) -> int:
    """The quantization-table quality Pillow reads back out of a JPEG.

    Read from the file rather than inferred from its size: the claim is about
    what the encoder was asked for, and byte count varies with content.
    """
    with Image.open(io.BytesIO(data)) as encoded:
        tables = encoded.quantization
    # Pillow does not expose the quality setting, and a JPEG does not record
    # it — the quantization tables are what the setting produced. The
    # luminance table's first coefficient moves monotonically with quality,
    # which is all that is needed to compare two encodes of one image.
    return int(tables[0][0])


def test_the_derivative_is_capped_on_the_long_edge() -> None:
    big = textured(size=(3000, 1800))

    with Image.open(io.BytesIO(intake.display_derivative(big))) as view:
        assert max(view.size) == intake.DERIVATIVE_MAX_EDGE


def test_a_small_reference_is_not_enlarged() -> None:
    small = textured(size=(300, 200))

    with Image.open(io.BytesIO(intake.display_derivative(small))) as view:
        assert view.size == (300, 200)


def test_an_ordinary_reference_meets_the_byte_budget() -> None:
    # A flat-ish tile, which is what most of the catalogue is.
    ordinary = Image.new("RGB", (2048, 1400), (182, 176, 168))

    assert len(intake.display_derivative(ordinary)) <= intake.DERIVATIVE_MAX_BYTES


def test_nothing_is_ever_encoded_below_the_quality_floor() -> None:
    """The floor is a floor, not a step the loop walks past.

    Stepping 82 by 6 reaches 82, 76, 70, then **64** — below the 68 the
    constant and the docstring both promise — and the loop's exit test would
    then accept it. What that costs is the one thing the derivative exists
    for: a reference image a member of staff can recognise the tile from.

    Driven by making the budget unreachable, which is the only way the loop
    runs to its end at all.
    """
    incompressible = textured(seed=11, size=(1280, 1280))

    at_the_floor = _quality_of(intake.display_derivative(incompressible))
    # The same image encoded at each end of the range, as the yardstick: a
    # JPEG's quality is not recorded in the file, so the only honest
    # comparison is against encodes this test makes itself.
    expected = _quality_of(jpeg(incompressible, quality=intake.DERIVATIVE_MIN_QUALITY))
    one_step_below = _quality_of(
        jpeg(incompressible, quality=intake.DERIVATIVE_MIN_QUALITY - intake.DERIVATIVE_QUALITY_STEP)
    )

    assert len(intake.display_derivative(incompressible)) > intake.DERIVATIVE_MAX_BYTES, (
        "this fixture now fits the budget, so the loop never reaches its floor"
    )
    assert at_the_floor == expected
    assert at_the_floor != one_step_below


def test_the_steps_between_the_ceiling_and_the_floor_are_taken() -> None:
    # The clamp must not turn the search into "try 82, then give up at 68":
    # roughly 90% of the catalogue meets the budget at full quality and the
    # rest should degrade gradually, not in one jump.
    assert intake.DERIVATIVE_QUALITY > intake.DERIVATIVE_MIN_QUALITY
    steps = []
    quality = intake.DERIVATIVE_QUALITY
    while quality > intake.DERIVATIVE_MIN_QUALITY:
        quality = max(intake.DERIVATIVE_MIN_QUALITY, quality - intake.DERIVATIVE_QUALITY_STEP)
        steps.append(quality)

    assert steps == [76, 70, 68]


# --- AD-11's crop -----------------------------------------------------------
# `apps/api/tests/test_scan_submission.py` drives this through the real
# endpoint, which proves it is wired up and refuses what it should over the
# wire. This file asserts the pixels it actually produces — the box a caller
# cannot see from a status code — and the exception it raises directly,
# without a route's own status-code translation in the way.


def test_the_rectangle_is_read_against_the_images_own_pixels() -> None:
    image = textured(size=(200, 100))

    cropped = intake.crop_to_rect(image, x=0.25, y=0.5, width=0.5, height=0.5)

    # 200x100, so x=0.25 -> 50px, width=0.5 -> 100px; y=0.5 -> 50px,
    # height=0.5 -> 50px. Different scales on each axis, on purpose: a bug
    # that swapped width/height against x/y would still pass a square fixture.
    assert cropped.size == (100, 50)


def test_a_full_frame_rectangle_is_accepted_and_changes_nothing() -> None:
    image = textured(size=(64, 48))

    cropped = intake.crop_to_rect(image, x=0, y=0, width=1, height=1)

    assert cropped.size == image.size
    assert np.asarray(cropped).tolist() == np.asarray(image).tolist()


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"width": 0}, "zero width"),
        ({"height": 0}, "zero height"),
        ({"width": -0.1}, "negative width"),
        ({"x": 1.0, "width": 0.1}, "x at the ceiling — no pixel sits at fraction 1.0"),
        ({"y": 1.0, "height": 0.1}, "y at the ceiling"),
        ({"x": -0.01}, "x below zero"),
        ({"y": -0.01}, "y below zero"),
        ({"x": 0.5, "width": 0.6}, "x + width past the far edge"),
        ({"y": 0.5, "height": 0.6}, "y + height past the far edge"),
        # `nan`/`inf` fail every ordinary comparison as `False`, so a bounds
        # check that only compares (`width <= 0`, `x + width > 1`, ...) lets
        # each of these through to `round()`, which raises an uncaught
        # `ValueError` rather than this function's own `InvalidCropRect`. One
        # case per field, so a `math.isfinite` guard dropped from any single
        # argument is still caught.
        ({"width": float("nan")}, "nan width"),
        ({"height": float("nan")}, "nan height"),
        ({"x": float("nan")}, "nan x"),
        ({"y": float("nan")}, "nan y"),
        ({"width": float("inf")}, "infinite width"),
        ({"height": float("inf")}, "infinite height"),
        ({"x": float("inf")}, "infinite x"),
        ({"y": float("inf")}, "infinite y"),
        ({"x": float("-inf")}, "negative-infinite x"),
        ({"y": float("-inf")}, "negative-infinite y"),
    ],
)
def test_a_degenerate_or_out_of_bounds_rectangle_is_refused(
    kwargs: dict[str, float], why: str
) -> None:
    base = {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}
    image = textured()

    with pytest.raises(intake.InvalidCropRect):
        intake.crop_to_rect(image, **{**base, **kwargs})


def test_rounding_a_tiny_fractional_rectangle_never_collapses_to_zero_pixels() -> None:
    # A rectangle that is entirely valid in fractional terms can still round to
    # zero width or height against a small enough image — this one is small
    # enough to round down towards the origin but not so close to the far edge
    # that it collapses (see the test directly below for that case), so the
    # crop it produces is at least one pixel on each axis.
    image = textured(size=(20, 20))

    cropped = intake.crop_to_rect(image, x=0.01, y=0.01, width=0.02, height=0.02)

    assert cropped.width >= 1
    assert cropped.height >= 1


def test_a_rectangle_that_rounds_to_no_pixels_against_the_far_edge_is_refused() -> None:
    # `x`/`y` this close to 1.0 pass every fractional bounds check above —
    # `0.99 < 1.0`, and `0.99 + 0.005 = 0.995 <= 1.0` — but against a small
    # image `round(x * image.width)` can land exactly on `image.width` itself,
    # and clamping `right`/`bottom` to that same edge then makes the box zero
    # pixels wide or tall. This is the case the bounds checks above cannot
    # catch because nothing is wrong with the rectangle in fractional terms —
    # only the rounding of it against *this* image's pixel grid.
    image = textured(size=(10, 10))

    with pytest.raises(intake.InvalidCropRect):
        intake.crop_to_rect(image, x=0.99, y=0.99, width=0.005, height=0.005)
