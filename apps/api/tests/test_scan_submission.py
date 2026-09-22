"""`POST /scans` — Stories 3.2-3.4's I/O matrix, through the real route.

Driven against a real PostgreSQL and a real object store for the reason every
other route test in this suite is: `require_claimed_user` is a dependency, not
a line in the handler, and the only honest way to prove a refused caller never
reaches the crop is to run the real app.

**Most of this file still needs no ONNX model.** `find_candidates` (Story 3.4)
answers `[]` without ever touching the model when the catalogue has no active
generation — which is every test below that never adds a Tile, exactly as
`test_tile_searchable.py`'s own empty-catalogue case argues. The two cases
below that seed a real Tile through `POST /admin/tiles` and expect it back as
a Candidate are marked `needs_model`, because embedding both the reference
image and the query photo is the one thing they cannot avoid touching the
model for.

Pattern imitated throughout from `test_catalogue_authorization.py`: `sign_in`,
a `make_user` role, and asserting the refusal's status and code rather than
reaching for the database at all, since a dependency-level refusal never
touches it.
"""

from __future__ import annotations

import io
import struct
import threading
import time
import zlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import shared_vision
from api import catalogue
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]

SCANS = "/scans"
ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"

#: `test_remove_tile.py`'s own technique, with its own figures: how long a
#: concurrency test gives a second, deliberately racing thread a real chance
#: to reach the point under contention before checking it has not gone past
#: it, and how long it then waits for the threads it started to actually
#: finish. Generous rather than tight — a decode and a quality check are
#: milliseconds of work, and what this buys is headroom against a loaded CI
#: box, not precision.
LOCK_OVERLAP_SECONDS = 1.0
LOCK_RELEASE_SECONDS = 30.0

#: The two happy-path tests below add a Tile and embed a query photo against
#: it; every other test in this file is refused before a byte is decoded, or
#: matches against a catalogue with no active generation, and needs no
#: artifact at all. `test_tile_searchable.py`'s own marker.
needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)


