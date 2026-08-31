"""Tests for the shared vision module.

test_index_and_query_paths_produce_identical_vectors is the one that must never
be allowed to fail: it is AD-1 as an executable assertion. Any asymmetry between
the index-time and query-time pipeline silently destroys match accuracy and
raises no error, so this test is the only thing standing between a refactor and
a catalogue that quietly stops matching.
"""

import io
from pathlib import Path

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


class TestColourManagement:
    """Only 31 of 131 references are sRGB; most are CMYK press assets.

    Ignoring their ICC profiles turned a dark brown-black marble bright green
    and, worse, embedded it that way — comparing CMYK references against sRGB
    phone queries across colour spaces.
    """

    CMYK_REF = "Tiles/45X90/POLISH/Copy of RP.RSS.0062ST.PL.0T.jpg"

    @pytest.mark.skipif(not Path(CMYK_REF).is_file(), reason="reference tree not present")
    def test_cmyk_reference_is_colour_managed(self):
        img = vision.load_image(self.CMYK_REF)
        assert img.mode == "RGB"
        r, g, b = np.asarray(img, dtype=np.float32).reshape(-1, 3).mean(axis=0)
        # The naive conversion put green at ~54.7 against red ~33.5. Colour
        # managed, the channels sit close together on a near-neutral stone.
        assert g < r + 8, f"green cast is back: mean RGB = {(r, g, b)}"

    @pytest.mark.skipif(not Path(CMYK_REF).is_file(), reason="reference tree not present")
    def test_rendering_intent_matches_colorsync(self):
        """Pillow's perceptual default renders these press profiles near-black.

        macOS ColorSync puts this tile at mean brightness 84.2; perceptual gives
        25.0. Guard the brightness, not just the hue — the green cast and the
        crush were two separate bugs and the first fix did not catch the second.
        """
        mean = float(np.asarray(vision.load_image(self.CMYK_REF), dtype=np.float32).mean())
        assert 78 <= mean <= 90, f"brightness {mean:.1f} is off ColorSync's 84.2"

    def test_srgb_input_survives_a_round_trip(self):
        """Colour management must not disturb an image already in sRGB."""
        rng = np.random.default_rng(3)
        src = Image.fromarray(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8), "RGB")
        buf = io.BytesIO()
        src.save(buf, format="PNG")
        buf.seek(0)
        out = vision.load_image(buf)
        assert np.abs(np.asarray(out, np.int16) - np.asarray(src, np.int16)).max() == 0

    def test_missing_profile_still_loads(self, tmp_path):
        p = tmp_path / "noprofile.jpg"
        Image.new("RGB", (80, 80), (120, 90, 60)).save(p)
        assert vision.load_image(p).mode == "RGB"
