"""Preprocessing and embedding — ported from `poc/tilematch/vision.py`, unchanged.

**This file is a copy, not a reimplementation** (AD-1, and `AGENTS.md`'s first
Known pitfall). The POC module it comes from was written to be lifted here
whole: every constant, the ICC path, the `Image.frombytes` metadata strip, the
lazily-built ONNX session behind its initialisation lock and the `atexit`
release are the POC's, character for character. The one thing that changed is
where the model file lives — `MODEL_PATH` is now `shared_vision/models/` and is
overridable with `ROCELL_MODEL_PATH`, because the POC's `poc/models/` is not on
this package's import path.

Nothing here may be "optimised" on one side only. An asymmetry between
index-time and query-time pixels raises no error, fails no test that is not
looking for it, and shows up only as a quietly worse top-3 number months later.

Layering, unchanged from the POC::

    view selection / augmentation      (index-time only, `shared_vision.views`)
    ---------------------------- PIL.Image boundary -----------------------
    load_image -> preprocess -> embed  (this module, symmetric)
"""

from __future__ import annotations

import atexit
import gc
import hashlib
import io
import json
import os
import threading
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageCms, ImageOps

# --- Preprocessing constants -------------------------------------------------
# Taken verbatim from the model's own preprocessor_config.json (Xenova/dinov2-base),
# not invented. Changing ANY value here invalidates every stored vector.

RESIZE_SHORTEST_EDGE = 256
CROP_SIZE = 224
RESAMPLE = Image.Resampling.BICUBIC  # resample: 3 in preprocessor_config.json
IMAGE_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGE_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Deterministic decode cap. Reference scans reach 14457px; decoding them at full
# size is slow and buys nothing at 224px input. Applied identically on both
# paths so it can never become an asymmetry.
DECODE_MAX_EDGE = 2048

# Pillow refuses images above 2x MAX_IMAGE_PIXELS with DecompressionBombError,
# which inherits straight from Exception — not OSError — so it slips past the
# usual "corrupt file" handlers and aborts a whole build.
#
# The catalogue legitimately contains 185.8 Mpixel scans (19276x9638), so the
# default 89.5 Mpixel limit is simply wrong for trusted reference files. Query
# uploads are a different matter: they are untrusted, and a 60 Mpixel cap is
# already far above any real phone camera.
#
# This is a gate, not a transform — it rejects, it never alters pixels — so it
# cannot introduce index/query asymmetry.
REFERENCE_MAX_PIXELS = 400_000_000
UPLOAD_MAX_PIXELS = 60_000_000

# Grey-world colour constancy: scale each channel so its mean matches the global
# mean, cancelling a uniform illuminant cast. Applied inside preprocess, so it is
# symmetric across both pipelines by construction.
#
# **Off, and AD-15 says to leave it off**: these are full-bleed single-colour
# tiles, so the grey-world assumption (a scene averages to grey) is violated by
# construction — a genuinely pink tile is pink, not a cast to correct. The
# toggle survives the port because `config_hash` reads it: a build that flipped
# it would produce a different stamp and therefore a different generation
# (AD-14), which is exactly the protection a silently-removed toggle would lose.
GREY_WORLD = os.environ.get("TILEMATCH_GREYWORLD", "0") == "1"

EMBED_DIM = 1536  # concat(CLS 768, mean-patch 768)

PIPELINE_VERSION = "dinov2b-224-cls+meanpatch-icc-v3"

# Colour management is not optional on this dataset. Only 31 of 131 reference
# images are sRGB; 63 carry "U.S. Web Coated (SWOP) v2" and 21 more carry custom
# press profiles — these are CMYK printing assets, not photographs.
#
# Two distinct mistakes are avoided here, both found on RP.RSS.0062ST.PL.0T,
# which is a medium grey-brown marble (mean brightness 84):
#
#   .convert("RGB")          ignores the profile entirely -> bright green, and
#                            embeds CMYK references against sRGB queries across
#                            colour spaces.
#   perceptual intent        Pillow's default. These profiles' perceptual tables
#                            render far darker than the file is -> near-black,
#                            mean brightness 25.
#
# Relative colorimetric matches macOS ColorSync within ~1 level on every profile
# type in this tree; perceptual was off by up to 59. No black-point
# compensation — adding it re-darkens to 41 and diverges from ColorSync again.
RENDERING_INTENT = ImageCms.Intent.RELATIVE_COLORIMETRIC

_SRGB = ImageCms.createProfile("sRGB")

# We enforce our own explicit limit above, so Pillow's global default (which
# would raise on legitimate 185 Mpixel reference scans) is lifted. Not set to
# None: the per-call check is what bounds this, and it is stricter for uploads.
Image.MAX_IMAGE_PIXELS = REFERENCE_MAX_PIXELS