def a_tile_photograph(seed: int = 5, size: tuple[int, int] = (320, 320)) -> Image.Image:
    """A textured patch — `test_add_tile.py`'s own helper, unchanged."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def jpeg_bytes(image: Image.Image | None = None) -> bytes:
    buf = io.BytesIO()
    (image or a_tile_photograph()).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def a_flat_photograph(size: tuple[int, int] = (320, 320)) -> Image.Image:
    """A single uniform colour — zero Laplacian variance, whatever the crop
    rectangle takes from it, and the fixture Story 3.3's quality gate exists
    to refuse. `a_tile_photograph`'s random-noise fixture scores far above any
    provisional threshold, so it stays the happy-path fixture unchanged.
    """
    return Image.new("RGB", size, (180, 180, 180))


def sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


def submit_scan(
    client: TestClient,
    *,
    crop_x: float = 0.1,
    crop_y: float = 0.1,
    crop_width: float = 0.8,
    crop_height: float = 0.8,
    image: tuple[str, bytes, str] | None = None,
) -> Any:
    """`POST /scans` as multipart, the shape `submitScan` (`apps/web`) builds."""
    data = {
        "crop_x": crop_x,
        "crop_y": crop_y,
        "crop_width": crop_width,
        "crop_height": crop_height,
    }
    files = [("image", image or ("scan.jpg", jpeg_bytes(), "image/jpeg"))]
    return client.post(SCANS, data=data, files=files)


# --- The happy path -------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.STAFF, Role.ADMIN])
def test_a_claimed_caller_submits_a_scan_against_an_empty_catalogue(
    client: TestClient, make_user: MakeUser, role: Role
) -> None:
    """FR-24 — both roles Scan is reachable by can submit a crop (not admin-only).

    Nothing has ever been added to this test's catalogue, so `find_candidates`
    answers `[]` without touching the model (`test_tile_searchable.py`'s own
    empty-catalogue case) — this is `200` and an empty array, not a `404` and
    not the old `202`: the request fully resolves the match before answering.
    """
    sign_in(client, make_user(role=role))

    response = submit_scan(client)

    assert response.status_code == 200, response.text
    assert response.json() == []
    assert response.headers["cache-control"] == "no-store"


#: Edge length of a generated reference. `test_tile_searchable.py`'s own
#: constant, large enough that a perturbed copy still carries structure.
TILE_SIZE = 384


def a_tile(seed: int) -> Image.Image:
    """A tile face with visible structure — `test_tile_searchable.py`'s own
    fixture, reused rather than reimplemented: per-pixel noise is not a
    texture to a vision model, so a catalogue of noise makes retrieval a coin
    toss and this file would be measuring the fixture rather than the route.
    """
    rng = np.random.default_rng(seed)
    face = Image.new("RGB", (TILE_SIZE, TILE_SIZE), tuple(int(v) for v in rng.integers(30, 220, 3)))
    pen = ImageDraw.Draw(face)
    ink = tuple(int(v) for v in rng.integers(30, 220, 3))
    period = int(rng.integers(12, 48))
    for offset in range(0, TILE_SIZE, period):
        if seed % 3 == 0:
            pen.rectangle([offset, 0, offset + period // 2, TILE_SIZE], fill=ink)
        elif seed % 3 == 1:
            pen.ellipse([offset, offset, offset + period, offset + period], outline=ink, width=4)
        else:
            pen.line([(0, offset), (TILE_SIZE, offset + period)], fill=ink, width=5)

    grain = np.asarray(face, dtype=np.int16) + rng.integers(-12, 12, (TILE_SIZE, TILE_SIZE, 3))
    return Image.fromarray(np.clip(grain, 0, 255).astype(np.uint8), "RGB")


def a_photograph_of(image: Image.Image) -> Image.Image:
    """A perturbed copy standing in for a phone photo of the physical tile —
    `test_tile_searchable.py`'s own helper, softened less than that file's
    own copy: this one has to clear `POST /scans`' own quality gate (FR-9)
    as well as still retrieve, where that file's calls it straight through
    `find_candidates` and never meets the gate at all.
    """
    width, height = image.size
    crop = image.crop((width // 8, height // 8, width * 7 // 8, height * 7 // 8))
    crop = ImageEnhance.Brightness(crop).enhance(1.12)
    crop = crop.filter(ImageFilter.GaussianBlur(radius=0.3))
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def add_reference_tile(
    client: TestClient, make_user: MakeUser, code: str, image: Image.Image
) -> Any:
    """Seed one Tile through the real add route, as an Administrator.

    A separate, throwaway Administrator session — `submit_scan`'s own caller
    signs in afterward, and a Scan is reachable by Staff and Administrator
    alike (FR-24), so which role added the catalogue is not what this test
    is about.
    """
    account = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    sign_in(client, account)
    response = client.post(
        ADD_TILE,
        data={"code": code, "size": "45X90", "category": "POLISH"},
        files=[("images", (f"{code}.jpg", jpeg_bytes(image), "image/jpeg"))],
    )
    assert response.status_code == 201, response.text
    return response.json()


@needs_model
def test_a_populated_catalogue_returns_the_matching_tile_as_a_candidate(
    client: TestClient, make_user: MakeUser
) -> None:
    """The route's own acceptance clause: matching wired to a real catalogue.

    Every field the response carries is asserted: `tile_id` and `image_id` are
    the seeded Tile's own, `code`/`size`/`category` mirror what was added, and
    no `score`, `rank` or similarity value is anywhere in the body (AD-20).
    """
    reference = a_tile(41)
    seeded = add_reference_tile(client, make_user, "RP.CMA.0001DJ.SM.0T", reference)

    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))
    response = submit_scan(
        client,
        crop_x=0,
        crop_y=0,
        crop_width=1,
        crop_height=1,
        image=("scan.jpg", jpeg_bytes(a_photograph_of(reference)), "image/jpeg"),
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert [candidate["code"] for candidate in body][:1] == ["RP.CMA.0001DJ.SM.0T"]
    best = body[0]
    assert best["tile_id"] == seeded["id"]
    assert best["size"] == "45X90"
    assert best["category"] == "POLISH"
    assert best["image_id"] == seeded["reference_images"][0]["id"]
    for candidate in body:
        assert set(candidate) == {"tile_id", "code", "size", "category", "image_id"}


@needs_model
def test_two_candidates_from_the_same_category_keep_their_own_slot(
    client: TestClient, make_user: MakeUser
) -> None:
    """AD-18, restated at the route: never deduplicated or diversified by Category."""
    tiles = {f"POLISH-{seed}": a_tile(seed) for seed in (21, 22, 23)}
    for code, image in tiles.items():
        add_reference_tile(client, make_user, code, image)

    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))
    response = submit_scan(
        client,
        crop_x=0,
        crop_y=0,
        crop_width=1,
        crop_height=1,
        image=("scan.jpg", jpeg_bytes(a_photograph_of(tiles["POLISH-22"])), "image/jpeg"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == catalogue.TOP_K == 3
    assert len({candidate["tile_id"] for candidate in body}) == 3
    assert {candidate["category"] for candidate in body} == {"POLISH"}


# --- The model is a prerequisite here too -----------------------------------


@needs_model
def test_a_missing_model_artifact_refuses_the_scan_through_the_real_route(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`find_candidates`'s own `503 matching_unavailable`, proven through
    `POST /scans` itself rather than only inferred.

    Every other proof of this refusal in the suite calls `find_candidates`
    from a *different* route — `test_add_tile.py`, `test_edit_tile.py`,
    `test_bulk_upload.py` and `test_tile_searchable.py` all exercise it from
    the write path, and `apps/web`'s own frontend test only mocks the `503`
    HTTP response rather than ever calling into this handler's own,
    uncaught-`ApiError` propagation. This drives the real `/scans` route so
    that `submit_scan`'s pass-through of `find_candidates`'s refusal — no
    `try`/`except` sits between them (see the module docstring) — is what is
    actually being checked.

    An active generation has to exist for `find_candidates` to reach the model
    at all: an empty catalogue answers `[]` before touching it (the test
    above this one). So this seeds one real Tile first, which is why the test
    needs the model too, exactly as `test_edit_tile.py`'s equivalent case does
    for its own route.
    """
    add_reference_tile(client, make_user, "RP.CMA.0009DJ.SM.0T", a_tile(61))

    monkeypatch.setattr(pipeline, "_session", None)
    monkeypatch.setattr(pipeline, "MODEL_PATH", tmp_path / "absent" / "model.onnx")

    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))
    response = submit_scan(client)

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "matching_unavailable"
    assert "make model" in response.json()["error"]["message"]


