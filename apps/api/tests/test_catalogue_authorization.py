"""Every catalogue route is Administrator-only, server-side, whatever the UI hides.

`tests/test_admin_authorization.py` proves the *rule* over the route table —
every route under `/admin/` declares `require_administrator`, and every route
declaring it is under `/admin/`, with Story 2.1's two, Story 2.2's two, Story
2.3's one, Story 2.4's one and Story 2.5's one now in its expected set. This
file proves the *behaviour* on those seven routes specifically, and the one
thing the table guard cannot see: that a refused caller leaves the database and
the object store untouched.

Story 2.5's catalogue list inverts that last claim in the way that matters
most for a read: there is nothing for it to write, and what has to hold is that
*nothing was disclosed*. A blank query on it browses the whole Catalogue, so a
guard that ran a moment too late would answer a Staff caller with every row the
product holds — which is the exfiltration AGENTS.md names as the primary
commercial threat, in one request.

The two bulk routes are worth a line of their own here, because a batch is
driven from the client and the row route answers `200` for a row it *refused* —
that is its contract. A refusal of the caller therefore has to arrive as an
envelope under a `403` or a `401` and never as a `200` carrying a report line
that says "not allowed", which a driver would paint as one bad tile and carry
on past. Both halves are asserted below, for both routes.

For the removal that claim is inverted and is the stronger half: there is a Tile
in the catalogue when the refused call arrives, so "nothing was written" becomes
"the Tile, its images, its embeddings and its objects are all still there".

That second half matters more here than it did for Story 1.8's user write. The
add path decodes images, runs 16 forward passes and writes two objects per
image before the transaction opens — so "the refusal wrote nothing" is a claim
about a longer and more expensive sequence, and the refusal has to come from
the dependency, before any of it.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import psycopg
import pytest
import shared_vision
from fastapi.testclient import TestClient
from PIL import Image
from shared_schema.user import Role
from shared_vision import pipeline

MakeUser = Callable[..., Any]

ADD_TILE = "/admin/tiles"
BULK_PLAN = "/admin/tiles/bulk/plan"
BULK_ROW = "/admin/tiles/bulk/row"
LOGIN = "/auth/login"

#: The removal's refusals need a Tile to fail to remove, and putting one in the
#: catalogue runs the real embedding path. Every other test in this file is
#: refused before a byte is decoded and needs no artifact at all.
needs_model = pytest.mark.skipif(
    not pipeline.MODEL_PATH.exists(),
    reason="model not downloaded; run `make model`",
)


def an_image() -> bytes:
    rng = np.random.default_rng(3)
    image = Image.fromarray(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8), "RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


REFUSED_FIELDS = {"code": "RP.CMA.0001DJ.SM.0T", "size": "45X90", "category": "CREMA MARMOL"}

#: The same Tile as `REFUSED_FIELDS`, as a bulk manifest of one row.
REFUSED_MANIFEST = b"file,code,size,category\na.jpg,RP.CMA.0001DJ.SM.0T,45X90,CREMA MARMOL\n"


def post_tile(client: TestClient) -> Any:
    return client.post(
        ADD_TILE,
        data=REFUSED_FIELDS,
        files=[("images", ("reference.jpg", an_image(), "image/jpeg"))],
    )


def get_image(client: TestClient) -> Any:
    return client.get(f"/admin/tiles/{uuid4()}/images/{uuid4()}")


def patch_tile(client: TestClient) -> Any:
    """Story 2.2's edit, with a real image part.

    The id names no Tile, deliberately: a handler that ran would answer `404`,
    and the dependency answers `403` or `401` first. That difference is the
    whole of "the authorization is a dependency, never a line in the handler".
    """
    return client.patch(
        f"{ADD_TILE}/{uuid4()}",
        data=REFUSED_FIELDS,
        files=[("images", ("reference.jpg", an_image(), "image/jpeg"))],
    )


def post_bulk_plan(client: TestClient) -> Any:
    """Story 2.4's first phase, with a real manifest and a real file name.

    Driven with both, not an empty body: refusing `{}` would be refusing a
    malformed request and would show nothing about the authorization. The
    manifest names one valid row, so a handler that ran at all would answer a
    plan naming a Code — which is catalogue data a Staff caller must not see.
    """
    return client.post(
        BULK_PLAN,
        files=[("manifest", ("codes.csv", REFUSED_MANIFEST, "text/csv"))],
        data={"names": ["a.jpg"]},
    )


def post_bulk_row(client: TestClient) -> Any:
    """Story 2.4's second phase, with a real image part.

    A batch is driven from the client, so this route is reachable on its own
    and carries the whole of one add — which is why it needs its own refusal
    rather than inheriting the plan's. A handler that ran at all would write a
    Tile.
    """
    return client.post(
        BULK_ROW,
        data=REFUSED_FIELDS,
        files=[("image", ("a.jpg", an_image(), "image/jpeg"))],
    )


def lookup_tile(client: TestClient) -> Any:
    return client.get(f"{ADD_TILE}/lookup", params={"code": REFUSED_FIELDS["code"]})


def search_tiles(client: TestClient) -> Any:
    """Story 2.5's catalogue list (FR-18), with a `q` that matches `SEEDED_CODE`."""
    return client.get(ADD_TILE, params={"q": "CMA"})


def browse_tiles(client: TestClient) -> Any:
    """The same route with no `q` at all — the whole Catalogue in one answer.

    Separate from `search_tiles` because it is the shape that would leak most:
    a blank query browses everything (EXPERIENCE.md:35), so a guard that ran
    only when a query was present would hand a Staff caller the entire
    Catalogue, which is precisely this product's primary commercial threat.
    """
    return client.get(ADD_TILE)


#: A Tile the refused caller must not be told about, seeded **without** an
#: embedding.
#:
#: The point is that "nothing was disclosed" is a real claim. Against an empty
#: catalogue a handler that ran would answer `[]`, and every body assertion
#: below would pass with `require_administrator` deleted — the status would be
#: the only thing still pinning the guard. With a row in the table a handler
#: that ran answers that row, and the Code is in the response text.
#:
#: Two literal statements rather than `post_tile`, because the add path runs
#: sixteen forward passes and would put `@needs_model` on an authorization test
#: — which is the one kind of test that must never be skipped on a machine
#: missing a model artifact.
SEEDED_CODE = "RP.CMA.0001DJ.SM.0T"

_SEED_SIZE = """
INSERT INTO tile_size (name) VALUES (%s)
ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
RETURNING id
"""

_SEED_TILE = """
INSERT INTO tile (code, size_id) VALUES (%s, %s)
"""


@pytest.fixture
def a_seeded_tile(conn: psycopg.Connection) -> str:
    """One Tile in the catalogue, by Code. See `SEEDED_CODE`."""
    row = conn.execute(_SEED_SIZE, ("45X90",)).fetchone()
    assert row is not None
    conn.execute(_SEED_TILE, (SEEDED_CODE, row["id"]))
    return SEEDED_CODE


def delete_tile(client: TestClient, tile_id: str | None = None) -> Any:
    """Story 2.3's removal.

    The id names no Tile unless one is given, for `patch_tile`'s reason: a
    handler that ran would answer `404`, and the dependency answers `403` or
    `401` first.
    """
    return client.delete(f"{ADD_TILE}/{tile_id or uuid4()}")


def sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


#: The three counts, written out rather than built from a table name.
#: `tests/test_source_guards.py` forbids SQL assembled from a value — in tests
#: as firmly as in routes, because that is where the habit starts.
_COUNTS = (
    "SELECT count(*) AS total FROM tile",
    "SELECT count(*) AS total FROM reference_image",
    "SELECT count(*) AS total FROM reference_embedding",
)


def nothing_was_written(conn: psycopg.Connection, storage_root: Path) -> None:
    for statement in _COUNTS:
        row = conn.execute(statement).fetchone()
        assert row is not None
        assert row["total"] == 0, statement
    # AD-6/AD-9: the store is reached only through this service, so a refused
    # caller reaching it at all would mean the guard ran too late.
    assert [path for path in storage_root.rglob("*") if path.is_file()] == []


# --- Staff -------------------------------------------------------------------


