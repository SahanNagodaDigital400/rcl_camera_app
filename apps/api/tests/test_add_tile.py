"""`POST /admin/tiles` — every row of Story 2.1's I/O matrix, through the real route.

Driven against a real PostgreSQL with the shipped migrations and a real object
store, because every claim here is about the seam between them: what is
written, what is not written when the request is refused, and what is left
behind either way.

The tests that embed for real are marked `needs_model` and are the slow ones —
16 forward passes per image is the point of AD-13, not an accident. Every
refusal below is reached *before* the model is touched, which is deliberate:
the cheap rules come first so that a blank Code costs a `len()` rather than a
minute of CPU.
"""

from __future__ import annotations

import io
import struct
import sys
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import psycopg
import pytest
import shared_vision
from api import catalogue
from api.storage import ObjectStore
from fastapi.testclient import TestClient
from PIL import Image, ImageCms
from shared_schema.tile import MAX_CODE_LENGTH, MAX_IMAGES_PER_REQUEST, UNKNOWN_CATEGORY
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]

ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"

CODE = "RP.CMA.0001DJ.SM.0T"
SIZE = "45X90"
CATEGORY = "CREMA MARMOL"

needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)


# --- Fixtures and helpers -----------------------------------------------------


def a_tile_photograph(seed: int = 5, size: tuple[int, int] = (320, 320)) -> Image.Image:
    """A textured patch. Deliberately not flat — a plain colour is `featureless`."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def a_blocky_photograph(seed: int = 9, block: int = 20) -> Image.Image:
    """Flat patches rather than per-pixel noise.

    The colour assertions below compare channel means across a JPEG round trip
    and a resize, and per-pixel noise loses to chroma subsampling and to
    resampling before any colour question is reached. Real tile photography is
    far closer to this: large areas of one colour.
    """
    rng = np.random.default_rng(seed)
    blocks = rng.integers(40, 215, (16, 16, 3), dtype=np.uint8)
    return Image.fromarray(np.repeat(np.repeat(blocks, block, axis=0), block, axis=1), "RGB")


def jpeg_bytes(image: Image.Image | None = None, **save: Any) -> bytes:
    buf = io.BytesIO()
    (image or a_tile_photograph()).save(buf, format="JPEG", quality=92, **save)
    return buf.getvalue()


def png_bytes(image: Image.Image | None = None) -> bytes:
    buf = io.BytesIO()
    (image or a_tile_photograph()).save(buf, format="PNG")
    return buf.getvalue()


def a_png_header_claiming(width: int, height: int) -> bytes:
    """A PNG whose IHDR says it is enormous and whose pixel data never arrives.

    The point of the pixel gate is that it reads the *header* and refuses
    before allocating anything, so the only honest way to test it is a file
    that could never be decoded at all. 400 megapixels of real image data is
    not something a test can produce, and a gate tested with a file small
    enough to decode is a gate tested after the fact.
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
        # One byte of pixel data for a picture that claims 400 megapixels. The
        # header is well-formed and the image is not: a reader that gated on
        # the header never looks at this, and a reader that decoded first would
        # be allocating 1.2 GB before it found out.
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )


def _after(before: Callable[[], None], original: Callable[..., Any]) -> Callable[..., Any]:
    """`original`, with `before` run first — a hook into a call the handler makes.

    Used to open the window a concurrent writer occupies. Substituted for
    `catalogue._prepare`, it fires after this request has passed its
    duplicate-Code pre-flight and before its own `INSERT`, which is precisely
    where a second request claiming the same Code lands.
    """

    def hooked(*args: Any, **kwargs: Any) -> Any:
        before()
        return original(*args, **kwargs)

    return hooked


def sign_in(client: TestClient, account: Any) -> None:
    assert (
        client.post(LOGIN, json={"email": account.email, "password": account.password}).status_code
        == 200
    )


@pytest.fixture
def administrator(client: TestClient, make_user: MakeUser) -> Any:
    account = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    sign_in(client, account)
    return account


def add(
    client: TestClient,
    *,
    code: str | None = CODE,
    size: str | None = SIZE,
    category: str | None = CATEGORY,
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
) -> Any:
    """`POST /admin/tiles` as multipart, with each part omitted when it is None."""
    data = {
        key: value
        for key, value in (("code", code), ("size", size), ("category", category))
        if value is not None
    }
    if files is None:
        files = [("images", ("reference.jpg", jpeg_bytes(), "image/jpeg"))]
    return client.post(ADD_TILE, data=data, files=files)