# --- AD-16's serialization ----------------------------------------------------


@needs_model
def test_two_concurrent_scans_serialize_through_the_inference_lock(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AD-16's own acceptance clause: two scans that reach the model together
    wait for each other's forward pass rather than running it in parallel.

    Nothing else in the suite would catch a regression that dropped
    `_inference_lock` or narrowed its scope — this is the one test that puts
    two real overlapping requests through it and watches the order.

    The overlap is arranged rather than hoped for, `test_remove_tile.py`'s own
    `threading.Event` technique: the first scan's `shared_vision.embed` call
    is held open until a second scan has had a real chance to reach the same
    call, and the recorded order proves the second's `"enter"` never appears
    before the first's `"exit"`.
    """
    add_reference_tile(client, make_user, "RP.CMA.0010DJ.SM.0T", a_tile(62))
    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))

    real_embed = shared_vision.embed
    order: list[str] = []
    first_entered = threading.Event()
    release_first = threading.Event()

    def watched_embed(batch: np.ndarray) -> np.ndarray:
        order.append("enter")
        if order.count("enter") == 1:
            first_entered.set()
            assert release_first.wait(LOCK_RELEASE_SECONDS), "the first scan was never released"
        result = real_embed(batch)
        order.append("exit")
        return result

    monkeypatch.setattr(shared_vision, "embed", watched_embed)

    statuses: list[int] = []
    failures: list[BaseException] = []

    def scan() -> None:
        try:
            statuses.append(submit_scan(client).status_code)
        except BaseException as raised:  # noqa: BLE001 - re-reported below
            failures.append(raised)

    first = threading.Thread(target=scan)
    first.start()
    try:
        assert first_entered.wait(LOCK_RELEASE_SECONDS), "the first scan never reached embed"

        second = threading.Thread(target=scan)
        second.start()
        try:
            # A real chance for the second scan to reach the lock while the
            # first still holds it. If the lock were dropped or scoped too
            # narrowly, the second thread's own "enter" would land here,
            # before the first has been released at all.
            time.sleep(LOCK_OVERLAP_SECONDS)
            assert order == ["enter"], order

            release_first.set()
        finally:
            second.join(LOCK_RELEASE_SECONDS)
    finally:
        release_first.set()
        first.join(LOCK_RELEASE_SECONDS)

    assert failures == [], failures
    assert statuses == [200, 200]
    # Fully interleaved, never overlapped: the second scan's own "enter" comes
    # only after the first's "exit" — one forward pass at a time.
    assert order == ["enter", "exit", "enter", "exit"]


# --- The crop rectangle ----------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"crop_width": 0}, id="zero width"),
        pytest.param({"crop_height": 0}, id="zero height"),
        pytest.param({"crop_width": -0.1}, id="negative width"),
        pytest.param({"crop_height": -0.1}, id="negative height"),
        pytest.param({"crop_x": 1.0, "crop_width": 0.1}, id="x at the ceiling"),
        pytest.param({"crop_y": 1.0, "crop_height": 0.1}, id="y at the ceiling"),
        pytest.param({"crop_x": -0.01}, id="x below zero"),
        pytest.param({"crop_y": -0.01}, id="y below zero"),
        pytest.param({"crop_x": 0.5, "crop_width": 0.6}, id="x + width past the far edge"),
        pytest.param({"crop_y": 0.5, "crop_height": 0.6}, id="y + height past the far edge"),
        # `nan`/`inf` fail every ordinary comparison as `False`, so a bounds
        # check written the obvious way lets each of these through to
        # `crop_to_rect`'s `round()` — which raises an uncaught `ValueError`
        # or, wired up wrong, would let this route answer a `500` rather than
        # its own `422`. Pydantic accepts the strings `nan`/`inf`/`-inf` as
        # ordinary floats, so these reach the handler exactly as a malformed
        # or forged request would send them, over the wire.
        pytest.param({"crop_width": float("nan")}, id="nan width"),
        pytest.param({"crop_height": float("nan")}, id="nan height"),
        pytest.param({"crop_x": float("nan")}, id="nan x"),
        pytest.param({"crop_y": float("nan")}, id="nan y"),
        pytest.param({"crop_width": float("inf")}, id="infinite width"),
        pytest.param({"crop_height": float("inf")}, id="infinite height"),
        pytest.param({"crop_x": float("inf")}, id="infinite x"),
        pytest.param({"crop_y": float("inf")}, id="infinite y"),
    ],
)
def test_a_degenerate_or_out_of_bounds_rect_is_refused(
    client: TestClient, make_user: MakeUser, overrides: dict[str, float]
) -> None:
    sign_in(client, make_user())

    response = submit_scan(client, **overrides)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_crop_rect"


def test_a_blurry_or_flat_crop_is_refused_as_low_quality(
    client: TestClient, make_user: MakeUser
) -> None:
    """FR-9 / AD-12 — a cropped region that scores below the quality gate is
    refused before matching (3.4) ever exists to see it, with a dedicated
    `422` distinct from `invalid_crop_rect`: the rectangle here is perfectly
    valid, it is the pixels inside it that fail.
    """
    sign_in(client, make_user())

    response = submit_scan(
        client, image=("scan.jpg", jpeg_bytes(a_flat_photograph()), "image/jpeg")
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "scan_quality_too_low"
    # This exact wording has no TypeScript twin — `CropScreen` renders the
    # server's own `message` verbatim rather than holding a second copy — so
    # this assertion is the only thing pinning it anywhere.
    assert response.json()["error"]["message"] == "This photo's a little blurry — try again."


def test_a_valid_full_frame_rect_is_accepted(client: TestClient, make_user: MakeUser) -> None:
    """`x=0, y=0, width=1, height=1` is the one edge case the matrix's own
    "x/y outside [0,1)" and "x+width>1" clauses both graze without covering:
    the rectangle exactly fills the image, and nothing about that is invalid.
    """
    sign_in(client, make_user())

    response = submit_scan(client, crop_x=0, crop_y=0, crop_width=1, crop_height=1)

    assert response.status_code == 200, response.text


# --- The uploaded image -----------------------------------------------------------


def test_unreadable_bytes_are_refused(client: TestClient, make_user: MakeUser) -> None:
    sign_in(client, make_user())

    response = submit_scan(client, image=("scan.jpg", b"not an image", "image/jpeg"))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "unreadable_image"


def test_an_oversized_image_is_refused_before_a_decode(
    client: TestClient, make_user: MakeUser
) -> None:
    """A header claiming more than `UPLOAD_MAX_PIXELS` (60,000,000) — the far
    tighter of AD-7's two ceilings, since this upload is untrusted content from
    a phone camera rather than an Administrator's studio asset.
    `test_add_tile.py`'s `a_png_header_claiming` argues for the technique: a
    header this large cannot honestly be produced any other way in a test.
    """
    sign_in(client, make_user())
    oversized = a_png_header_claiming(8_000, 7_501)  # 60,008,000 pixels

    response = submit_scan(client, image=("scan.png", oversized, "image/png"))

    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "image_too_large"


def test_empty_bytes_are_refused_as_unreadable(client: TestClient, make_user: MakeUser) -> None:
    sign_in(client, make_user())

    response = submit_scan(client, image=("scan.jpg", b"", "image/jpeg"))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "unreadable_image"


# --- Authorization -----------------------------------------------------------------


def test_a_signed_out_caller_is_refused(client: TestClient) -> None:
    response = submit_scan(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_a_caller_on_a_temporary_credential_is_refused(
    client: TestClient, make_user: MakeUser
) -> None:
    """`require_claimed_user`, not `current_user` alone: a session that is
    valid but still unclaimed is refused with `403 password_change_required`,
    not let through to crop a photo before the forced change (AGENTS.md
    line 18).

    The expiry is set in the future and not left `None`: login's own
    `credential_expired` check fails **closed** on a NULL expiry (`auth.py`'s
    own comment), so an unclaimed account with no deadline could never sign in
    at all, and this test would fail at `sign_in` rather than at the route it
    means to exercise.
    """
    sign_in(
        client,
        make_user(
            must_change_password=True,
            temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )

    response = submit_scan(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "password_change_required"


# --- The PNG header helper --------------------------------------------------------


def a_png_header_claiming(width: int, height: int) -> bytes:
    """A PNG whose IHDR says it is enormous and whose pixel data never arrives.

    `test_add_tile.py`'s own helper, unchanged: the pixel gate reads the
    *header* and refuses before allocating anything, so the only honest way to
    test it is a file that could never really be decoded.
    """

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )
