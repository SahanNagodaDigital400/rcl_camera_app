"""AD-13's shape, pinned: 16 views per Reference Image, 4 of them clean rotations.

The failure this guards against is the one the architecture spine's own ERD
made: one embedding per Reference Image. Pooling the views into a single vector
at write time gives back the scale invariance the crops exist to buy, and
nothing about it raises — the index is simply, permanently, less able to find
the tile.

Reproducibility is the second claim. A rebuild has to produce the same views
from the same bytes, or a re-index (AD-14) is not a rebuild of the same
generation at all; `generate_views` is seeded from the caller's key, and
`apps/api` passes the image's sha256 for exactly that reason.
"""

from __future__ import annotations

import numpy as np
import pytest
import shared_vision
from PIL import Image
from shared_vision import views


@pytest.fixture
def reference() -> Image.Image:
    rng = np.random.default_rng(23)
    return Image.fromarray(rng.integers(0, 255, (512, 768, 3), dtype=np.uint8), "RGB")


def test_one_reference_image_yields_sixteen_views(reference: Image.Image) -> None:
    assert len(views.generate_views(reference, "key")) == views.VIEWS_PER_IMAGE == 16


def test_the_first_four_are_the_clean_rotations_of_the_whole_frame(
    reference: Image.Image,
) -> None:
    # Baseline coverage, unaugmented, so the index always holds the tile as it
    # actually looks at each of the four orientations a photograph can have.
    generated = views.generate_views(reference, "key")

    assert views.CANONICAL_VIEWS == 4
    assert generated[0] is reference
    for k in range(1, views.CANONICAL_VIEWS):
        expected = reference.rotate(90 * k, expand=True)
        assert np.array_equal(np.asarray(generated[k]), np.asarray(expected))


def test_the_remaining_twelve_are_augmented_crops(reference: Image.Image) -> None:
    generated = views.generate_views(reference, "key")
    crops = generated[views.CANONICAL_VIEWS :]

    assert len(crops) == 12
    # Every one is a crop: strictly smaller than the frame on its short edge,
    # within the 25-60% band a staff photo of a tile face lands in.
    for crop in crops:
        assert min(crop.size) < min(reference.size)


def test_the_view_kinds_are_a_function_of_the_index() -> None:
    # `reference_embedding.view_kind` is written from this, so it cannot be a
    # separate decision a second writer could get wrong.
    kinds = [views.view_kind(i) for i in range(views.VIEWS_PER_IMAGE)]

    assert kinds[: views.CANONICAL_VIEWS] == [views.VIEW_ROTATION] * 4
    assert set(kinds[views.CANONICAL_VIEWS :]) == {views.VIEW_CROP}


def test_the_same_key_gives_the_same_views(reference: Image.Image) -> None:
    # The seed is the whole of reproducibility: without it a re-index builds a
    # different generation from identical bytes, and no test anywhere would
    # notice.
    first = views.generate_views(reference, "sha-of-the-bytes")
    second = views.generate_views(reference, "sha-of-the-bytes")

    for a, b in zip(first, second, strict=True):
        assert np.array_equal(np.asarray(a), np.asarray(b))


def test_a_different_key_gives_different_crops(reference: Image.Image) -> None:
    # The negative control for the test above: if the seed were ignored, both
    # would pass and neither would mean anything.
    first = views.generate_views(reference, "one")
    second = views.generate_views(reference, "two")

    assert any(
        a.size != b.size or not np.array_equal(np.asarray(a), np.asarray(b))
        for a, b in zip(
            first[views.CANONICAL_VIEWS :], second[views.CANONICAL_VIEWS :], strict=True
        )
    )


def test_the_eval_only_query_synthesizer_did_not_come_across() -> None:
    # `poc/tilematch/augment.py` also holds `synthesize_query`, which fakes a
    # phone photo from a studio scan for the synthetic eval. It is deliberately
    # harsher than anything here and has no business in a write path: anything
    # that called it would be embedding an image nobody ever photographed.
    assert not hasattr(views, "synthesize_query")
    assert not hasattr(shared_vision, "synthesize_query")