#: Where the ONNX weights live, and the **only** deliberate change from the POC.
#:
#: 346 MB of weights never enter git (`.gitignore`), so the file is fetched once
#: per machine by `make model`. The environment variable exists because a
#: deployment may mount the artifact somewhere else entirely, and because a
#: developer who already has the POC's copy should not have to download it
#: twice.
MODEL_PATH_ENV = "ROCELL_MODEL_PATH"
MODEL_DIR = Path(__file__).resolve().parent / "models"
DEFAULT_MODEL_PATH = MODEL_DIR / "model.onnx"
MODEL_PATH = Path(os.environ.get(MODEL_PATH_ENV, "").strip() or DEFAULT_MODEL_PATH)

#: What an operator is told when the artifact is not there. Named so `apps/api`
#: can render the same sentence rather than inventing a second one.
MODEL_MISSING = (
    "The embedding model is not installed. Run `make model` to download it, "
    f"or set {MODEL_PATH_ENV} to an existing model.onnx."
)


def config_hash() -> str:
    """Stamp identifying this exact preprocessing + embedding configuration.

    Stored on the active `embedding_generation` row (AD-14); a search refuses to
    run against a generation built with a different stamp.
    """
    payload = json.dumps(
        {
            "version": PIPELINE_VERSION,
            "resize": RESIZE_SHORTEST_EDGE,
            "crop": CROP_SIZE,
            "resample": int(RESAMPLE),
            "mean": IMAGE_MEAN.tolist(),
            "std": IMAGE_STD.tolist(),
            "decode_max_edge": DECODE_MAX_EDGE,
            "grey_world": GREY_WORLD,
            "rendering_intent": int(RENDERING_INTENT),
            "dim": EMBED_DIM,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# --- Intake (AD-7: sniff -> orient -> strip EXIF -> RGB) ---------------------


def load_image(
    src: str | Path | bytes | io.BytesIO,
    max_pixels: int = REFERENCE_MAX_PIXELS,
) -> Image.Image:
    """Decode any input to a clean RGB image with no metadata.

    Content is sniffed by Pillow, not trusted from the extension. EXIF
    orientation is applied and then all metadata is dropped, so a phone photo
    and a studio scan arrive at `preprocess` in the same state.

    `max_pixels` bounds decompression-bomb exposure. It defaults to the
    reference-file limit; the upload path passes the much tighter
    UPLOAD_MAX_PIXELS because that input is untrusted.

    Raises PIL.UnidentifiedImageError for unreadable/empty files and
    ValueError for an image above `max_pixels`; callers decide what is fatal.
    """
    if isinstance(src, bytes):
        src = io.BytesIO(src)

    img = Image.open(src)

    # Check the header dimensions before any decode, so an oversized file is
    # rejected without ever allocating its pixels.
    pixels = img.width * img.height
    if pixels > max_pixels:
        raise ValueError(
            f"image is {pixels / 1e6:.0f} Mpixels, above the {max_pixels / 1e6:.0f} Mpixel limit"
        )

    # Fast DCT-domain downscale for JPEG. Deterministic for a given file, and
    # applied on both paths, so it cannot introduce index/query asymmetry.
    # Mode is left alone (draft(None, ...)) so a CMYK source stays CMYK until the
    # colour-managed conversion below — asking draft for RGB here would discard
    # the profile silently, which is the bug this replaced.
    img.draft(None, (DECODE_MAX_EDGE, DECODE_MAX_EDGE))

    img = _to_srgb(img)
    img = ImageOps.exif_transpose(img)

    if max(img.size) > DECODE_MAX_EDGE:
        scale = DECODE_MAX_EDGE / max(img.size)
        new = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(new, RESAMPLE)

    # Re-create from raw pixels: guarantees no EXIF, ICC or other metadata rides
    # along. frombytes is a C-level copy (~90x faster than putdata, verified
    # byte-identical) — this runs on every scan, so it matters.
    return Image.frombytes("RGB", img.size, img.tobytes())


def _to_srgb(img: Image.Image) -> Image.Image:
    """Convert to sRGB honouring any embedded ICC profile.

    Falls back to a plain conversion when there is no profile or the transform
    fails — a slightly wrong colour beats refusing to index the image, and the
    caller has no better option to offer.
    """
    icc = img.info.get("icc_profile")
    if icc:
        try:
            return ImageCms.profileToProfile(
                img,
                ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                _SRGB,
                renderingIntent=RENDERING_INTENT,
                outputMode="RGB",
            )
        except (ImageCms.PyCMSError, OSError, ValueError):
            pass
    return img.convert("RGB")


# --- Preprocess --------------------------------------------------------------


def preprocess(img: Image.Image) -> np.ndarray:
    """PIL RGB image -> (3, 224, 224) float32 CHW tensor.

    Resize shortest edge to 256 (bicubic), center crop 224, scale to [0,1],
    normalize by ImageNet statistics. Accepts any input resolution — AD-2
    forbids assuming the client downscaled to anything in particular.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    scale = RESIZE_SHORTEST_EDGE / min(w, h)
    img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), RESAMPLE)

    w, h = img.size
    left = (w - CROP_SIZE) // 2
    top = (h - CROP_SIZE) // 2
    img = img.crop((left, top, left + CROP_SIZE, top + CROP_SIZE))

    arr = np.asarray(img, dtype=np.float32) / 255.0

    if GREY_WORLD:
        means = arr.reshape(-1, 3).mean(axis=0)
        arr = np.clip(arr * (means.mean() / np.clip(means, 1e-4, None)), 0.0, 1.0)

    arr = (arr - IMAGE_MEAN) / IMAGE_STD
    return np.ascontiguousarray(arr.transpose(2, 0, 1))


# --- Embed -------------------------------------------------------------------

_session: ort.InferenceSession | None = None
_input_name: str = ""
_output_name: str = ""
# Scans run in a threadpool, so two first-scans can race here. Without the lock
# each builds its own session and loads the 346 MB model — double the memory and
# a long stall, for one session that ends up used.
_session_lock = threading.Lock()


def _get_session() -> ort.InferenceSession:
    global _session, _input_name, _output_name
    if _session is not None:
        return _session

    with _session_lock:
        if _session is not None:  # another thread won the race while we waited
            return _session
        return _build_session()


def _build_session() -> ort.InferenceSession:
    global _session, _input_name, _output_name

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"{MODEL_MISSING} (looked in {MODEL_PATH})")

    opts = ort.SessionOptions()
    # Physical (performance) cores only. Measured on M-series: 4 threads = 492
    # ms/img, 8 threads = 616 ms/img — the efficiency cores actively hurt.
    # CoreML was also tried and is worse (754 ms/img): it claims only 41 of 643
    # nodes, so the graph ends up split across providers.
    opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # CPUExecutionProvider only: production pins ONNX Runtime CPU, and pinning it
    # here keeps the numbers comparable and deterministic.
    _session = ort.InferenceSession(
        str(MODEL_PATH), sess_options=opts, providers=["CPUExecutionProvider"]
    )
    _input_name = _session.get_inputs()[0].name
    # Dinov2Model exports last_hidden_state (N, tokens, hidden) plus pooler_output
    # (N, hidden). We want the rank-3 one so we can split CLS from patch tokens.
    rank3 = [o.name for o in _session.get_outputs() if len(o.shape) == 3]
    _output_name = rank3[0] if rank3 else _session.get_outputs()[0].name
    return _session


@atexit.register
def _release_session() -> None:
    """Destroy the ONNX session before interpreter shutdown.

    Left to finalization, ONNX Runtime's teardown intermittently aborts the
    process with "recursive_mutex lock failed" — the tests pass and then the exit
    code says otherwise (measured at 1 in 8 runs). Dropping the reference is not
    enough on its own; the collection has to be forced while the interpreter is
    still healthy enough to run the destructor.
    """
    global _session, _input_name, _output_name
    if _session is None:
        return
    _session = None
    _input_name = _output_name = ""
    gc.collect()


def embed(batch: np.ndarray) -> np.ndarray:
    """(N, 3, 224, 224) float32 -> (N, 1536) unit-norm float32.

    DINOv2's own retrieval head: the CLS token concatenated with the mean of the
    patch tokens, each L2-normalized before concatenation so neither half
    dominates, then the result L2-normalized so cosine similarity is a dot
    product.
    """
    if batch.ndim == 3:
        batch = batch[None, ...]

    sess = _get_session()
    hidden = sess.run([_output_name], {_input_name: batch.astype(np.float32)})[0]

    cls = hidden[:, 0, :]
    patches = hidden[:, 1:, :].mean(axis=1)

    feat = np.concatenate([_l2(cls), _l2(patches)], axis=1)
    return _l2(feat).astype(np.float32)


def _l2(x: np.ndarray) -> np.ndarray:
    return x / np.clip(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12, None)


def embed_images(images: list[Image.Image], batch_size: int = 8) -> np.ndarray:
    """Convenience batching wrapper. Still exactly preprocess -> embed."""
    out = []
    for i in range(0, len(images), batch_size):
        chunk = images[i : i + batch_size]
        out.append(embed(np.stack([preprocess(im) for im in chunk])))
    return np.concatenate(out) if out else np.zeros((0, EMBED_DIM), dtype=np.float32)
