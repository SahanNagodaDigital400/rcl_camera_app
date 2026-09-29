"""`/admin/markers` — registering, correcting and withdrawing a physical ruler.

A **Marker** is an object of known printed size a staff member lays on a tile
before photographing it, so `api.measure` can turn pixels into millimetres.
This file is about the Administrator's half: the writes, their refusals, and
the audit entries that make a silently re-measured card traceable.

**The dimensions are what these tests are really guarding.** They scale every
measurement every staff member takes with that card. A `54mm` stored as `540mm`
produces confident answers wrong by a factor of ten and fails nowhere a reader
can see — the geometry stays valid and the tile still rectifies as a rectangle.
So the bounds are asserted at the API, the both-or-neither fiducial rule is
asserted at the API *and* left to the database, and every write is asserted to
land in the log carrying the numbers it wrote.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from api.markers import (
    DUPLICATE_MARKER_NAME,
    INVALID_MARKER_DIMENSION,
    INVALID_MARKER_FIDUCIAL,
    INVALID_MARKER_NAME,
    MARKER_NOT_FOUND,
)
from fastapi.testclient import TestClient
from shared_schema.marker import MAX_MARKER_EDGE_MM, MIN_MARKER_EDGE_MM
from shared_schema.user import Role

LOGIN = "/auth/login"
MARKERS = "/admin/markers"

#: ISO/IEC 7810 ID-1 — a bank card, the marker most staff already carry.
CARD = {"name": "Bank card", "width_mm": 85.6, "height_mm": 53.98}

#: A printed fiducial card, which the detector can find by itself.
FIDUCIAL = {
    "name": "Rocell marker card",
    "width_mm": 100.0,
    "height_mm": 100.0,
    "aruco_dictionary": "DICT_4X4_50",
    "aruco_id": 7,
}

MakeUser = Callable[..., Any]


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


def register(client: TestClient, **overrides: Any) -> Any:
    body = {**CARD, "aruco_dictionary": None, "aruco_id": None, **overrides}
    return client.post(MARKERS, json=body)


class TestRegistering:
    def test_an_administrator_registers_a_plain_object(
        self, client: TestClient, administrator: Any
    ) -> None:
        """A bank card with nothing printed on it is a perfectly good ruler."""
        answer = register(client)

        assert answer.status_code == 201
        body = answer.json()
        assert body["name"] == "Bank card"
        assert body["width_mm"] == pytest.approx(85.6)
        assert body["height_mm"] == pytest.approx(53.98)
        assert body["aruco_dictionary"] is None
        assert body["aruco_id"] is None

    def test_an_administrator_registers_a_fiducial_card(
        self, client: TestClient, administrator: Any
    ) -> None:
        answer = client.post(MARKERS, json=FIDUCIAL)

        assert answer.status_code == 201
        assert answer.json()["aruco_dictionary"] == "DICT_4X4_50"
        assert answer.json()["aruco_id"] == 7

    def test_the_name_is_trimmed_and_collapsed_but_not_uppercased(
        self, client: TestClient, administrator: Any
    ) -> None:
        """A Size is uppercased because it is joined on. This is read by a human."""
        assert register(client, name="  Rocell   ID  badge ").json()["name"] == "Rocell ID badge"

    def test_a_duplicate_name_is_refused(self, client: TestClient, administrator: Any) -> None:
        """Two rulers of that name with different dimensions is a measurement
        that is wrong half the time, with nothing on screen to say which half.
        """
        assert register(client).status_code == 201

        answer = register(client, width_mm=90.0)

        assert answer.status_code == 409
        assert answer.json()["error"]["code"] == DUPLICATE_MARKER_NAME

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_name_is_refused(
        self, client: TestClient, administrator: Any, blank: str
    ) -> None:
        answer = register(client, name=blank)

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == INVALID_MARKER_NAME

    @pytest.mark.parametrize("edge", [MIN_MARKER_EDGE_MM - 1, MAX_MARKER_EDGE_MM + 1])
    def test_a_dimension_outside_the_bounds_is_refused(
        self, client: TestClient, administrator: Any, edge: float
    ) -> None:
        """Below the floor one pixel of corner error swamps the scale; above the
        ceiling the "marker" is larger than every tile in the catalogue.
        """
        answer = register(client, width_mm=edge)

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == INVALID_MARKER_DIMENSION

    def test_the_message_names_the_dimension_that_failed(
        self, client: TestClient, administrator: Any
    ) -> None:
        """A form with two dimension fields must say which one was wrong."""
        assert "height" in register(client, height_mm=1.0).json()["error"]["message"]

    @pytest.mark.parametrize(("dictionary", "aruco_id"), [("DICT_4X4_50", None), (None, 7)])
    def test_half_a_fiducial_declaration_is_refused(
        self, client: TestClient, administrator: Any, dictionary: str | None, aruco_id: int | None
    ) -> None:
        """A card the detector will never find, with nothing to say why."""
        answer = register(client, aruco_dictionary=dictionary, aruco_id=aruco_id)

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == INVALID_MARKER_FIDUCIAL

    def test_an_id_outside_its_family_is_refused(
        self, client: TestClient, administrator: Any
    ) -> None:
        """`DICT_4X4_50` holds ids 0-49. A card printed with 60 does not exist."""
        answer = register(client, aruco_dictionary="DICT_4X4_50", aruco_id=60)

        assert answer.status_code == 422
        assert answer.json()["error"]["code"] == INVALID_MARKER_FIDUCIAL

    def test_an_unknown_dictionary_is_refused(self, client: TestClient, administrator: Any) -> None:
        assert register(client, aruco_dictionary="DICT_NOPE", aruco_id=1).status_code == 422

    def test_a_key_outside_the_contract_is_refused(
        self, client: TestClient, administrator: Any
    ) -> None:
        """Closed shape: a caller writing against a contract that does not exist
        is told so, rather than having the key silently dropped.
        """
        assert client.post(MARKERS, json={**CARD, "size": "60X30"}).status_code == 422


class TestReading:
    def test_the_list_is_ordered_by_name(self, client: TestClient, administrator: Any) -> None:
        for name in ("Zebra card", "Alpha card", "Middle card"):
            assert register(client, name=name).status_code == 201

        names = [row["name"] for row in client.get(MARKERS).json()]

        assert names == ["Alpha card", "Middle card", "Zebra card"]

    def test_an_empty_register_is_not_an_error(
        self, client: TestClient, administrator: Any
    ) -> None:
        """The Scan screen renders this as no Measure control — not a failure."""
        answer = client.get(MARKERS)

        assert answer.status_code == 200
        assert answer.json() == []

    def test_staff_read_the_same_rows_from_the_scan_surface(
        self, client: TestClient, administrator: Any, make_user: MakeUser
    ) -> None:
        """One owner for the table: `GET /scans/markers` is the same reader.

        Staff pick a ruler; only an Administrator registers one. If these two
        could drift, a staff member would measure with a card whose stored
        dimensions are not the ones the register shows.
        """
        assert register(client).status_code == 201
        client.post("/auth/logout")

        sign_in(client, make_user(role=Role.STAFF))
        answer = client.get("/scans/markers")

        assert answer.status_code == 200
        assert [row["name"] for row in answer.json()] == ["Bank card"]


class TestCorrecting:
    def test_an_unsent_field_keeps_its_value(self, client: TestClient, administrator: Any) -> None:
        """Partial, and `model_fields_set` is what makes it partial."""
        marker_id = client.post(MARKERS, json=FIDUCIAL).json()["id"]

        answer = client.patch(f"{MARKERS}/{marker_id}", json={"name": "Renamed card"})

        assert answer.status_code == 200
        assert answer.json()["name"] == "Renamed card"
        # The fiducial survives a rename. Treating "absent" as "null" here
        # would silently un-register the card's marker.
        assert answer.json()["aruco_dictionary"] == "DICT_4X4_50"
        assert answer.json()["aruco_id"] == 7

    def test_an_explicit_null_clears_the_fiducial(
        self, client: TestClient, administrator: Any
    ) -> None:
        """A detected card becomes a tapped one. Both are legitimate."""
        marker_id = client.post(MARKERS, json=FIDUCIAL).json()["id"]

        answer = client.patch(
            f"{MARKERS}/{marker_id}", json={"aruco_dictionary": None, "aruco_id": None}
        )

        assert answer.status_code == 200
        assert answer.json()["aruco_dictionary"] is None
        assert answer.json()["aruco_id"] is None

    def test_half_a_pair_completes_against_the_stored_row(
        self, client: TestClient, administrator: Any
    ) -> None:
        """Sending only the id, on a Marker that already declares a dictionary,
        is a complete declaration once merged — refusing it would make a legal
        correction impossible.
        """
        marker_id = client.post(MARKERS, json=FIDUCIAL).json()["id"]

        answer = client.patch(f"{MARKERS}/{marker_id}", json={"aruco_id": 12})

        assert answer.status_code == 200
        assert answer.json()["aruco_id"] == 12
        assert answer.json()["aruco_dictionary"] == "DICT_4X4_50"

    def test_a_corrected_dimension_is_stored(self, client: TestClient, administrator: Any) -> None:
        marker_id = register(client).json()["id"]

        answer = client.patch(f"{MARKERS}/{marker_id}", json={"width_mm": 85.6, "height_mm": 54.0})

        assert answer.json()["height_mm"] == pytest.approx(54.0)

    def test_an_unknown_id_is_a_404(self, client: TestClient, administrator: Any) -> None:
        answer = client.patch(f"{MARKERS}/{uuid4()}", json={"name": "Nothing"})

        assert answer.status_code == 404
        assert answer.json()["error"]["code"] == MARKER_NOT_FOUND

    def test_renaming_onto_another_name_is_refused(
        self, client: TestClient, administrator: Any
    ) -> None:
        assert register(client, name="First").status_code == 201
        second = register(client, name="Second").json()["id"]

        answer = client.patch(f"{MARKERS}/{second}", json={"name": "First"})

        assert answer.status_code == 409
        assert answer.json()["error"]["code"] == DUPLICATE_MARKER_NAME


class TestWithdrawing:
    def test_a_removed_marker_is_gone(self, client: TestClient, administrator: Any) -> None:
        marker_id = register(client).json()["id"]

        assert client.delete(f"{MARKERS}/{marker_id}").status_code == 204
        assert client.get(MARKERS).json() == []

    def test_removal_is_not_idempotent(self, client: TestClient, administrator: Any) -> None:
        """An Administrator told "removed" about a card that was never
        registered has been told they removed something they did not — and
        would stop looking for the one that is still there.
        """
        marker_id = register(client).json()["id"]
        assert client.delete(f"{MARKERS}/{marker_id}").status_code == 204

        answer = client.delete(f"{MARKERS}/{marker_id}")

        assert answer.status_code == 404
        assert answer.json()["error"]["code"] == MARKER_NOT_FOUND


class TestAuthorization:
    """AGENTS.md Policy: enforced server-side, independent of what the UI hides."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", MARKERS),
            ("GET", MARKERS),
            ("PATCH", f"{MARKERS}/{uuid4()}"),
            ("DELETE", f"{MARKERS}/{uuid4()}"),
        ],
    )
    def test_staff_are_refused_at_every_route(
        self, client: TestClient, make_user: MakeUser, method: str, path: str
    ) -> None:
        sign_in(client, make_user(role=Role.STAFF))

        answer = client.request(method, path, json=CARD)

        assert answer.status_code == 403

    def test_a_signed_out_caller_is_refused(self, client: TestClient) -> None:
        assert client.get(MARKERS).status_code == 401

    def test_a_staff_write_leaves_nothing_behind(
        self, client: TestClient, make_user: MakeUser, administrator: Any
    ) -> None:
        """The refusal is not merely a status code — nothing is written."""
        client.post("/auth/logout")
        sign_in(client, make_user(role=Role.STAFF))
        assert client.post(MARKERS, json=CARD).status_code == 403

        client.post("/auth/logout")
        sign_in(client, administrator)
        assert client.get(MARKERS).json() == []