def test_a_staff_caller_is_refused_the_add_and_writes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    storage_root: Path,
    make_user: MakeUser,
    audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
) -> None:
    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))

    response = post_tile(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "administrator_required"
    nothing_was_written(conn, storage_root)
    assert [r for r in audit_rows(conn) if r["action"] == "catalogue_tile_added"] == []


def test_a_staff_caller_is_refused_the_image_read(client: TestClient, make_user: MakeUser) -> None:
    sign_in(client, make_user(role=Role.STAFF))

    response = get_image(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "administrator_required"


def test_a_staff_caller_is_refused_the_edit_and_writes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    storage_root: Path,
    make_user: MakeUser,
    audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
) -> None:
    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))

    response = patch_tile(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "administrator_required"
    nothing_was_written(conn, storage_root)
    assert [r for r in audit_rows(conn) if r["action"] == "catalogue_tile_edited"] == []


@pytest.mark.parametrize("send", [post_bulk_plan, post_bulk_row])
def test_a_staff_caller_is_refused_the_bulk_upload_and_writes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    storage_root: Path,
    make_user: MakeUser,
    audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
    send: Callable[[TestClient], Any],
) -> None:
    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))

    response = send(client)

    # An envelope under a `403`, not a `200` carrying a plan or a report line
    # that says "refused". The row route answers `200` for a row it refused —
    # that is its contract — so a role check made inside it rather than as a
    # dependency would be painted by a driver as one bad tile.
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "administrator_required"
    assert "items" not in response.text
    assert "status" not in response.text
    nothing_was_written(conn, storage_root)
    assert [r for r in audit_rows(conn) if r["action"] == "catalogue_tile_added"] == []


def test_a_staff_caller_is_refused_the_catalogue_and_is_told_nothing(
    client: TestClient, make_user: MakeUser, a_seeded_tile: str
) -> None:
    # A read, and the one most worth refusing: this route answers the whole
    # Catalogue in one body. Catalogue exfiltration through a compromised
    # account is this product's primary commercial threat (AGENTS.md Policy),
    # and the Catalogue screen's door being role-conditional is a courtesy on
    # top of this, never the control.
    #
    # **There is a Tile in the table when the refused call arrives**
    # (`a_seeded_tile`), which is what makes every assertion below say
    # something: against an empty catalogue a handler that ran would answer
    # `[]`, and the body checks would pass with the dependency deleted.
    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))

    for send in (search_tiles, browse_tiles):
        response = send(client)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "administrator_required"
        # The seeded Code is the assertion that actually pins the guard: a
        # handler that ran would have put it in this body, under either shape
        # of the request.
        assert a_seeded_tile not in response.text
        # Not "the array is empty" — the body is an envelope and carries no
        # array at all.
        assert set(response.json()) == {"error"}
        # The `Tile` contract's own field names, minus `code`, which the
        # envelope carries as a key of its own. Any of them in the body would
        # mean a row had been serialized.
        for leaked in ("size", "category", "reference_images", "face_number"):
            assert leaked not in response.text, leaked


