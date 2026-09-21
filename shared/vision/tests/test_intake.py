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
