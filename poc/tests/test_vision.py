"""Tests for the shared vision module.

test_index_and_query_paths_produce_identical_vectors is the one that must never
be allowed to fail: it is AD-1 as an executable assertion. Any asymmetry between
the index-time and query-time pipeline silently destroys match accuracy and
raises no error, so this test is the only thing standing between a refactor and
a catalogue that quietly stops matching.
"""

import numpy as np
import pytest
from PIL import Image

from tilematch import vision

pytestmark = pytest.mark.skipif(
    not vision.MODEL_PATH.exists(), reason="model not downloaded; run `make model`"
)


@pytest.fixture(scope="module")
def sample():
    rng = np.random.default_rng(7)
    return Image.fromarray(rng.integers(0, 255, (600, 900, 3), dtype=np.uint8), "RGB")


def test_preprocess_shape_and_range(sample):
    a = vision.preprocess(sample)
    assert a.shape == (3, vision.CROP_SIZE, vision.CROP_SIZE)
    assert a.dtype == np.float32


def test_preprocess_accepts_any_input_resolution():
    # AD-2: no server-side code may assume the client downscaled to anything.
    for size in [(224, 224), (80, 4000), (5000, 5000), (1, 1)]:
        img = Image.new("RGB", size, (128, 100, 90))
        assert vision.preprocess(img).shape == (3, 224, 224)


def test_embedding_is_unit_norm_and_correct_dim(sample):
    v = vision.embed(vision.preprocess(sample))
    assert v.shape == (1, vision.EMBED_DIM)
    assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-5)


def test_embedding_is_deterministic(sample):
    a = vision.embed(vision.preprocess(sample))
    b = vision.embed(vision.preprocess(sample))
    np.testing.assert_array_equal(a, b)


def test_index_and_query_paths_produce_identical_vectors(sample):
    """AD-1. Index-time and query-time must agree exactly, not approximately."""
    from tilematch.search import Matcher

    index_side = vision.embed_images([sample])

    # Reach the query path without needing a built index: embed_query's first
    # view is the unmodified image, which is what indexing embeds too.
    query_side = Matcher.embed_query(object.__new__(Matcher), sample)[:1]

    np.testing.assert_array_equal(index_side, query_side)


def test_batching_does_not_change_results(sample):
    """Whatever the batch size, a given image must embed to the same vector."""
    one = vision.embed_images([sample, sample], batch_size=1)
    two = vision.embed_images([sample, sample], batch_size=2)
    np.testing.assert_allclose(one, two, atol=1e-5)


def test_load_image_strips_metadata(tmp_path):
    p = tmp_path / "with_exif.jpg"
    img = Image.new("RGB", (400, 300), (200, 150, 100))
    exif = Image.Exif()
    exif[274] = 1  # Orientation
    img.save(p, exif=exif)

    out = vision.load_image(p)
    assert out.mode == "RGB"
    assert not dict(out.getexif())


def test_load_image_rejects_unreadable_file(tmp_path):
    p = tmp_path / "empty.jpg"
    p.write_bytes(b"")
    with pytest.raises(Exception):
        vision.load_image(p)


def test_config_hash_changes_with_constants(monkeypatch):
    before = vision.config_hash()
    monkeypatch.setattr(vision, "CROP_SIZE", 256)
    assert vision.config_hash() != before
