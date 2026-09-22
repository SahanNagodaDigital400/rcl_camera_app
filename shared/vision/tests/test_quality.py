"""FR-9's retake gate — score, threshold, and the env-var override.

Runs with no model artifact required: `blur_score`/`passes_quality` are pure
numpy over a `PIL.Image`, with no ONNX session anywhere in the path.
"""

from __future__ import annotations

import importlib
import logging

import numpy as np
import pytest
import shared_vision
from PIL import Image
from shared_vision import quality


def a_noisy_image(seed: int = 3, size: tuple[int, int] = (64, 64)) -> Image.Image:
    """A textured patch — plenty of high-frequency edge content to score high."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def a_flat_image(size: tuple[int, int] = (64, 64)) -> Image.Image:
    """A single uniform colour — zero Laplacian variance by construction."""
    return Image.new("RGB", size, (128, 96, 200))


# --- blur_score -----------------------------------------------------------------


def test_a_noisy_textured_image_scores_high() -> None:
    assert quality.blur_score(a_noisy_image()) > quality.DEFAULT_SCAN_QUALITY_THRESHOLD


def test_a_uniform_flat_image_scores_zero() -> None:
    # Every pixel equals its neighbours, so every 3x3 Laplacian response is
    # exactly zero and the variance of an all-zero array is zero too.
    assert quality.blur_score(a_flat_image()) == 0.0


@pytest.mark.parametrize("size", [(1, 1), (2, 2), (2, 10), (10, 2)])
def test_an_image_under_3px_on_either_edge_scores_zero_without_raising(
    size: tuple[int, int],
) -> None:
    assert quality.blur_score(a_flat_image(size)) == 0.0


def test_a_hand_computed_grid_matches_its_own_laplacian_variance() -> None:
    """A regression that widened the early-return guard so `blur_score`
    returned `0.0` for every small-but-valid image would have passed the
    weaker assertion this test replaces (`>= 0.0`, true even for a stub that
    always answers zero) silently. This pins the *exact* value for a 5x5
    grid whose interior Laplacian responses are computed by hand below, a
    value only the real computation can produce — a 3x3 image cannot make
    this distinction at all, since its interior is a single pixel and the
    variance of one value is `0.0` regardless of what that value is.

    Grid (a single spike of 100 at the centre, 0 everywhere else)::

        0   0   0   0   0
        0   0   0   0   0
        0   0 100   0   0
        0   0   0   0   0
        0   0   0   0   0

    The nine interior (3x3) Laplacian responses (`up + down + left + right -
    4*center` at each interior point) this produces are
    `[0, 100, 0, 100, -400, 100, 0, 100, 0]`: the four points orthogonally
    adjacent to the spike each see exactly one neighbour at 100, the spike's
    own point sees `0 + 0 + 0 + 0 - 4*100 = -400`, and the four diagonal
    interior points see nothing at all. Their mean is `0` (they sum to
    zero), so the population variance `np.var` computes is the mean of their
    squares: `(4 * 100**2 + 400**2) / 9 == 200_000 / 9`.
    """
    grid = np.zeros((5, 5), dtype=np.uint8)
    grid[2, 2] = 100
    image = Image.fromarray(grid, "L")

    assert quality.blur_score(image) == pytest.approx(200_000 / 9)


# --- passes_quality ---------------------------------------------------------------


def test_a_sharp_image_passes() -> None:
    assert quality.passes_quality(a_noisy_image()) is True


def test_a_flat_image_fails() -> None:
    assert quality.passes_quality(a_flat_image()) is False


def test_a_degenerate_crop_fails_rather_than_raising() -> None:
    assert quality.passes_quality(a_flat_image((2, 2))) is False


def test_an_explicit_threshold_overrides_the_module_default() -> None:
    image = a_noisy_image()
    score = quality.blur_score(image)

    assert quality.passes_quality(image, threshold=score + 1) is False
    assert quality.passes_quality(image, threshold=score) is True


# --- The environment override -----------------------------------------------------


def test_the_env_var_overrides_the_threshold_read_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SCAN_QUALITY_THRESHOLD` is read once at import — `pipeline.GREY_WORLD`'s
    own pattern — so proving the override works means re-importing with the
    environment variable set, not just calling a setter.

    **Reloads the `shared_vision` package too, not only `quality`.**
    `apps/api/api/scan.py` never calls `quality.passes_quality` directly — it
    calls `shared_vision.passes_quality`/`shared_vision.SCAN_QUALITY_THRESHOLD`,
    names bound into the *package's* namespace once, at package-import time,
    by `shared_vision/__init__.py`'s own `from shared_vision.quality import
    ...`. A `from x import y` binding does not track a later reload of `x`,
    so reloading `quality` alone leaves `shared_vision.SCAN_QUALITY_THRESHOLD`
    pointing at the value it had before the override — asserting only against
    `quality`'s own copy would prove nothing about the names production code
    actually calls.
    """
    image = a_noisy_image()
    score = quality.blur_score(image)

    monkeypatch.setenv(quality.SCAN_QUALITY_THRESHOLD_ENV, str(score + 1))
    try:
        importlib.reload(quality)
        reloaded = importlib.reload(shared_vision)
        assert reloaded.SCAN_QUALITY_THRESHOLD == pytest.approx(score + 1)
        # The new bound — not the old default — decides the gate now, with no
        # code change: the same borderline photo that passed before now fails.
        assert reloaded.passes_quality(image) is False
    finally:
        # Undone explicitly, and both modules reloaded again, before
        # `monkeypatch`'s own teardown runs: `shared_vision` and
        # `shared_vision.quality` are singletons elsewhere in the suite, and
        # leaving either reloaded against a threshold this test invented
        # would leak into whatever runs next.
        monkeypatch.delenv(quality.SCAN_QUALITY_THRESHOLD_ENV, raising=False)
        importlib.reload(quality)
        importlib.reload(shared_vision)


@pytest.mark.parametrize("raw", ["not-a-number", "nan", "inf", "-inf"])
def test_an_unparseable_or_non_finite_env_value_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    raw: str,
) -> None:
    """An operator's typo must not crash every import of `shared_vision`, and
    `float()` itself is not strict enough to catch every bad value: it parses
    `"nan"`, `"inf"` and `"-inf"` without raising. A `nan` threshold would
    fail *every* scan (every comparison against `nan`, including `>=`, is
    `False`) and an `inf`/`-inf` one would fail or pass *every* scan outright
    — silently, with no real bound in effect — so all four inputs here must
    fall back to `DEFAULT_SCAN_QUALITY_THRESHOLD` rather than crash the
    import or gate on a value nobody could have intended, and each must be
    logged so the fallback is not silent either.
    """
    monkeypatch.setenv(quality.SCAN_QUALITY_THRESHOLD_ENV, raw)
    try:
        with caplog.at_level(logging.WARNING, logger="rocell.shared_vision.quality"):
            reloaded = importlib.reload(quality)

        assert reloaded.SCAN_QUALITY_THRESHOLD == reloaded.DEFAULT_SCAN_QUALITY_THRESHOLD
        assert any(raw in record.getMessage() for record in caplog.records)
    finally:
        monkeypatch.delenv(quality.SCAN_QUALITY_THRESHOLD_ENV, raising=False)
        importlib.reload(quality)