def test_a_staff_caller_is_refused_the_lookup(client: TestClient, make_user: MakeUser) -> None:
    # A read, and still Administrator-only: catalogue exfiltration through a
    # compromised account is this product's primary commercial threat, and a
    # route that answered a Code with a Tile would be a way to walk the
    # Catalogue one guess at a time.
    sign_in(client, make_user(role=Role.STAFF))

    response = lookup_tile(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "administrator_required"


def test_a_staff_callers_image_is_never_decoded(
    client: TestClient,
    conn: psycopg.Connection,
    storage_root: Path,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The refusal comes from a dependency, which FastAPI resolves before the
    # handler runs at all — so a Staff caller's file is never sniffed, never
    # colour-managed and never embedded. That is the difference between an
    # authorization boundary and a check inside a handler, and it is what
    # stops an unauthorized caller costing tens of seconds of CPU a request.
    #
    # Driven with a **real image part**, not an empty body: refusing `{}`
    # would be refusing a malformed request and would show nothing at all
    # about the decode.
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a refused caller's bytes reached shared_vision")

    monkeypatch.setattr(shared_vision, "intake_image", refuse)
    sign_in(client, make_user(role=Role.STAFF))

    for send in (post_tile, patch_tile, post_bulk_plan, post_bulk_row):
        response = send(client)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "administrator_required"
        nothing_was_written(conn, storage_root)


def test_the_refusal_precedes_the_request_body_being_validated(
    client: TestClient, conn: psycopg.Connection, storage_root: Path, make_user: MakeUser
) -> None:
    # The sibling claim, and all this one shows: a Staff caller who sends
    # nothing at all is told `403` and not `422`.
    sign_in(client, make_user(role=Role.STAFF))

    response = client.post(ADD_TILE, data={})

    assert response.status_code == 403
    nothing_was_written(conn, storage_root)


# --- Signed out ---------------------------------------------------------------


def test_a_signed_out_caller_is_refused_the_add_and_writes_nothing(
    client: TestClient, conn: psycopg.Connection, storage_root: Path
) -> None:
    response = post_tile(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    nothing_was_written(conn, storage_root)


def test_a_signed_out_caller_is_refused_the_image_read(client: TestClient) -> None:
    response = get_image(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_a_signed_out_caller_is_refused_the_edit_and_writes_nothing(
    client: TestClient, conn: psycopg.Connection, storage_root: Path
) -> None:
    response = patch_tile(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    nothing_was_written(conn, storage_root)


@pytest.mark.parametrize("send", [post_bulk_plan, post_bulk_row])
def test_a_signed_out_caller_is_refused_the_bulk_upload_and_writes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    storage_root: Path,
    send: Callable[[TestClient], Any],
) -> None:
    response = send(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert "items" not in response.text
    assert "status" not in response.text
    nothing_was_written(conn, storage_root)


def test_a_signed_out_caller_is_refused_the_catalogue_and_is_told_nothing(
    client: TestClient, a_seeded_tile: str
) -> None:
    # The same non-vacuity as the staff twin above: there is a Tile to disclose,
    # so "nothing was disclosed" is a claim about the guard rather than about an
    # empty table.
    for send in (search_tiles, browse_tiles):
        response = send(client)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
        assert a_seeded_tile not in response.text
        assert set(response.json()) == {"error"}
        for leaked in ("size", "category", "reference_images", "face_number"):
            assert leaked not in response.text, leaked


def test_a_signed_out_caller_is_refused_the_lookup(client: TestClient) -> None:
    response = lookup_tile(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# --- The two states between signed in and allowed -----------------------------


def test_an_administrator_on_an_unclaimed_temporary_credential_is_refused(
    client: TestClient, conn: psycopg.Connection, storage_root: Path, make_user: MakeUser
) -> None:
    # `require_administrator` chains on the forced-change gate, so a credential
    # that travelled by note cannot be used to write the Catalogue before a
    # real password is set.
    account = make_user(role=Role.ADMIN, must_change_password=True)
    conn.execute(
        "UPDATE users SET temp_credential_expires_at = now() + interval '72 hours' WHERE id = %s",
        (account.id,),
    )
    sign_in(client, account)

    response = post_tile(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "password_change_required"
    nothing_was_written(conn, storage_root)


def test_an_administrator_deactivated_mid_session_is_refused_as_unauthenticated(
    client: TestClient, conn: psycopg.Connection, storage_root: Path, make_user: MakeUser
) -> None:
    # AD-3: `lookup_session` re-reads `active` on every request, so the
    # revocation lands on the very next one with no sign-out in between.
    account = make_user(role=Role.ADMIN)
    sign_in(client, account)
    conn.execute("UPDATE users SET active = false WHERE id = %s", (account.id,))

    response = post_tile(client)

    assert response.status_code == 401
    nothing_was_written(conn, storage_root)


def test_an_administrator_demoted_mid_session_is_refused_on_the_next_request(
    client: TestClient, conn: psycopg.Connection, storage_root: Path, make_user: MakeUser
) -> None:
    account = make_user(role=Role.ADMIN)
    sign_in(client, account)
    conn.execute("UPDATE users SET role = %s WHERE id = %s", (Role.STAFF.value, account.id))

    response = post_tile(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "administrator_required"
    nothing_was_written(conn, storage_root)


@pytest.mark.parametrize(
    "send",
    [
        post_tile,
        get_image,
        patch_tile,
        lookup_tile,
        delete_tile,
        post_bulk_plan,
        post_bulk_row,
        search_tiles,
    ],
)
def test_every_refusal_is_uncacheable(
    client: TestClient, make_user: MakeUser, send: Callable[[TestClient], Any]
) -> None:
    # Catalogue exfiltration through a compromised account is this product's
    # primary commercial threat; a refusal or a reference image left in a
    # shared cache is a copy outside the audit trail.
    sign_in(client, make_user(role=Role.STAFF))

    assert send(client).headers["cache-control"] == "no-store"


# --- The removal (Story 2.3) --------------------------------------------------
# The inverse claim, and the stronger one: there *is* a Tile when the refused
# call arrives, so what has to hold is not "nothing was written" but "nothing
# was taken away" — from the database and from the object store alike.


@pytest.fixture
def a_catalogued_tile(client: TestClient, make_user: MakeUser) -> Any:
    """One Tile, added by an Administrator whose session is then replaced.

    Returned as the id a later caller tries and fails to remove. The sign-in
    below overwrites the admin session cookie, so the refused caller really is
    the only session the request carries.
    """
    sign_in(client, make_user(role=Role.ADMIN, name="Nadeesha Silva"))
    response = post_tile(client)
    assert response.status_code == 201, response.text
    return response.json()


def nothing_was_removed(conn: psycopg.Connection, storage_root: Path) -> None:
    """The one Tile, its one image, its 16 views and its two objects, all intact.

    Sixteen because AD-13 embeds sixteen views of every Reference Image; two
    objects because each one is stored as a source and a derivative.
    """
    expected = (1, 1, 16)
    for statement, total in zip(_COUNTS, expected, strict=True):
        row = conn.execute(statement).fetchone()
        assert row is not None
        assert row["total"] == total, statement
    assert len([path for path in storage_root.rglob("*") if path.is_file()]) == 2


@needs_model
def test_a_staff_caller_is_refused_the_removal_and_removes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    storage_root: Path,
    make_user: MakeUser,
    a_catalogued_tile: Any,
    audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
) -> None:
    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))

    response = delete_tile(client, a_catalogued_tile["id"])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "administrator_required"
    nothing_was_removed(conn, storage_root)
    assert [r for r in audit_rows(conn) if r["action"] == "catalogue_tile_removed"] == []


@needs_model
def test_a_signed_out_caller_is_refused_the_removal_and_removes_nothing(
    client: TestClient,
    conn: psycopg.Connection,
    storage_root: Path,
    a_catalogued_tile: Any,
    audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
) -> None:
    client.cookies.clear()

    response = delete_tile(client, a_catalogued_tile["id"])

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    nothing_was_removed(conn, storage_root)
    assert [r for r in audit_rows(conn) if r["action"] == "catalogue_tile_removed"] == []


def test_a_staff_caller_is_refused_the_removal_before_any_row_is_read(
    client: TestClient, conn: psycopg.Connection, storage_root: Path, make_user: MakeUser
) -> None:
    # The id names no Tile, so a handler that ran would answer `404`. The
    # dependency answers `403` first, which is the whole of "the authorization
    # is a dependency, never a line in the handler" — and needs no Tile, and
    # therefore no model artifact, to state.
    sign_in(client, make_user(role=Role.STAFF))

    response = delete_tile(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "administrator_required"
    nothing_was_written(conn, storage_root)


def test_a_signed_out_caller_is_refused_the_removal(
    client: TestClient, conn: psycopg.Connection, storage_root: Path
) -> None:
    response = delete_tile(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    # The half the route-table guard cannot see, as on every other refusal in
    # this file: the caller reached neither the database nor the store.
    nothing_was_written(conn, storage_root)


# --- The Scan surface's own image route (Story 3.4) ----------------------------
# `GET /tiles/{tile_id}/images/{image_id}` is gated by `require_claimed_user`
# alone, never `require_administrator` — a Candidate card is not an admin
# surface, and Scan is reachable by every authenticated role. This file's own
# claim inverts here: a *claimed* session of either role must reach it rather
# than be refused, and only a signed-out caller or a pair naming no row is
# turned away — mirroring `test_add_tile.py`'s own coverage of the admin
# route's success, refusal and mismatched-pair cases over this second door.


def get_scan_image(
    client: TestClient, tile_id: str | None = None, image_id: str | None = None
) -> Any:
    return client.get(f"/tiles/{tile_id or uuid4()}/images/{image_id or uuid4()}")


@needs_model
@pytest.mark.parametrize("role", [Role.STAFF, Role.ADMIN])
def test_a_claimed_session_of_either_role_reaches_the_scan_image_route(
    client: TestClient, make_user: MakeUser, a_catalogued_tile: Any, role: Role
) -> None:
    # The sign-in below overwrites the admin session `a_catalogued_tile` left
    # behind, so the claimed caller under test really is the only session the
    # request carries — `a_catalogued_tile`'s own reason.
    sign_in(client, make_user(role=role, name="Kasun Perera"))

    response = get_scan_image(
        client, a_catalogued_tile["id"], a_catalogued_tile["reference_images"][0]["id"]
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"


def test_a_signed_out_caller_is_refused_the_scan_image_route(client: TestClient) -> None:
    response = get_scan_image(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@needs_model
def test_a_mismatched_pair_is_not_found_on_the_scan_image_route(
    client: TestClient, make_user: MakeUser, a_catalogued_tile: Any
) -> None:
    # The id pair names no row — a real Tile paired with an image id that is
    # not one of its own — which is the same "does not exist" fact
    # `test_an_image_id_paired_with_the_wrong_tile_is_not_found` proves for the
    # admin route, over the one lookup helper both routes share.
    sign_in(client, make_user(role=Role.STAFF, name="Kasun Perera"))

    response = get_scan_image(client, a_catalogued_tile["id"], str(uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_not_found"
