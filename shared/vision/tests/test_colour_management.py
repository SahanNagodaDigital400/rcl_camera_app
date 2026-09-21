"""AD-15 — colour management, asserted on hue *and* brightness.

Roughly 60% of this catalogue's reference images are CMYK press files, not
photographs. A naive `.convert("RGB")` discards the embedded ICC profile:
measured on a 28-image sample as a 12.6-level average and 84.6-level peak
channel shift, and up to 68 levels on one named tile — which is rendered the
wrong colour *and* embedded from wrong pixels, against sRGB phone queries, in a
different colour space.

Two separate bugs were found there and the first fix did not catch the second,
which is why every check below that can guard brightness does so as well as
hue:

* ignoring the profile turned a grey-brown marble bright green (hue);
* Pillow's default *perceptual* intent rendered these press profiles near
  black — mean brightness 25.0 against ColorSync's 84.2 (brightness).

Relative colorimetric measured 84.3, within ~1 level of ColorSync, with no
black point compensation (which re-darkened it to 41).

The file is in two halves. The numeric bounds AD-15 states come from one
specific reference image and are asserted against that file, skipped when the
POC's reference tree is not checked out. The mechanism — that an embedded
profile is honoured at all, rather than discarded — is asserted portably
against a fixture this test builds, so a checkout with no reference tree still
fails when the ICC path is removed.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms
from shared_vision import pipeline

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The tile every number in AD-15 was measured on: a medium grey-brown marble
#: carrying a press profile. Under the POC's gitignored reference tree, so this
#: half skips on a fresh checkout.
CMYK_REFERENCE = (
    REPO_ROOT / "poc" / "Tiles" / "45X90" / "POLISH" / "Copy of RP.RSS.0062ST.PL.0T.jpg"
)

needs_reference = pytest.mark.skipif(
    not CMYK_REFERENCE.is_file(),
    reason=f"the POC reference tree is not checked out ({CMYK_REFERENCE})",
)


def channel_means(img: Image.Image) -> tuple[float, float, float]:
    r, g, b = np.asarray(img, dtype=np.float32).reshape(-1, 3).mean(axis=0)
    return float(r), float(g), float(b)


# --- The measured bounds, on the image they were measured on ------------------


@needs_reference
def test_the_cmyk_reference_has_no_green_cast() -> None:
    # The naive conversion put green at ~54.7 against red ~33.5. Colour
    # managed, the channels sit close together on a near-neutral stone.
    img = pipeline.load_image(CMYK_REFERENCE)
    r, g, b = channel_means(img)

    assert img.mode == "RGB"
    assert g < r + 8, f"the green cast is back: mean RGB = {(r, g, b)}"


@needs_reference
def test_the_rendering_intent_matches_colorsync() -> None:
    # Guard the brightness, not only the hue. Perceptual gives 25.0 and black
    # point compensation 41 on this file; ColorSync puts it at 84.2 and
    # relative colorimetric at 84.3.
    mean = float(np.asarray(pipeline.load_image(CMYK_REFERENCE), dtype=np.float32).mean())

    assert 78 <= mean <= 90, f"brightness {mean:.1f} is off ColorSync's 84.2"


@needs_reference
def test_perceptual_intent_would_crush_this_file_to_near_black() -> None:
    """AD-15's second measurement, reproduced rather than quoted.

    Pillow's default intent is *perceptual*, so `renderingIntent=` is one
    omitted keyword away from being lost — and nothing about the resulting
    index would look broken. This runs the same press profile both ways and
    asserts they disagree by tens of levels, which is what makes the constant
    assertion at the bottom of this file worth anything. Only the real press
    profiles show it: a generic CMYK profile carries identical tables for the
    two intents and would pass either way.
    """
    with Image.open(CMYK_REFERENCE) as raw:
        icc = raw.info.get("icc_profile")
        assert icc, "the reference file is no longer a tagged press asset"
        perceptual = ImageCms.profileToProfile(
            raw,
            ImageCms.ImageCmsProfile(io.BytesIO(icc)),
            ImageCms.createProfile("sRGB"),
            renderingIntent=ImageCms.Intent.PERCEPTUAL,
            outputMode="RGB",
        )
    assert perceptual is not None

    relative_mean = float(np.asarray(pipeline.load_image(CMYK_REFERENCE), np.float32).mean())
    perceptual_mean = float(np.asarray(perceptual, np.float32).mean())

    # Measured: 84.3 against 25.0. The bound is loose because the claim is
    # "these are not the same picture", not a second copy of the number above.
    assert relative_mean - perceptual_mean > 25, (
        f"relative colorimetric {relative_mean:.1f} and perceptual {perceptual_mean:.1f} "
        "agree here, so this file can no longer see AD-15's bug"
    )


# --- The mechanism, on a CMYK fixture this test builds ------------------------

#: Where a CMYK ICC profile is found on the machines this is developed and run
#: on. A CMYK profile cannot be committed (binary, and the press profiles in
#: the real tree are licensed) and littleCMS cannot synthesise one —
#: `ImageCms.createProfile` makes sRGB, LAB and XYZ and nothing else — so the
#: mechanism half of this file borrows whatever the system has. Skipped, never
#: quietly passed, when there is none.
CMYK_PROFILE_CANDIDATES = (
    # macOS
    Path("/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc"),
    # Linux, colord / icc-profiles-free
    Path("/usr/share/color/icc/colord/CoatedFOGRA39.icc"),
    Path("/usr/share/color/icc/ECI-RGB.V1.0.icc"),
    Path("/usr/share/color/icc/sRGB.icc"),
)


def _cmyk_profile() -> Path | None:
    for candidate in CMYK_PROFILE_CANDIDATES:
        if not candidate.is_file():
            continue
        try:
            profile = ImageCms.getOpenProfile(str(candidate))
        except ImageCms.PyCMSError:  # pragma: no cover - a profile we cannot read
            continue
        if profile.profile.xcolor_space.strip() == "CMYK":
            return candidate
    return None


CMYK_PROFILE = _cmyk_profile()

needs_cmyk_profile = pytest.mark.skipif(
    CMYK_PROFILE is None,
    reason="no CMYK ICC profile on this machine to build a press-file fixture from",
)


def _cmyk_press_file(source: Image.Image) -> bytes:
    """`source` re-expressed as a CMYK JPEG carrying the profile that decodes it.

    A stand-in for the real press files, and a fair one for what is being
    tested: the bytes on disk are not sRGB, and the only thing that can turn
    them back into the right colours is the embedded profile. Pillow's
    `.convert("RGB")` on a CMYK image is a naive ink inversion that ignores the
    profile entirely — which is the exact bug AD-15 was written from.
    """
    assert CMYK_PROFILE is not None
    profile = ImageCms.getOpenProfile(str(CMYK_PROFILE))
    cmyk = ImageCms.profileToProfile(
        source,
        ImageCms.createProfile("sRGB"),
        profile,
        renderingIntent=pipeline.RENDERING_INTENT,
        outputMode="CMYK",
    )
    assert cmyk is not None
    buf = io.BytesIO()
    cmyk.save(buf, format="JPEG", quality=100, icc_profile=profile.tobytes())
    return buf.getvalue()


@pytest.fixture(scope="module")
def coloured() -> Image.Image:
    # A deliberately saturated, mid-brightness patchwork: a neutral grey would
    # survive being misread, and that is the one case this must not pass on.
    rng = np.random.default_rng(11)
    blocks = rng.integers(40, 210, (8, 8, 3), dtype=np.uint8)
    return Image.fromarray(np.repeat(np.repeat(blocks, 16, axis=0), 16, axis=1), "RGB")


@needs_cmyk_profile
def test_an_embedded_cmyk_profile_is_honoured_rather_than_discarded(
    coloured: Image.Image,
) -> None:
    press = _cmyk_press_file(coloured)

    managed = pipeline.load_image(press)
    naive = Image.open(io.BytesIO(press)).convert("RGB")

    want = np.asarray(coloured, dtype=np.float32)
    got = np.asarray(managed, dtype=np.float32)
    wrong = np.asarray(naive, dtype=np.float32)

    # Hue: the channels come back where they started, within what a round trip
    # through a CMYK gamut and an 8-bit JPEG costs.
    assert np.abs(got - want).mean() < 12.0, (
        f"colour managed means {channel_means(managed)} against {channel_means(coloured)}"
    )
    # Brightness: the same claim on the overall level, stated separately
    # because a fix that only corrects hue can still be badly wrong here — the
    # green cast and the tonal crush were two different bugs.
    assert abs(got.mean() - want.mean()) < 8.0

    # The negative control: the bug this exists for is visible to this test. A
    # reader that discards the profile is off by tens of levels, not by
    # rounding, so an assertion that passed either way would be worth nothing.
    assert np.abs(wrong - want).mean() > 20.0
    assert abs(wrong.mean() - want.mean()) > 10.0


def test_an_untagged_image_is_assumed_srgb_and_survives_unchanged(
    coloured: Image.Image,
) -> None:
    # AD-15: a missing profile is assumed sRGB. Colour management must not
    # disturb an image that is already in it — byte-identical, not close.
    buf = io.BytesIO()
    coloured.save(buf, format="PNG")

    out = pipeline.load_image(buf.getvalue())

    assert np.abs(np.asarray(out, np.int16) - np.asarray(coloured, np.int16)).max() == 0


def test_an_image_with_no_profile_at_all_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "noprofile.jpg"
    Image.new("RGB", (80, 80), (120, 90, 60)).save(path)

    assert pipeline.load_image(path).mode == "RGB"


def test_a_broken_profile_does_not_refuse_the_image(coloured: Image.Image) -> None:
    # A slightly wrong colour beats refusing to index the tile: the caller has
    # no better option to offer, and a reference image that cannot be added is
    # a tile a scan can never return.
    buf = io.BytesIO()
    coloured.save(buf, format="JPEG", icc_profile=b"not an ICC profile")

    assert pipeline.load_image(buf.getvalue()).mode == "RGB"


# --- The intent itself --------------------------------------------------------


def test_the_intent_is_relative_colorimetric_with_no_black_point_compensation() -> None:
    # The two measurements AD-15 records as badly wrong on these press
    # profiles, as a rule rather than as a number: perceptual is Pillow's
    # *default*, so this is one omitted keyword away from being reintroduced,
    # and nothing about the resulting index would look broken.
    assert pipeline.RENDERING_INTENT is ImageCms.Intent.RELATIVE_COLORIMETRIC

    source = (Path(pipeline.__file__)).read_text(encoding="utf-8")
    assert "flags=" not in source, "a littleCMS flag (black point compensation) has appeared"
