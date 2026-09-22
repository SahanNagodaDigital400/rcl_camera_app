"""`POST /scans` — Story 3.2's I/O matrix, through the real route.

Driven against a real PostgreSQL and a real object store for the reason every
other route test in this suite is: `require_claimed_user` is a dependency, not
a line in the handler, and the only honest way to prove a refused caller never
reaches the crop is to run the real app.

**Nothing here needs the ONNX model.** Unlike `test_add_tile.py`, this route
does not embed — there is no matching yet (Story 3.4) and nothing here should
be marked `needs_model`. If a future edit makes that mark necessary, it is a
sign this route grew scope it should not have in this story.

Pattern imitated throughout from `test_catalogue_authorization.py`: `sign_in`,
a `make_user` role, and asserting the refusal's status and code rather than
reaching for the database at all, since a dependency-level refusal never
touches it.
"""

from __future__ import annotations

import io
import struct
import zlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.user import Role

MakeUser = Callable[..., Any]

SCANS = "/scans"
LOGIN = "/auth/login"


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
def test_a_claimed_caller_submits_a_scan(
    client: TestClient, make_user: MakeUser, role: Role
) -> None:
    """FR-24 — both roles Scan is reachable by can submit a crop (not admin-only)."""
    sign_in(client, make_user(role=role))

    response = submit_scan(client)

    assert response.status_code == 202, response.text
    # No body: nothing is matched yet (3.4) and nothing is persisted yet
    # (3.5, no `Scan` table exists), so there is nothing yet to hand back.
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"


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

    assert response.status_code == 202, response.text


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
