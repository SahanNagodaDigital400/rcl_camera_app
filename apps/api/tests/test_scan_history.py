"""`GET /scans` — Story 3.5's read: a caller's own scan history.

`test_audit_read.py`'s own shape, scoped to one caller's rows rather than the
whole table: the order, the keyset paging and the two-answers-for-"nothing
older" distinction are `GET /admin/audit`'s own claims, restated here with
`user_id` as the added predicate every statement carries. What is new here and
has no audit-log counterpart is cross-user isolation (FR-8: a caller sees only
their own scans, never another user's) and AD-10 survival (a history entry's
snapshot renders unchanged after the Tile it matched is removed).

Every test below drives `POST /scans` and `GET /scans` through the real app,
`test_scan_submission.py`'s own reason: `require_claimed_user` is a
dependency, not a line in the handler, and the only honest way to prove a
refused caller never reaches either is to run the real app. Most tests arrange
`scan` rows directly, as the table owner, `test_audit_read.py`'s own
`_ARRANGE_ENTRY` reasoning: `api.scan` is the code under test on the write
side, and a fixture that went through it could not express an arbitrary
`created_at` or a large run without embedding real images.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageEnhance
from psycopg.types.json import Jsonb
from shared_schema.scan import HISTORY_PAGE_SIZE
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]

SCANS = "/scans"
ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"

needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)

#: A closed `ScanCandidate`, valid enough to round-trip through
#: `ScanHistoryEntry.candidates` — the shape `apps/web`'s own fixtures use.
A_CANDIDATE = {
    "tile_id": "11111111-1111-4111-8111-111111111111",
    "code": "RP.CMA.0001DJ.SM.0T",
    "size": "45X90",
    "category": "CREMA MARMOL",
    "image_id": "22222222-2222-4222-8222-222222222222",
}

_ARRANGE_SCAN = """
INSERT INTO scan (created_at, user_id, candidates_snapshot)
VALUES (%s, %s, %s)
RETURNING id
"""


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


def _arrange(
    conn: psycopg.Connection,
    user_id: Any,
    count: int,
    *,
    first_at: datetime | None = None,
    step: timedelta = timedelta(seconds=1),
    candidates: list[dict[str, Any]] | None = None,
) -> list[str]:
    """`count` scans belonging to `user_id`, oldest first, each `step` newer
    than the last. `test_audit_read.py`'s `_arrange`, restated for one column
    fewer and one predicate more.

    `first_at` defaults to a minute in the future so every arranged row sorts
    above anything a real submission in the same test could have written.

    Returns the ids in the order they were written, so `reversed(...)` is the
    order the route must answer in.
    """
    base = first_at if first_at is not None else datetime.now(UTC) + timedelta(minutes=1)
    written: list[str] = []
    for index in range(count):
        row = conn.execute(
            _ARRANGE_SCAN,
            (
                base + step * index,
                user_id,
                Jsonb(candidates if candidates is not None else []),
            ),
        ).fetchone()
        assert row is not None
        written.append(str(row["id"]))
    return written


def _read(client: TestClient, before: str | None = None) -> list[dict[str, Any]]:
    path = SCANS if before is None else f"{SCANS}?before={before}"
    response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return body


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["id"] for entry in entries]


# --- The order and its scope ---------------------------------------------------


def test_the_first_page_is_the_callers_own_scans_newest_first(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    written = _arrange(conn, account.id, 3)

    assert _ids(_read(client)) == list(reversed(written))


def test_two_scans_sharing_a_created_at_are_ordered_by_id_descending(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    shared = datetime.now(UTC) + timedelta(minutes=1)
    written = _arrange(conn, account.id, 2, first_at=shared, step=timedelta(0))

    top = _ids(_read(client))[:2]

    assert set(top) == set(written)
    assert top == sorted(written, reverse=True)


# --- Cross-user isolation (FR-8) -----------------------------------------------


def test_a_caller_sees_only_their_own_scans_never_anothers(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    mine = make_user(name="Kasun Perera")
    theirs = make_user(name="Nadeesha Silva")
    my_rows = _arrange(conn, mine.id, 2)
    their_rows = _arrange(conn, theirs.id, 2, first_at=datetime.now(UTC) + timedelta(minutes=2))

    _sign_in(client, mine)
    seen = _ids(_read(client))

    assert set(seen) == set(my_rows)
    assert set(seen).isdisjoint(their_rows)


def test_each_callers_history_is_scoped_to_their_own_session(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The pair, both directions: neither account's history leaks into the
    # other's, whichever signs in on this client second.
    first = make_user(name="Kasun Perera")
    second = make_user(name="Nadeesha Silva")
    first_rows = _arrange(conn, first.id, 1)
    second_rows = _arrange(conn, second.id, 1, first_at=datetime.now(UTC) + timedelta(minutes=2))

    _sign_in(client, first)
    assert _ids(_read(client)) == first_rows

    _sign_in(client, second)
    assert _ids(_read(client)) == second_rows


# --- Paging ---------------------------------------------------------------------


def test_a_full_page_holds_the_server_s_page_size_and_no_more(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    _arrange(conn, account.id, HISTORY_PAGE_SIZE + 10)

    assert len(_read(client)) == HISTORY_PAGE_SIZE


def test_the_next_page_repeats_nothing_and_skips_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    written = _arrange(conn, account.id, HISTORY_PAGE_SIZE + 10)
    expected = list(reversed(written))

    first = _ids(_read(client))
    second = _ids(_read(client, before=first[-1]))

    assert first + second == expected
    assert len(set(first + second)) == len(expected)


def test_an_entry_written_between_two_reads_shifts_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    written = _arrange(conn, account.id, HISTORY_PAGE_SIZE + 10)

    first = _ids(_read(client))
    interloper = _arrange(conn, account.id, 1, first_at=datetime.now(UTC) + timedelta(hours=1))[0]
    second = _ids(_read(client, before=first[-1]))

    assert len(first) == HISTORY_PAGE_SIZE
    assert set(first).isdisjoint(second)
    assert interloper not in first + second
    assert first + second == [entry for entry in reversed(written)]


def test_the_client_cannot_choose_the_page_size(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    _arrange(conn, account.id, HISTORY_PAGE_SIZE + 10)

    response = client.get(f"{SCANS}?limit=500")

    assert response.status_code == 200
    assert len(response.json()) == HISTORY_PAGE_SIZE


# --- The empty history ----------------------------------------------------------


def test_a_caller_with_no_scans_sees_an_empty_array(
    client: TestClient, make_user: MakeUser
) -> None:
    _sign_in(client, make_user())

    response = client.get(SCANS)

    assert response.status_code == 200
    assert response.json() == []


# --- The cursor's two failures ---------------------------------------------------


def test_a_cursor_naming_no_entry_is_refused(client: TestClient, make_user: MakeUser) -> None:
    _sign_in(client, make_user())

    response = client.get(f"{SCANS}?before={uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "scan_entry_not_found"
    assert response.headers["cache-control"] == "no-store"


def test_a_cursor_naming_another_users_scan_is_refused(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # The cursor is a real row — just not one of the caller's own. Treated
    # exactly as an invented id: a caller must not be able to tell "exists,
    # but is someone else's" from "does not exist" by probing this parameter.
    mine = make_user()
    theirs = make_user()
    their_row = _arrange(conn, theirs.id, 1)[0]
    _sign_in(client, mine)

    response = client.get(f"{SCANS}?before={their_row}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "scan_entry_not_found"


def test_an_exhausted_history_and_an_invented_cursor_are_not_the_same_answer(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    written = _arrange(conn, account.id, 2)
    oldest = written[0]

    assert client.get(f"{SCANS}?before={oldest}").status_code == 200
    assert client.get(f"{SCANS}?before={uuid4()}").status_code == 404


def test_a_cursor_that_is_not_a_uuid_is_refused(client: TestClient, make_user: MakeUser) -> None:
    _sign_in(client, make_user())

    response = client.get(f"{SCANS}?before=nonsense")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- Who may read it --------------------------------------------------------------


def test_an_unauthenticated_caller_is_refused(client: TestClient) -> None:
    response = client.get(SCANS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_a_caller_on_a_temporary_credential_is_refused(
    client: TestClient, make_user: MakeUser
) -> None:
    account = make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _sign_in(client, account)

    response = client.get(SCANS)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "password_change_required"


def test_an_administrator_reaches_their_own_history_too(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Never `require_administrator`: every claimed role reaches its own
    # history, exactly as it reaches `POST /scans` itself (FR-24).
    account = make_user(role=Role.ADMIN)
    _sign_in(client, account)
    written = _arrange(conn, account.id, 1)

    assert _ids(_read(client)) == written


# --- The cascade: a deleted user's own scan history goes with them --------------


def _scan_count(conn: psycopg.Connection, user_id: Any) -> int:
    row = conn.execute(
        "SELECT count(*) AS total FROM scan WHERE user_id = %s", (user_id,)
    ).fetchone()
    assert row is not None
    return int(row["total"])


def test_a_deleted_users_scans_cascade(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    """`scan.user_id ON DELETE CASCADE` — the migration's own "one real foreign
    key here". No application code deletes a `scan` row on this path
    (`DELETE /admin/users/{user_id}` never names this table); if the
    constraint were ever dropped from the migration, this is the only test in
    the suite that would notice — `test_delete_user.py`'s own cascade test
    for `sessions.user_id`, restated for this table.
    """
    target = make_user(role=Role.STAFF, name="Kasun Perera")
    _arrange(conn, target.id, 2)
    assert _scan_count(conn, target.id) == 2

    administrator = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    _sign_in(client, administrator)

    response = client.delete(f"/admin/users/{target.id}")

    assert response.status_code == 204, response.text
    assert _scan_count(conn, target.id) == 0


# --- The response's own shape -----------------------------------------------------


def test_the_response_is_never_stored(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    _arrange(conn, account.id, 1)

    assert client.get(SCANS).headers["cache-control"] == "no-store"


def test_the_body_is_a_bare_array(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    _arrange(conn, account.id, 2)

    body = client.get(SCANS).json()

    assert isinstance(body, list)


def test_an_entry_carries_its_candidates_verbatim(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    written = _arrange(conn, account.id, 1, candidates=[A_CANDIDATE])

    entry = _read(client)[0]

    assert entry["id"] == written[0]
    assert entry["candidates"] == [A_CANDIDATE]
    assert set(entry) == {"id", "created_at", "candidates"}


def test_an_entry_with_no_confident_match_carries_an_empty_array(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user()
    _sign_in(client, account)
    _arrange(conn, account.id, 1, candidates=[])

    assert _read(client)[0]["candidates"] == []


# --- Persistence through the real submission path (needs the model) -----------


def a_tile_image(seed: int, size: tuple[int, int] = (384, 384)) -> Image.Image:
    """A tile face with visible structure — `test_scan_submission.py`'s
    `a_tile` fixture, restated: per-pixel noise is not a texture to a vision
    model, so a catalogue of noise makes retrieval a coin toss.
    """
    rng = np.random.default_rng(seed)
    face = Image.new("RGB", size, tuple(int(v) for v in rng.integers(30, 220, 3)))
    pen = ImageDraw.Draw(face)
    ink = tuple(int(v) for v in rng.integers(30, 220, 3))
    period = int(rng.integers(12, 48))
    for offset in range(0, size[0], period):
        pen.rectangle([offset, 0, offset + period // 2, size[1]], fill=ink)
    grain = np.asarray(face, dtype=np.int16) + rng.integers(-12, 12, (size[1], size[0], 3))
    return Image.fromarray(np.clip(grain, 0, 255).astype(np.uint8), "RGB")


def a_photograph_of(image: Image.Image) -> Image.Image:
    width, height = image.size
    crop = image.crop((width // 8, height // 8, width * 7 // 8, height * 7 // 8))
    crop = ImageEnhance.Brightness(crop).enhance(1.12)
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def jpeg_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def add_reference_tile(
    client: TestClient, make_user: MakeUser, code: str, image: Image.Image
) -> Any:
    account = make_user(role=Role.ADMIN, name="Nadeesha Silva")
    _sign_in(client, account)
    response = client.post(
        ADD_TILE,
        data={"code": code, "size": "45X90", "category": "POLISH"},
        files=[("images", (f"{code}.jpg", jpeg_bytes(image), "image/jpeg"))],
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit_scan(client: TestClient, image: Image.Image) -> Any:
    return client.post(
        SCANS,
        data={"crop_x": 0, "crop_y": 0, "crop_width": 1, "crop_height": 1},
        files=[("image", ("scan.jpg", jpeg_bytes(image), "image/jpeg"))],
    )


@needs_model
def test_a_removed_tiles_history_entry_still_renders_its_snapshot(
    client: TestClient, make_user: MakeUser
) -> None:
    """AD-10 — a Tile removed after the fact does not touch the history entry
    that already matched it: the Code/Size/Category came from the snapshot at
    submission time, and removing the Tile cannot change a row that is no
    longer a foreign key to anything.
    """
    reference = a_tile_image(91)
    seeded = add_reference_tile(client, make_user, "RP.CMA.0091DJ.SM.0T", reference)

    account = make_user(role=Role.STAFF, name="Kasun Perera")
    _sign_in(client, account)
    submitted = submit_scan(client, a_photograph_of(reference))
    assert submitted.status_code == 200, submitted.text
    original = submitted.json()
    assert original, "the seeded tile did not come back as a candidate"

    administrator = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(client, administrator)
    removal = client.delete(f"{ADD_TILE}/{seeded['id']}")
    assert removal.status_code == 204, removal.text

    _sign_in(client, account)
    history = _read(client)

    assert len(history) == 1
    assert history[0]["candidates"] == original
