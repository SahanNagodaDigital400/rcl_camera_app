"""Every catalogue route is Administrator-only, server-side, whatever the UI hides.

`tests/test_admin_authorization.py` proves the *rule* over the route table —
every route under `/admin/` declares `require_administrator`, and every route
declaring it is under `/admin/`, with Story 2.1's two and Story 2.2's two now in
its expected set. This file proves the *behaviour* on those four routes
specifically, and the one thing the table guard cannot see: that a refused
caller leaves the database and the object store untouched.

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

MakeUser = Callable[..., Any]

ADD_TILE = "/admin/tiles"
LOGIN = "/auth/login"


def an_image() -> bytes:
    rng = np.random.default_rng(3)
    image = Image.fromarray(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8), "RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


REFUSED_FIELDS = {"code": "RP.CMA.0001DJ.SM.0T", "size": "45X90", "category": "CREMA MARMOL"}


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


def lookup_tile(client: TestClient) -> Any:
    return client.get(f"{ADD_TILE}/lookup", params={"code": REFUSED_FIELDS["code"]})


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

    for send in (post_tile, patch_tile):
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


@pytest.mark.parametrize("send", [post_tile, get_image, patch_tile, lookup_tile])
def test_every_refusal_is_uncacheable(
    client: TestClient, make_user: MakeUser, send: Callable[[TestClient], Any]
) -> None:
    # Catalogue exfiltration through a compromised account is this product's
    # primary commercial threat; a refusal or a reference image left in a
    # shared cache is a copy outside the audit trail.
    sign_in(client, make_user(role=Role.STAFF))

    assert send(client).headers["cache-control"] == "no-store"