def stored_objects(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def count(conn: psycopg.Connection, table_query: str) -> int:
    row = conn.execute(table_query).fetchone()
    assert row is not None
    return int(row["total"])


TILES = "SELECT count(*) AS total FROM tile"
IMAGES = "SELECT count(*) AS total FROM reference_image"
EMBEDDINGS = "SELECT count(*) AS total FROM reference_embedding"


# --- The happy path -----------------------------------------------------------


@needs_model
def test_an_administrator_adds_a_tile(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
) -> None:
    response = add(client)

    assert response.status_code == 201, response.text
    # Catalogue data on the wire. Every sibling write asserts this on its own
    # success response, and a shared proxy or the planned service worker is
    # exactly what `no-store` is here to keep the Code out of.
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["code"] == CODE
    assert body["size"] == SIZE
    assert body["category"] == CATEGORY
    assert body["face_number"] is None
    assert len(body["reference_images"]) == 1

    # AD-13: 16 embeddings for the one image, as separate rows, never pooled.
    assert count(conn, TILES) == 1
    assert count(conn, IMAGES) == 1
    assert count(conn, EMBEDDINGS) == shared_vision.VIEWS_PER_IMAGE == 16

    # Two objects per image: the retained source a re-index reads, and AD-17's
    # capped derivative, which is the only one with a route.
    assert len(stored_objects(storage_root)) == 2

    entries = [row for row in audit_rows(conn) if row["action"] == "catalogue_tile_added"]
    assert len(entries) == 1


@needs_model
def test_the_response_carries_no_similarity_value_and_no_storage_reference(
    client: TestClient, administrator: Any
) -> None:
    # AD-20 and AD-9, asserted on the wire rather than on the model: the
    # contract has no field for either, and this is what proves nothing put one
    # there anyway.
    body = add(client).json()
    rendered = str(body).lower()

    assert set(body) == {
        "id",
        "code",
        "size",
        "category",
        "face_number",
        "reference_images",
        "created_at",
        "updated_at",
    }
    assert set(body["reference_images"][0]) == {
        "id",
        "width",
        "height",
        "featureless",
        "created_at",
    }
    for forbidden in ("score", "similarity", "source_key", "derivative_key", "url", "http"):
        assert forbidden not in rendered, rendered


@needs_model
def test_every_embedding_is_unit_norm_in_the_one_active_generation(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AD-5: unit-norm `vector(1536)`. AD-14: every row belongs to the single
    # active generation, whose stamp is the running pipeline's.
    add(client)

    generation = conn.execute(
        "SELECT id, pipeline_version, config_hash FROM embedding_generation WHERE is_active"
    ).fetchall()
    assert len(generation) == 1
    assert generation[0]["pipeline_version"] == shared_vision.PIPELINE_VERSION
    assert generation[0]["config_hash"] == shared_vision.config_hash()

    rows = conn.execute(
        "SELECT generation_id, view_kind, view_index, embedding FROM reference_embedding "
        "ORDER BY view_index"
    ).fetchall()
    assert [row["view_index"] for row in rows] == list(range(16))
    assert [row["view_kind"] for row in rows[:4]] == ["rotation"] * 4
    assert {row["view_kind"] for row in rows[4:]} == {"crop"}
    assert {row["generation_id"] for row in rows} == {generation[0]["id"]}

    for row in rows:
        vector = np.array([float(value) for value in row["embedding"].strip("[]").split(",")])
        assert vector.shape == (shared_vision.EMBED_DIM,)
        assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-4)


@needs_model
def test_a_second_generation_is_never_opened_by_a_second_add(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AD-14: a re-index is a whole new generation cut over by one pointer. An
    # ordinary add joins the active one and must never create a second.
    add(client, code="FIRST")
    add(client, code="SECOND")

    assert count(conn, "SELECT count(*) AS total FROM embedding_generation") == 1


@needs_model
def test_a_first_add_that_loses_the_generation_race_joins_the_winner(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    """Two first-adds into an empty catalogue: the loser reads the winner's row.

    `ensure_active_generation` guards its insert with a savepoint precisely so
    that the partial unique index on `is_active` decides the race and the
    losing request carries on. Nothing else in this file drives two writers
    into that window — two *sequential* adds take the early return above it —
    so without this test the recovery branch can be deleted with the suite
    green, and the losing request becomes a 500 with its objects discarded.
    """
    original = catalogue.active_generation

    def lose_the_race(connection: psycopg.Connection) -> Any:
        found = original(connection)
        # Only the read *inside* `ensure_active_generation` is the race window.
        # `add_tile` calls `active_generation` earlier as its stamp pre-flight,
        # and a row inserted there would simply be found by the read below —
        # the early return, which two sequential adds already cover.
        caller = sys._getframe(1).f_code.co_name
        if found is None and caller == "ensure_active_generation":
            # A concurrent writer, on its own committed connection, gets there
            # between this request's read and its insert.
            conn.execute(
                "INSERT INTO embedding_generation (pipeline_version, config_hash, is_active) "
                "VALUES (%s, %s, TRUE)",
                (shared_vision.PIPELINE_VERSION, shared_vision.config_hash()),
            )
        return found

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(catalogue, "active_generation", lose_the_race)
        response = add(client)

    assert response.status_code == 201, response.text
    # One generation, the winner's, and every embedding this request wrote
    # belongs to it.
    assert count(conn, "SELECT count(*) AS total FROM embedding_generation") == 1
    assert count(conn, EMBEDDINGS) == shared_vision.VIEWS_PER_IMAGE
    assert (
        count(
            conn,
            "SELECT count(*) AS total FROM reference_embedding e "
            "JOIN embedding_generation g ON g.id = e.generation_id WHERE g.is_active",
        )
        == shared_vision.VIEWS_PER_IMAGE
    )


def test_a_second_generation_with_the_same_stamp_is_allowed(
    conn: psycopg.Connection, administrator: Any
) -> None:
    """A re-index whose pipeline has not changed must not be blocked by the schema.

    An earlier draft of the migration carried a unique index over
    `(pipeline_version, config_hash)`, which made a generation per stamp — so
    recovering from a corrupted index, re-running an ingest that failed
    part-way, or rebuilding after a bulk delete were all permanently
    impossible without editing the schema. AD-14 asks for exactly one
    *active* generation, which the partial index enforces, and for nothing
    else.
    """
    conn.execute(
        "INSERT INTO embedding_generation (pipeline_version, config_hash, is_active) "
        "VALUES (%s, %s, true)",
        (shared_vision.PIPELINE_VERSION, shared_vision.config_hash()),
    )
    # The same stamp again, inactive — a rebuild in progress, before cutover.
    conn.execute(
        "INSERT INTO embedding_generation (pipeline_version, config_hash, is_active) "
        "VALUES (%s, %s, false)",
        (shared_vision.PIPELINE_VERSION, shared_vision.config_hash()),
    )

    assert count(conn, "SELECT count(*) AS total FROM embedding_generation") == 2


def test_two_active_generations_are_refused_by_the_database(
    conn: psycopg.Connection, administrator: Any
) -> None:
    # The uniqueness that *is* required: the single active pointer AD-14 cuts
    # a re-index over with. Enforced by the partial index rather than by
    # application code, so a bug cannot leave a search reading a half-built
    # generation.
    conn.execute(
        "INSERT INTO embedding_generation (pipeline_version, config_hash, is_active) "
        "VALUES (%s, %s, true)",
        ("a", "1"),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO embedding_generation (pipeline_version, config_hash, is_active) "
            "VALUES (%s, %s, true)",
            ("b", "2"),
        )


@needs_model
def test_a_missing_category_resolves_to_the_unknown_sentinel(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AD-18: a Tile whose Category cannot be recovered is indexed under an
    # explicit marker, never dropped. Both spellings of absent.
    assert add(client, category=None).json()["category"] == UNKNOWN_CATEGORY
    assert add(client, code="OTHER", category="   ").json()["category"] == UNKNOWN_CATEGORY

    assert count(conn, TILES) == 2


@needs_model
def test_casing_and_whitespace_resolve_to_one_row_not_a_near_duplicate(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # The spine's Consistency Conventions: one create-if-missing,
    # case/whitespace-normalized lookup, so two writers cannot drift into
    # `45X90` and `45x90` as two sizes nothing can join on.
    add(client, code="ONE", size=SIZE, category=CATEGORY)
    add(client, code="TWO", size=" 45x90 ", category="Crema  Marmol")

    assert count(conn, "SELECT count(*) AS total FROM tile_size") == 1
    # The UNKNOWN sentinel the migration seeds, plus the one real category.
    categories = [
        row["name"]
        for row in conn.execute("SELECT name FROM tile_category ORDER BY name").fetchall()
    ]
    assert categories == [CATEGORY, UNKNOWN_CATEGORY]


@needs_model
def test_two_tiles_in_one_size_and_category_are_two_tiles(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AD-18, the whole of it: the varying numeric segment distinguishes
    # different Tiles, not faces of one. Nothing here may merge, deduplicate or
    # report them as a conflict.
    assert add(client, code="RP.CMA.0011DJ.SM.0T").status_code == 201
    assert add(client, code="RP.CMA.0013DJ.SM.0T").status_code == 201

    assert count(conn, TILES) == 2


@needs_model
def test_several_images_each_get_their_own_sixteen(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    response = add(
        client,
        files=[
            ("images", ("a.jpg", jpeg_bytes(a_tile_photograph(1)), "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes(a_tile_photograph(2)), "image/jpeg")),
        ],
    )

    assert response.status_code == 201
    assert len(response.json()["reference_images"]) == 2
    assert count(conn, IMAGES) == 2
    assert count(conn, EMBEDDINGS) == 32


# --- Intake: content, not extension (AD-7, AGENTS.md Policy) ------------------


@needs_model
def test_a_png_named_jpg_is_accepted_because_the_content_decides(
    client: TestClient, administrator: Any
) -> None:
    response = add(client, files=[("images", ("lying.jpg", png_bytes(), "image/jpeg"))])

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("zero bytes", b""),
        ("plain text behind a .jpg", b"this is not an image, it is a note"),
        ("an executable renamed", b"MZ\x90\x00\x03" + b"\x00" * 512),
        ("a truncated JPEG", jpeg_bytes()[:64]),
    ],
)
def test_bytes_that_are_not_an_image_are_refused_and_nothing_is_stored(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    label: str,
    payload: bytes,
) -> None:
    response = add(client, files=[("images", ("reference.jpg", payload, "image/jpeg"))])

    assert response.status_code == 422, label
    assert response.json()["error"]["code"] == "unreadable_image"
    assert count(conn, TILES) == 0
    assert stored_objects(storage_root) == []


def test_a_declared_content_type_of_image_jpeg_does_not_make_it_one(
    client: TestClient, administrator: Any
) -> None:
    # The client's header is never consulted. Asserted separately from the
    # extension case because they are two different lies and only one of them
    # is the one AGENTS.md names.
    response = add(client, files=[("images", ("x.bin", b"not an image at all", "image/jpeg"))])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_image"


@needs_model
def test_an_exif_bearing_upload_is_oriented_and_then_stripped(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    object_store: ObjectStore,
) -> None:
    exif = Image.Exif()
    exif[274] = 6  # Orientation: a quarter turn
    exif[271] = "Rocell"
    exif[0x8825] = {1: "N", 2: (7.0, 0.0, 0.0)}  # GPS
    photo = a_tile_photograph(size=(400, 300))

    response = add(
        client,
        files=[("images", ("phone.jpg", jpeg_bytes(photo, exif=exif), "image/jpeg"))],
    )

    assert response.status_code == 201
    image = response.json()["reference_images"][0]
    # Applied: the quarter turn swapped the dimensions before storage.
    assert (image["width"], image["height"]) == (300, 400)

    row = conn.execute("SELECT source_key, derivative_key FROM reference_image").fetchone()
    assert row is not None
    for key in (row["source_key"], row["derivative_key"]):
        with Image.open(io.BytesIO(object_store.get(key))) as stored:
            assert not dict(stored.getexif())
            assert stored.info.get("icc_profile") is None


@needs_model
def test_the_stored_derivative_is_capped(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    object_store: ObjectStore,
) -> None:
    # AD-17: <=1280px long edge, <=300 KB, generated once at write time. Built
    # from an image well above the cap so the resize is exercised rather than
    # skipped.
    add(
        client,
        files=[
            ("images", ("big.jpg", jpeg_bytes(a_tile_photograph(size=(3000, 1800))), "image/jpeg"))
        ],
    )

    row = conn.execute(
        "SELECT derivative_key, derivative_bytes, width, height FROM reference_image"
    ).fetchone()
    assert row is not None
    data = object_store.get(row["derivative_key"])

    with Image.open(io.BytesIO(data)) as derivative:
        assert max(derivative.size) <= shared_vision.DERIVATIVE_MAX_EDGE
    # The long edge is a cap; the byte budget is a *target* with a quality
    # floor under it, because a smeared reference image is useless for the one
    # thing it exists for. This fixture meets the budget; a genuinely
    # incompressible texture would bottom out at q68 above it, by design.
    assert len(data) <= shared_vision.DERIVATIVE_MAX_BYTES
    assert row["derivative_bytes"] == len(data)
    # The retained source is the 2048px-capped asset the pipeline saw, which is
    # a different (larger) thing from the derivative.
    assert max(row["width"], row["height"]) == pipeline.DECODE_MAX_EDGE


@needs_model
@pytest.mark.skipif(
    not Path("/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc").is_file(),
    reason="no CMYK ICC profile on this machine to build a press-file fixture from",
)
def test_a_cmyk_press_file_is_stored_and_embedded_in_srgb(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    object_store: ObjectStore,
) -> None:
    """AD-15, through the route rather than through the library.

    Roughly 60% of the real reference set is CMYK press files. A naive RGB
    conversion discards the profile and both stores and embeds the wrong
    colours — and nothing raises. `shared/vision/tests/test_colour_management.py`
    holds the numbers; this holds the claim that `POST /admin/tiles` is wired
    to the path that produces them.
    """
    profile = ImageCms.getOpenProfile("/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc")
    source = a_blocky_photograph()
    press = ImageCms.profileToProfile(
        source,
        ImageCms.createProfile("sRGB"),
        profile,
        renderingIntent=pipeline.RENDERING_INTENT,
        outputMode="CMYK",
    )
    assert press is not None
    buf = io.BytesIO()
    press.save(buf, format="JPEG", quality=100, icc_profile=profile.tobytes())

    response = add(client, files=[("images", ("press.jpg", buf.getvalue(), "image/jpeg"))])
    assert response.status_code == 201

    row = conn.execute("SELECT derivative_key FROM reference_image").fetchone()
    assert row is not None
    with Image.open(io.BytesIO(object_store.get(row["derivative_key"]))) as stored:
        assert stored.mode == "RGB"
        got = np.asarray(stored.convert("RGB"), dtype=np.float32)

    want = np.asarray(source.resize(stored.size, Image.Resampling.LANCZOS), dtype=np.float32)
    naive = np.asarray(
        Image.open(io.BytesIO(buf.getvalue()))
        .convert("RGB")
        .resize(stored.size, Image.Resampling.LANCZOS),
        dtype=np.float32,
    )

    managed_error = float(np.abs(got.mean(axis=(0, 1)) - want.mean(axis=(0, 1))).max())
    naive_error = float(np.abs(naive.mean(axis=(0, 1)) - want.mean(axis=(0, 1))).max())

    # Hue and brightness both, because the green cast and the tonal crush were
    # two different bugs and the first fix did not catch the second.
    assert managed_error < 8, f"per-channel shift {managed_error:.1f}"
    assert abs(got.mean() - want.mean()) < 6

    # The negative control: the bug this exists for is visible here. Stated as
    # a ratio rather than as a level, because *how* wrong a discarded profile
    # is depends on which profile it was — this machine's generic CMYK is far
    # gentler than the press profiles in the real tree, where the measured peak
    # was 84.6 levels. What must hold everywhere is that it is much worse.
    assert naive_error > 10, f"this profile cannot see AD-15's bug ({naive_error:.1f})"
    assert naive_error > 2 * managed_error


@needs_model
def test_a_flat_reference_is_flagged_and_a_textured_one_is_not(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    """FR-19's flag, over real pixels rather than over a fixture.

    `featureless` and `pixel_std` are computed, stored and rendered, and every
    other assertion about them in the suite reads a value this code put there
    — so inverting the comparison would leave the whole suite green while
    every plain tile in the catalogue was reported as fine and every detailed
    one as unusable.

    **The flat fixture is neutral grey, and that is not an arbitrary choice.**
    The POC measures the standard deviation of the *whole RGB array*, so the
    spread between a tile's channels counts towards it exactly as spatial
    texture does: a flat but coloured tile — `(182, 176, 168)` measures 6.1 —
    is above the threshold and is not flagged, however featureless it looks.
    That is the shipped behaviour, ported unchanged, and whether the measure
    should be per-channel and on the full-size image is recorded as deferred
    work rather than decided here. This test asserts what the code does.
    """
    flat = Image.new("RGB", (400, 400), (176, 176, 176))
    flat_upload = [("images", ("flat.jpg", jpeg_bytes(flat), "image/jpeg"))]

    assert add(client, code="FLAT", files=flat_upload).status_code == 201
    assert add(client, code="TEXTURED").status_code == 201

    rows = {
        row["code"]: row
        for row in conn.execute(
            "SELECT t.code, ri.featureless, ri.pixel_std FROM reference_image ri "
            "JOIN tile t ON t.id = ri.tile_id"
        ).fetchall()
    }

    assert rows["FLAT"]["featureless"] is True
    assert rows["FLAT"]["pixel_std"] < shared_vision.FEATURELESS_STD
    assert rows["TEXTURED"]["featureless"] is False
    assert rows["TEXTURED"]["pixel_std"] > shared_vision.FEATURELESS_STD


# --- Size gates ---------------------------------------------------------------


def test_a_header_claiming_more_pixels_than_the_ceiling_is_refused_before_a_decode(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    oversized = a_png_header_claiming(20_000, 20_001)  # 400,020,000 pixels

    response = add(client, files=[("images", ("bomb.png", oversized, "image/png"))])

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_large"
    assert count(conn, TILES) == 0
    assert stored_objects(storage_root) == []


def test_a_file_above_the_byte_ceiling_is_refused(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real ceiling is 128 MB, which is not a thing to put through a test
    # suite. The bound is lowered rather than the file inflated: what is being
    # checked is that the handler stops at *its* limit, and the limit's value
    # is the constant's business.
    monkeypatch.setattr(catalogue, "MAX_IMAGE_BYTES", 1024)

    response = add(client, files=[("images", ("big.jpg", jpeg_bytes(), "image/jpeg"))])

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_large"
    assert count(conn, TILES) == 0


def test_more_images_than_the_limit_are_refused_naming_it(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    files = [
        ("images", (f"{index}.jpg", jpeg_bytes(a_tile_photograph(index)), "image/jpeg"))
        for index in range(MAX_IMAGES_PER_REQUEST + 1)
    ]

    response = add(client, files=files)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_images"
    assert str(MAX_IMAGES_PER_REQUEST) in response.json()["error"]["message"]
    assert count(conn, TILES) == 0


# --- Field refusals -----------------------------------------------------------


@pytest.mark.parametrize("code", ["", "   ", "x" * (MAX_CODE_LENGTH + 1), "bad\x00code"])
def test_a_code_the_endpoint_will_not_store_is_refused_naming_the_field(
    client: TestClient, conn: psycopg.Connection, administrator: Any, code: str
) -> None:
    response = add(client, code=code)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_code"
    assert count(conn, TILES) == 0


def test_an_absent_code_is_refused_as_a_code_and_not_as_a_shape(
    client: TestClient, administrator: Any
) -> None:
    # Left to the request model this would be `validation_error`, whose one
    # sentence names no field — the Administrator would be told the request was
    # "not in the expected shape" and left to guess which of four parts.
    response = add(client, code=None)

    assert response.json()["error"]["code"] == "invalid_code"


@pytest.mark.parametrize("size", ["", "   ", None])
def test_a_missing_or_blank_size_is_refused_naming_the_field(
    client: TestClient, conn: psycopg.Connection, administrator: Any, size: str | None
) -> None:
    response = add(client, size=size)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_size"
    assert count(conn, TILES) == 0


def test_no_image_at_all_is_refused_naming_the_field(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    response = client.post(ADD_TILE, data={"code": CODE, "size": SIZE})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_image"
    assert count(conn, TILES) == 0


# --- The duplicate ------------------------------------------------------------


@needs_model
def test_a_duplicate_code_is_a_conflict_that_writes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
) -> None:
    assert add(client).status_code == 201
    before = stored_objects(storage_root)

    response = add(client, size="60X60", category="ASTORIA")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "code_already_exists"
    # The transaction rolled back and the objects this request wrote were
    # removed: exactly the first add's two are left.
    assert count(conn, TILES) == 1
    assert count(conn, IMAGES) == 1
    assert count(conn, EMBEDDINGS) == 16
    assert stored_objects(storage_root) == before
    assert len([r for r in audit_rows(conn) if r["action"] == "catalogue_tile_added"]) == 1


@needs_model
def test_a_duplicate_code_is_refused_before_anything_is_embedded(
    client: TestClient, administrator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pre-flight `SELECT`. Without it a re-add costs 16 forward passes and
    # two object writes per image, all of it discarded — and the Administrator
    # waits a minute to be told something a query answers at once.
    assert add(client).status_code == 201

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("the duplicate reached the embedding path")

    monkeypatch.setattr(shared_vision, "embed_images", refuse)

    response = add(client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "code_already_exists"


@needs_model
def test_the_unique_constraint_is_still_what_decides_a_duplicate(
    client: TestClient, conn: psycopg.Connection, administrator: Any, storage_root: Path
) -> None:
    """The pre-flight is an optimisation; the index is the decision.

    Two requests claiming one Code can both pass the `SELECT` — neither can
    see the other's uncommitted row — so the `UniqueViolation` catch is what
    actually separates them. Driven here by writing the row *after* the
    pre-flight has run and before the insert, which is exactly the window a
    concurrent request occupies.
    """
    clash_id = uuid4()

    def insert_the_clash() -> None:
        conn.execute(
            "INSERT INTO tile (id, code, size_id) "
            "VALUES (%s, %s, (SELECT id FROM tile_size LIMIT 1))",
            (clash_id, CODE),
        )

    # A size row has to exist for the racing insert to point at, so the first
    # add is a real one under a different Code.
    assert add(client, code="FIRST").status_code == 201

    with pytest.MonkeyPatch.context() as patch:
        # Fires after the pre-flight has passed and before this request's own
        # insert — the window a concurrent writer occupies.
        patch.setattr(catalogue, "_prepare", _after(insert_the_clash, catalogue._prepare))
        response = add(client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "code_already_exists"
    # Nothing of the losing request survives: no second tile, no orphaned
    # objects beyond the first add's own two.
    assert count(conn, TILES) == 2  # the first add, and the row inserted above
    assert len(stored_objects(storage_root)) == 2


def test_a_second_image_that_fails_leaves_no_partial_tile(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad second file is refused before the first one is embedded.

    "No partial Tile" is the first half: nothing written. The second half is
    cost — every file is read and taken through intake before any of them is
    embedded, so the refusal lands in milliseconds instead of after sixteen
    forward passes on the good file that are then thrown away. Asserted by
    failing if the embedder is reached at all, which is why this test does not
    need the model artifact.
    """

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("the good image was embedded before the bad one was refused")

    monkeypatch.setattr(shared_vision, "embed_images", refuse)

    response = add(
        client,
        files=[
            ("images", ("good.jpg", jpeg_bytes(), "image/jpeg")),
            ("images", ("bad.jpg", b"", "image/jpeg")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_image"
    assert count(conn, TILES) == 0
    assert count(conn, IMAGES) == 0
    assert stored_objects(storage_root) == []


def test_the_eighth_image_passes_the_count_gate_that_the_ninth_fails(
    client: TestClient, administrator: Any
) -> None:
    """The bound is `> 8`, pinned from both sides.

    Tested at nine only, `>` and `>=` are indistinguishable — and the limit the
    screen states and the limit the server enforces would silently disagree by
    one. Eight files of unreadable bytes cost nothing and answer the only
    question here: the count gate let them through, and something further down
    refused them for what they are.
    """
    files = [("images", (f"{index}.jpg", b"not an image", "image/jpeg")) for index in range(8)]

    response = add(client, files=files)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_image"


def test_cleanup_never_replaces_the_failure_it_runs_under() -> None:
    """`_discard` on a store whose `delete` raises — the case no route can reach today.

    It runs inside the `except` of a failed add, so anything it raises replaces
    the refusal the Administrator is about to be told about: a `409` they can
    act on becomes a `500` they cannot. And the clause is per key rather than
    around the loop, so one bad key does not abandon the rest.

    Every existing caller passes a `FilesystemObjectStore`, whose `delete` is
    `unlink(missing_ok=True)` and does not raise — so both properties are
    unpinned until the S3 driver this module is a seam for arrives, which is
    the worst moment to find out. Asserted directly on the function.
    """
    attempted: list[str] = []

    class RefusingStore:
        def put(self, key: str, data: bytes) -> None:  # pragma: no cover - unused here
            raise AssertionError("cleanup does not write")

        def get(self, key: str) -> bytes:  # pragma: no cover - unused here
            raise AssertionError("cleanup does not read")

        def delete(self, key: str) -> None:
            attempted.append(key)
            # Not an `OSError`: the point is that a driver-specific failure —
            # a `botocore` client error, a `ValueError` from an SDK — is
            # swallowed too.
            raise ValueError("the provider said no")

    catalogue._discard(RefusingStore(), ["tiles/a/source.jpg", "tiles/a/view.jpg"])

    assert attempted == ["tiles/a/source.jpg", "tiles/a/view.jpg"]


# --- The model is a prerequisite, not an assumption ---------------------------


def test_a_missing_model_artifact_refuses_the_add_and_names_the_step(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Driven through the real lookup rather than a stubbed raise: what is being
    # checked is that an absent artifact becomes a named `503` instead of a
    # `500` whose message says nothing. `_session` is cleared so the lazily
    # built one from an earlier test in this process cannot answer.
    monkeypatch.setattr(pipeline, "_session", None)
    monkeypatch.setattr(pipeline, "MODEL_PATH", tmp_path / "absent" / "model.onnx")

    response = add(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "matching_unavailable"
    assert "make model" in response.json()["error"]["message"]
    assert count(conn, TILES) == 0
    assert stored_objects(storage_root) == []


def _foreign_generation(conn: psycopg.Connection) -> None:
    """The state a deployment running ahead of its re-index is in.

    A generation this build did not produce, marked active — which is what
    `active_generation` reads and refuses on.
    """
    conn.execute(
        "INSERT INTO embedding_generation (pipeline_version, config_hash, is_active) "
        "VALUES (%s, %s, true)",
        ("dinov2b-224-something-else", "0000000000000000"),
    )


@needs_model
def test_a_stamp_the_running_pipeline_did_not_produce_is_a_hard_error(
    client: TestClient, conn: psycopg.Connection, administrator: Any
) -> None:
    # AD-14: a mismatch is a hard error, not a degraded search.
    _foreign_generation(conn)

    response = add(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pipeline_stamp_mismatch"
    assert count(conn, TILES) == 0


def test_a_foreign_stamp_is_refused_before_anything_is_embedded(
    client: TestClient,
    conn: psycopg.Connection,
    administrator: Any,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read-only pre-flight, not the one inside the transaction.

    `ensure_active_generation` would refuse this add too — after sixteen
    forward passes per image and two object writes, all of it discarded, on
    every add a stamp-mismatched deployment receives. Delete the pre-flight and
    the sibling test above still passes; this one does not.
    """
    _foreign_generation(conn)

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("the stamp mismatch reached the embedding path")

    monkeypatch.setattr(shared_vision, "embed_images", refuse)

    response = add(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pipeline_stamp_mismatch"
    assert count(conn, TILES) == 0
    assert stored_objects(storage_root) == []


# --- The derivative read (AD-9, AD-17) ----------------------------------------


@needs_model
def test_the_derivative_is_served_and_the_source_has_no_route(
    client: TestClient, conn: psycopg.Connection, administrator: Any, object_store: ObjectStore
) -> None:
    created = add(client).json()
    tile_id = created["id"]
    image_id = created["reference_images"][0]["id"]

    response = client.get(f"/admin/tiles/{tile_id}/images/{image_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    # The only route in the product answering with bytes that began as an
    # upload. They were re-encoded on the way in, so the declared type is
    # true — and this is what stops a browser deciding otherwise.
    assert response.headers["x-content-type-options"] == "nosniff"

    row = conn.execute("SELECT source_key, derivative_key FROM reference_image").fetchone()
    assert row is not None
    assert response.content == object_store.get(row["derivative_key"])
    # The original is never served (AD-17). The only bytes with a route are the
    # derivative's, and they are not the source's.
    assert response.content != object_store.get(row["source_key"])


@needs_model
def test_an_image_id_paired_with_the_wrong_tile_is_not_found(
    client: TestClient, administrator: Any
) -> None:
    first = add(client, code="FIRST").json()
    second = add(client, code="SECOND").json()

    response = client.get(
        f"/admin/tiles/{first['id']}/images/{second['reference_images'][0]['id']}"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_not_found"


@needs_model
def test_a_row_whose_object_has_vanished_is_not_found(
    client: TestClient, conn: psycopg.Connection, administrator: Any, object_store: ObjectStore
) -> None:
    # The store and the database have diverged — a backup restored to one and
    # not the other, an operator clearing orphans too enthusiastically. There
    # is genuinely nothing to serve, so a `404` is honest where a `500` would
    # report it as this service failing.
    created = add(client).json()
    row = conn.execute("SELECT derivative_key FROM reference_image").fetchone()
    assert row is not None
    object_store.delete(row["derivative_key"])

    response = client.get(
        f"/admin/tiles/{created['id']}/images/{created['reference_images'][0]['id']}"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_not_found"


def test_an_unknown_pair_is_not_found(client: TestClient, administrator: Any) -> None:
    response = client.get(f"/admin/tiles/{uuid4()}/images/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_not_found"
