"""The ported pipeline's contract — AD-1's symmetry assertion above all.

`test_the_write_path_and_the_query_path_produce_identical_vectors` is the one
that must never be allowed to fail. It is AD-1 as an executable assertion: any
asymmetry between index-time and query-time preprocessing silently destroys
match accuracy and raises no error, so this test is the only thing standing
between a refactor and a catalogue that quietly stops matching.

The rest is `poc/tests/test_vision.py`'s contract, carried across with the
port: shape and dtype, unit norm, bit-exact determinism, resolution
independence (AD-2), EXIF stripped, a zero-byte file refused, and
`config_hash` sensitive to the constants it stamps.

**Skipped, not failed, when the model artifact is absent.** A developer who has
not run `make model` has a 346 MB download ahead of them, not a broken
checkout — and the charter assertions below run either way, because they are
about this package's own promises rather than about the weights.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import shared_vision
from PIL import Image
from shared_vision import pipeline

#: Only the tests that actually run the model. The charter block at the bottom
#: of this file is deliberately outside it: whether the docstring still records
#: AD-1 has nothing to do with whether the weights are on this machine.
needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason=f"model not downloaded; run `make model` (looked in {pipeline.MODEL_PATH})",
)


@pytest.fixture(scope="module")
def sample() -> Image.Image:
    rng = np.random.default_rng(7)
    return Image.fromarray(rng.integers(0, 255, (600, 900, 3), dtype=np.uint8), "RGB")


# --- Preprocess ---------------------------------------------------------------


def test_preprocess_shape_and_dtype(sample: Image.Image) -> None:
    a = pipeline.preprocess(sample)

    assert a.shape == (3, pipeline.CROP_SIZE, pipeline.CROP_SIZE)
    assert a.dtype == np.float32


@pytest.mark.parametrize("size", [(224, 224), (80, 4000), (5000, 5000), (1, 1)])
def test_preprocess_accepts_any_input_resolution(size: tuple[int, int]) -> None:
    # AD-2: the client-side canvas downscale is bandwidth optimisation, not the
    # preprocessing boundary, so no server-side code may assume it produced
    # anything in particular.
    img = Image.new("RGB", size, (128, 100, 90))

    assert pipeline.preprocess(img).shape == (3, 224, 224)


# --- Embed --------------------------------------------------------------------


@needs_model
def test_embedding_is_unit_norm_and_the_dimension_pgvector_pins(sample: Image.Image) -> None:
    # AD-5 stores vectors unit-norm so cosine similarity is a single dot
    # product, and pins the column at `vector(1536)`. Both halves of that are
    # this assertion.
    v = pipeline.embed(pipeline.preprocess(sample))

    assert v.shape == (1, pipeline.EMBED_DIM)
    assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-5)


@needs_model
def test_embedding_is_bit_exactly_deterministic(sample: Image.Image) -> None:
    # Not `allclose`. A write path and a query path that agree to five decimal
    # places are a write path and a query path that have already diverged.
    a = pipeline.embed(pipeline.preprocess(sample))
    b = pipeline.embed(pipeline.preprocess(sample))

    np.testing.assert_array_equal(a, b)


@needs_model
def test_batching_does_not_change_results(sample: Image.Image) -> None:
    one = pipeline.embed_images([sample, sample], batch_size=1)
    two = pipeline.embed_images([sample, sample], batch_size=2)

    np.testing.assert_allclose(one, two, atol=1e-5)


@needs_model
def test_the_write_path_and_the_query_path_produce_identical_vectors(
    sample: Image.Image,
) -> None:
    """AD-1. The two paths must agree exactly, not approximately.

    The write path is `apps/api/api/catalogue.py`, which embeds the first of
    `generate_views`'s views — deliberately the unmodified image. The query
    path is `find_candidates`, which embeds the submitted photo. Both reach the
    same two functions with no wrapping, and this asserts the outcome rather
    than the call graph: a wrapper that re-resized, re-cropped or re-converted
    on one side would pass a structural check and fail here.
    """
    write_side = pipeline.embed_images(shared_vision.generate_views(sample, "key")[:1])
    query_side = pipeline.embed(pipeline.preprocess(sample))

    np.testing.assert_array_equal(write_side, query_side)


@needs_model
def test_the_first_generated_view_is_the_unmodified_image(sample: Image.Image) -> None:
    # The premise the assertion above rests on, stated separately so that a
    # change to `generate_views` fails as itself rather than as a symmetry
    # break that is not one.
    assert shared_vision.generate_views(sample, "key")[0] is sample


# --- Loading ------------------------------------------------------------------


def test_load_image_applies_orientation_and_then_strips_every_byte_of_metadata(
    tmp_path: Path,
) -> None:
    path = tmp_path / "with_exif.jpg"
    img = Image.new("RGB", (400, 300), (200, 150, 100))
    exif = Image.Exif()
    exif[274] = 6  # Orientation: rotate 90 CW on display
    exif[271] = "Rocell"  # Make
    exif[0x8825] = {1: "N", 2: (7.0, 0.0, 0.0)}  # GPS IFD
    img.save(path, exif=exif)

    out = pipeline.load_image(path)

    # Applied: orientation 6 is a quarter turn, so the stored pixels are
    # upright and the dimensions have swapped. A pipeline that dropped the tag
    # without honouring it would leave a sideways tile in the index.
    assert out.size == (300, 400)
    # Then dropped: what reaches storage carries no GPS, no make, no
    # orientation to apply a second time, and no ICC payload.
    assert out.mode == "RGB"
    assert not dict(out.getexif())
    assert out.info.get("icc_profile") is None


def test_load_image_refuses_a_zero_byte_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jpg"
    path.write_bytes(b"")

    with pytest.raises(Exception):  # noqa: B017 - Pillow's own class, whatever it is
        pipeline.load_image(path)


def test_load_image_decides_by_content_and_not_by_extension(tmp_path: Path) -> None:
    # AGENTS.md Policy: never accept a file validated by extension. A PNG named
    # `.jpg` is a readable image and is accepted; text named `.jpg` is not.
    png_as_jpg = tmp_path / "actually_a_png.jpg"
    Image.new("RGB", (64, 48), (10, 120, 90)).save(png_as_jpg, format="PNG")

    assert pipeline.load_image(png_as_jpg).size == (64, 48)


def test_load_image_caps_the_long_edge_identically_on_both_paths() -> None:
    # AD-1: both pipelines decode to the same 2048px cap before anything else.
    big = Image.new("RGB", (pipeline.DECODE_MAX_EDGE * 2, 500), (30, 40, 50))
    buf = io.BytesIO()
    big.save(buf, format="PNG")

    out = pipeline.load_image(buf.getvalue())

    assert max(out.size) == pipeline.DECODE_MAX_EDGE


def test_load_image_rejects_above_the_pixel_ceiling_from_the_header() -> None:
    # The gate is a refusal, never a transform, so it cannot introduce an
    # asymmetry — and it reads the header rather than allocating the pixels.
    img = Image.new("RGB", (4000, 4000), (1, 2, 3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    with pytest.raises(ValueError, match="Mpixel limit"):
        pipeline.load_image(buf.getvalue(), max_pixels=1_000_000)


# --- The AD-14 stamp ----------------------------------------------------------


def test_config_hash_changes_with_a_constant_it_stamps(monkeypatch: pytest.MonkeyPatch) -> None:
    # AD-14: the stamp identifies the exact preprocessing configuration, so a
    # changed constant must produce a different generation rather than silently
    # mixing vectors from two pipelines.
    before = pipeline.config_hash()
    monkeypatch.setattr(pipeline, "CROP_SIZE", 256)

    assert pipeline.config_hash() != before


def test_the_pipeline_version_is_the_ported_one() -> None:
    # The skeleton carried a placeholder that deliberately did not claim the
    # POC's version string. The port claims it, because it is the POC's
    # pipeline.
    assert shared_vision.PIPELINE_VERSION == "dinov2b-224-cls+meanpatch-icc-v3"


# --- The charter, which outlived the skeleton ---------------------------------


def test_module_docstring_records_the_ad1_invariant() -> None:
    doc = shared_vision.__doc__ or ""

    assert "AD-1" in doc
    assert "identical" in doc
    assert shared_vision.PORT_SOURCE in doc


def test_port_source_points_at_the_poc_module() -> None:
    assert shared_vision.PORT_SOURCE == "poc/tilematch/vision.py"


def test_the_entry_points_no_longer_refuse_to_pretend() -> None:
    # `test_skeleton.py`'s two assertions, inverted. They said `preprocess` and
    # `embed` must raise rather than return something that looks like a vector;
    # the port is what makes them return one, and this is the line that records
    # the crossing. `embed`'s half is every `@needs_model` test above.
    assert shared_vision.preprocess(Image.new("RGB", (300, 300))).shape == (3, 224, 224)
    assert shared_vision.preprocess is pipeline.preprocess
    assert shared_vision.embed is pipeline.embed