class TestTheAuditTrail:
    """FR-20. A silently re-measured card is the failure this trail exists for."""

    def test_registering_is_recorded_with_the_dimensions(
        self,
        client: TestClient,
        administrator: Any,
        conn: psycopg.Connection,
        audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
    ) -> None:
        register(client)

        entry = [row for row in audit_rows(conn) if row["action"] == "marker_added"][-1]

        assert entry["actor_email"] == administrator.email
        details = entry["details"]
        assert isinstance(details, dict)
        # The numbers, not just the name: this is the only place that would
        # show a card silently registered ten times too large.
        assert details["name"] == "Bank card"
        assert details["width_mm"] == pytest.approx(85.6)
        assert details["height_mm"] == pytest.approx(53.98)

    def test_correcting_is_recorded_as_an_edit(
        self,
        client: TestClient,
        administrator: Any,
        conn: psycopg.Connection,
        audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
    ) -> None:
        """A separate action from the add, so a reader following one card
        through the log can tell the two apart without parsing `details`.
        """
        marker_id = register(client).json()["id"]

        client.patch(f"{MARKERS}/{marker_id}", json={"width_mm": 90.0})

        entry = [row for row in audit_rows(conn) if row["action"] == "marker_edited"][-1]
        details = entry["details"]
        assert isinstance(details, dict)
        assert details["width_mm"] == pytest.approx(90.0)

    def test_removal_is_recorded_with_what_it_named(
        self,
        client: TestClient,
        administrator: Any,
        conn: psycopg.Connection,
        audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
    ) -> None:
        """The one event whose subject no longer exists once it is written, so
        the entry has to carry what it named by itself.
        """
        marker_id = register(client).json()["id"]

        client.delete(f"{MARKERS}/{marker_id}")

        entry = [row for row in audit_rows(conn) if row["action"] == "marker_removed"][-1]
        details = entry["details"]
        assert isinstance(details, dict)
        assert details["name"] == "Bank card"

    def test_a_refused_write_records_nothing(
        self,
        client: TestClient,
        administrator: Any,
        conn: psycopg.Connection,
        audit_rows: Callable[[psycopg.Connection], list[dict[str, object]]],
    ) -> None:
        """The log records changes (FR-20). A refusal changed nothing."""
        register(client, width_mm=1.0)

        assert [row for row in audit_rows(conn) if str(row["action"]).startswith("marker_")] == []
