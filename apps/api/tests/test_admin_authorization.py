"""`require_administrator` — the role check, and the guard that keeps it declared.

Story 1.8's second half, and the half that has to outlive the story. Written in
`test_forced_change_gate.py`'s shape, for the same reason that file is written
the way it is: an authorization rule held by each route's author is a rule the
next route forgets, and nothing fails when it does.

Three different things are checked here and none substitutes for another:

* **The check works.** A route declaring `require_administrator` refuses a
  claimed Staff session with `403 administrator_required`, writes nothing, and
  answers a claimed Administrator normally. Driven through the product's own
  route (`POST /admin/users`) as well as a throwaway one, because the guard
  below is about the route table and a live refusal is about the dependency.

* **The check is declared, in both directions.** Every served route whose path
  starts `/admin/` declares it at any depth, *and* every route that declares it
  is under `/admin/`. The second half is what makes `/admin/` mean something:
  without it the prefix is a naming convention, and an Administrator-only route
  parked somewhere else would be invisible to the first half.

* **The check is built on the gate.** `require_administrator` resolves
  `require_claimed_user`, so an Administrator still holding an admin-issued
  temporary credential is refused by Story 1.4's gate *before* the role is
  looked at — a note-borne credential cannot provision a second one — and
  `test_forced_change_gate.py` passes with no allowlist entry for `/admin/`.

AGENTS.md Policy: authorization is enforced server-side on every endpoint,
independent of what the UI hides.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

import psycopg
import pytest
from api import catalogue
from api.db import DATABASE_URL
from api.dependencies import (
    ADMINISTRATOR_REQUIRED,
    NOT_AN_ADMINISTRATOR,
    require_administrator,
    require_claimed_user,
)
from api.main import create_app
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from shared_schema.user import Role, User

#: The prefix that *is* the authorization boundary. Read off the path by the two
#: guards below, which is what makes the rule a property of the route table.
ADMIN_PREFIX = "/admin/"

#: The product's own collection under it. Two routes over the one path since
#: Story 1.9: `POST` provisions a user and `GET` lists them. Both are named from
#: this constant below, so the path is written down once.
CREATE_USER = "/admin/users"

#: The member under it, added by Story 1.10: `PATCH` edits one account's name,
#: email or role (FR-12). A second *path* rather than a third method on the one
#: above. Story 1.11 hung `DELETE` on the same path — removing an account is the
#: member resource's own verb, and inventing `/admin/users/{user_id}/delete` for
#: it would be a second path naming one row.
EDIT_USER = "/admin/users/{user_id}"

#: Story 1.11's two state verbs (FR-13). Sub-resources rather than methods,
#: because neither is a representation of the member: `POST .../deactivate`
#: takes access away and revokes every live session with it, and
#: `POST .../activate` gives the flag back and nothing else. Both carry no
#: request body at all, which is what keeps `PATCH`'s three-column contract
#: closed — a body sending `{"active": false}` is still refused there.
DEACTIVATE_USER = "/admin/users/{user_id}/deactivate"
ACTIVATE_USER = "/admin/users/{user_id}/activate"

#: Story 1.13's read (FR-21). A collection of its own rather than anything
#: hanging off `/admin/users`: an entry names an account but is not part of
#: one, and most entries name no account that still exists. The only route
#: under this prefix that writes nothing at all — which changes nothing about
#: the guards below, because the boundary is read off the path and not off the
#: verb.
AUDIT_LOG = "/admin/audit"

#: Story 2.1's two (FR-14). The first route under this prefix that takes a
#: multipart body and the first that answers with something other than JSON —
#: neither of which changes anything about the guards below, because the
#: boundary is read off the path and not off the content type. The image read
#: is nested under its Tile rather than living at `/admin/images/{id}`: a
#: Reference Image has no identity apart from the Tile it belongs to (AD-18),
#: and the pair is what the handler matches on, so an id borrowed from another
#: Tile names nothing.
ADD_TILE = "/admin/tiles"
TILE_IMAGE = "/admin/tiles/{tile_id}/images/{image_id}"

#: Story 2.2's two (FR-15). `PATCH` on the member resource, beside the `POST` on
#: the collection — the same shape `/admin/users` took in Story 1.10. The lookup
#: is a literal segment under the collection rather than a typed-UUID sibling:
#: there is no `GET /admin/tiles/{tile_id}`, so nothing can shadow it, and an
#: **exact** Code match returning one Tile is deliberately not Story 2.5's
#: catalogue list.
EDIT_TILE = "/admin/tiles/{tile_id}"
TILE_LOOKUP = "/admin/tiles/lookup"

#: Story 2.5's one (FR-18) is a `GET` on `ADD_TILE` above rather than a path of
#: its own: the Catalogue *is* the collection, and a list at
#: `/admin/tiles/search` would be a second path naming the same set of rows.
#: It takes no path parameter, so it cannot shadow either literal segment below.

#: Story 2.4's one (FR-17). A second literal segment under the collection, for
#: `TILE_LOOKUP`'s reason and with one addition of its own: it is the first
#: route in the product whose response is a *stream*, so every refusal it can
#: make has to be made before the first byte — which is precisely what the
#: guards below check by never reaching the handler at all.
BULK_UPLOAD = "/admin/tiles/bulk"

LOGIN = "/auth/login"

#: The throwaway route. Declared here and mounted on an app built here, so
#: nothing resembling it reaches the product's route table — which the guards at
#: the bottom of this file read.
GUARDED = "/admin/test-only/guarded"

MakeUser = Callable[..., Any]

#: A body the route would accept if the caller were allowed to send it. The
#: password is a repeated character rather than anything shaped like a
#: credential: AGENTS.md Policy forbids a committed credential in a fixture as
#: firmly as in source, and every caller in this file is refused before the
#: value is read at all, so nothing here is ever hashed or stored.
REFUSED_BODY = {
    "name": "Nadeesha Silva",
    "email": "nadeesha@rocell.lk",
    "role": Role.STAFF.value,
    "temporary_password": "x" * 24,
}


def _declares(route: APIRoute, dependency: Callable[..., object]) -> bool:
    """Whether `route` resolves `dependency`, at any depth of its dependency tree.

    Walked rather than matched on the handler's signature, exactly as
    `test_forced_change_gate.py` walks it: the dependency may be declared
    directly, through `dependencies=[...]`, or behind another dependency that
    wraps it, and all three are the route declaring it.
    """
    pending = list(route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        if dependant.call is dependency:
            return True
        pending.extend(dependant.dependencies)
    return False


def _api_routes(app: FastAPI) -> list[tuple[str, str, APIRoute]]:
    """Every (method, path, route) the application actually serves.

    Recursion through `original_router` is how an included router's routes are
    reached — FastAPI wraps rather than flattens — and an unrecognised route
    **fails the run** rather than being skipped, for the reason
    `test_forced_change_gate.py` gives at length: a guard whose whole purpose is
    that nothing is skipped cannot itself skip a route. A WebSocket or a
    sub-application mounted under `/admin/` would be served by the product and
    invisible to an `isinstance(route, APIRoute)` filter, and would pass both
    guards below by never reaching them.
    """
    found: list[tuple[str, str, APIRoute]] = []

    def walk(router: Any) -> None:
        for route in router.routes:
            if isinstance(route, APIRoute):
                # HEAD and OPTIONS are added by the framework, not declared by
                # anyone. A route left with nothing after that filter would fall
                # out of the table silently — checked by neither guard.
                methods = sorted((route.methods or set()) - {"HEAD", "OPTIONS"})
                if not methods:
                    raise AssertionError(
                        f"{route.path!r} declares only {sorted(route.methods or set())}, so it "
                        "is checked for require_administrator by neither direction of this "
                        "guard. Decide how a route of that shape declares the role check, and "
                        "teach _api_routes about it."
                    )
                found.extend((method, route.path, route) for method in methods)
                continue

            inner = getattr(route, "original_router", None)
            if inner is not None:
                walk(inner)
                continue

            kind = f"{type(route).__module__}.{type(route).__name__}"
            raise AssertionError(
                f"{kind} at {getattr(route, 'path', '<no path>')!r} is a route this guard does "
                "not understand, so it is checked for require_administrator by neither "
                "direction. Extend _api_routes to walk it, and decide there how a route of "
                "that kind declares the role check."
            )

    walk(app)
    return found


def _admin_routes(app: FastAPI) -> list[tuple[str, str, APIRoute]]:
    """Every served route whose path is under the authorization boundary."""
    return [entry for entry in _api_routes(app) if entry[1].startswith(ADMIN_PREFIX)]


def _undeclared_admin_routes(app: FastAPI) -> list[str]:
    """Every `/admin/` route that does not declare the role check.

    One expression, called by both the guard below and the negative control that
    proves the guard fires — written twice they would be two guards, and the one
    nobody ever sees fail would be the one that ships.
    """
    return [
        f"{method} {path}"
        for method, path, route in _admin_routes(app)
        if not _declares(route, require_administrator)
    ]


def _declared_outside_admin(app: FastAPI) -> list[str]:
    """Every route declaring the role check from outside the boundary."""
    return [
        f"{method} {path}"
        for method, path, route in _api_routes(app)
        if not path.startswith(ADMIN_PREFIX) and _declares(route, require_administrator)
    ]


def _guarded_app() -> FastAPI:
    """The product's app plus one route that declares the role check."""
    app = create_app()

    @app.get(GUARDED)
    def guarded(administrator: Annotated[User, Depends(require_administrator)]) -> dict[str, str]:
        return {"name": administrator.name}

    return app


@pytest.fixture
def guarded_client(migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A client for `_guarded_app`, on this test's migrated database.

    Mirrors `conftest.client`, https base URL included, so the `Secure` session
    cookie survives the test client's jar.
    """
    monkeypatch.setenv(DATABASE_URL, migrated_url)

    with TestClient(_guarded_app(), base_url="https://testserver") as client:
        yield client


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


def _user_count(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT count(*) AS total FROM users").fetchone()
    assert row is not None
    return int(row["total"])


# --- The role check as a unit -------------------------------------------------


def test_a_claimed_staff_session_is_refused(
    guarded_client: TestClient, make_user: MakeUser
) -> None:
    account = make_user(role=Role.STAFF, name="Kasun Perera")
    _sign_in(guarded_client, account)

    response = guarded_client.get(GUARDED)

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": ADMINISTRATOR_REQUIRED,
        "message": NOT_AN_ADMINISTRATOR,
    }


def test_the_refusal_is_never_a_401(guarded_client: TestClient, make_user: MakeUser) -> None:
    # `apps/web`'s `apiRequest` fires `notifyUnauthorized` on *status* 401, and
    # `SessionProvider` answers that by dropping the shell to the login screen.
    # A 401 here would therefore sign a perfectly good session out for asking
    # about a surface that is not theirs.
    account = make_user(role=Role.STAFF)
    _sign_in(guarded_client, account)

    assert guarded_client.get(GUARDED).status_code != 401


def test_the_refusal_returns_no_data(guarded_client: TestClient, make_user: MakeUser) -> None:
    # Never a 200, and never a partial body: the route's own handler must not run
    # at all, so nothing it would have returned can leak.
    account = make_user(role=Role.STAFF, name="Kasun Perera")
    _sign_in(guarded_client, account)

    response = guarded_client.get(GUARDED)

    assert set(response.json()) == {"error"}
    assert account.name not in response.text


def test_the_refusal_is_never_stored(guarded_client: TestClient, make_user: MakeUser) -> None:
    account = make_user(role=Role.STAFF)
    _sign_in(guarded_client, account)

    response = guarded_client.get(GUARDED)

    assert response.headers["cache-control"] == "no-store"


def test_an_administrator_reaches_the_route(
    guarded_client: TestClient, make_user: MakeUser
) -> None:
    account = make_user(role=Role.ADMIN, name="Ruwan Jayasuriya")
    _sign_in(guarded_client, account)

    response = guarded_client.get(GUARDED)

    assert response.status_code == 200
    assert response.json() == {"name": "Ruwan Jayasuriya"}


def test_the_role_is_read_per_request(
    guarded_client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AD-3: nothing is cached at sign-in, so a demotion closes the route on the
    # very next request without the user having to sign out first.
    account = make_user(role=Role.ADMIN)
    _sign_in(guarded_client, account)
    assert guarded_client.get(GUARDED).status_code == 200

    conn.execute("UPDATE users SET role = %s WHERE id = %s", (Role.STAFF.value, account.id))

    refused = guarded_client.get(GUARDED)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == ADMINISTRATOR_REQUIRED


def test_a_deactivated_administrator_is_refused_as_unauthenticated(
    guarded_client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AGENTS.md Policy: "Never let deactivating a user leave a session live —
    # revoke immediately, not just block the next login." `lookup_session` reads
    # `active` in the same breath as `role` (AD-3), so this is the sibling of the
    # demotion case above and it lands the same way: on the very next request,
    # with no sign-out in between.
    #
    # `401`, not the role check's `403`: the session itself is no longer usable,
    # so there is no caller left to have a role. That ordering matters here
    # because this is the first privileged endpoint in the product, and a
    # deactivated Administrator refused with `administrator_required` would be
    # told their *role* was the problem while their session went on working
    # everywhere else.
    account = make_user(role=Role.ADMIN)
    _sign_in(guarded_client, account)
    assert guarded_client.get(GUARDED).status_code == 200

    conn.execute("UPDATE users SET active = false WHERE id = %s", (account.id,))

    refused = guarded_client.get(GUARDED)
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "unauthorized"


def test_a_deactivated_administrator_writes_nothing_through_the_live_route(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user(role=Role.ADMIN)
    _sign_in(client, account)
    conn.execute("UPDATE users SET active = false WHERE id = %s", (account.id,))
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=REFUSED_BODY)

    assert response.status_code == 401
    assert _user_count(conn) == before


def test_no_cookie_is_refused_as_unauthenticated(guarded_client: TestClient) -> None:
    # `401`, not `403`: nobody is signed in, so there is no role to refuse.
    response = guarded_client.get(GUARDED)

    assert response.status_code == 401


# --- The live route, refused from a dependency rather than a handler ----------


def test_the_live_route_refuses_a_staff_caller(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    account = make_user(role=Role.STAFF)
    _sign_in(client, account)
    before = _user_count(conn)

    response = client.post(CREATE_USER, json=REFUSED_BODY)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED
    assert _user_count(conn) == before


def test_the_live_route_refuses_before_the_body_is_validated(
    client: TestClient, make_user: MakeUser
) -> None:
    # The refusal comes from a dependency, which FastAPI resolves before it
    # builds the handler's arguments — so a Staff caller who sends nothing at all
    # is still told `403` and not `422`. That ordering is the difference between
    # an authorization boundary and a check inside a handler, and it is the only
    # thing here that can see it.
    account = make_user(role=Role.STAFF)
    _sign_in(client, account)

    response = client.post(CREATE_USER, json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED


def test_the_edit_route_refuses_a_staff_caller_and_writes_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Story 1.10's route, through the same dependency. The refusal is worth
    # asserting on the *live* route as well as on the throwaway one above,
    # because a route that forgot the dependency would still be caught by the
    # route-table guard and would *not* be caught by any behavioural test unless
    # one existed — and this is the first route in the product a Staff caller
    # could use to promote themselves.
    caller = make_user(role=Role.STAFF)
    target = make_user(role=Role.STAFF, name="Kasun Perera")
    _sign_in(client, caller)

    # Read before the refusal as well as after, so "writes nothing" is a
    # comparison rather than a restatement of what the fixture created.
    before = conn.execute("SELECT * FROM users WHERE id = %s", (target.id,)).fetchone()
    assert before is not None

    response = client.patch(f"/admin/users/{target.id}", json={"role": Role.ADMIN.value})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED

    after = conn.execute("SELECT * FROM users WHERE id = %s", (target.id,)).fetchone()
    assert after is not None
    # Every column, `updated_at` included. Naming only the three the route may
    # write would leave the timestamp unasserted — and a handler that ran far
    # enough to touch it before being refused is a handler whose authorization is
    # not a dependency, which is the whole claim this test makes.
    assert dict(after) == dict(before)


def test_the_edit_route_refuses_a_staff_caller_before_the_body_is_validated(
    client: TestClient, make_user: MakeUser
) -> None:
    # As above for `POST`: the dependency resolves before the handler's arguments
    # are built, so an empty body — which `EditUserRequest` refuses with a 422 —
    # is still answered `403`. That ordering is the difference between an
    # authorization boundary and a check inside a handler.
    caller = make_user(role=Role.STAFF)
    target = make_user(role=Role.STAFF)
    _sign_in(client, caller)

    response = client.patch(f"/admin/users/{target.id}", json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED


def test_the_destructive_routes_refuse_a_staff_caller_and_write_nothing(
    client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Story 1.11's three routes, through the same dependency, asserted on the
    # *live* routes as well as on the throwaway one above. A route that forgot
    # the dependency would be caught by the route-table guard and would **not**
    # be caught by any behavioural test unless one existed — and these are the
    # first routes in the product a Staff caller could use to remove somebody
    # else's access.
    #
    # One test over the three rather than three near-identical ones: the claim
    # is the same claim, and the loop states it once with the route named in
    # every assertion message.
    caller = make_user(role=Role.STAFF)
    _sign_in(client, caller)

    for label, call in (
        ("deactivate", lambda target_id: client.post(f"/admin/users/{target_id}/deactivate")),
        ("activate", lambda target_id: client.post(f"/admin/users/{target_id}/activate")),
        ("delete", lambda target_id: client.delete(f"/admin/users/{target_id}")),
    ):
        # A fresh target per verb, so a delete that leaked through could not be
        # mistaken for a refusal by the next iteration finding nothing to read.
        target = make_user(role=Role.STAFF, name="Kasun Perera")
        # Read before the refusal as well as after, so "writes nothing" is a
        # comparison rather than a restatement of what the fixture created.
        before = conn.execute("SELECT * FROM users WHERE id = %s", (target.id,)).fetchone()
        assert before is not None

        response = call(target.id)

        assert response.status_code == 403, label
        assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED, label

        after = conn.execute("SELECT * FROM users WHERE id = %s", (target.id,)).fetchone()
        assert after is not None, f"{label} deleted the row it was refused on"
        # Every column, `updated_at` included. Naming only `active` would leave
        # the timestamp unasserted — and a handler that ran far enough to touch
        # it before being refused is a handler whose authorization is not a
        # dependency, which is the whole claim this test makes.
        assert dict(after) == dict(before), label


def test_the_destructive_routes_refuse_a_staff_caller_before_any_row_is_read(
    client: TestClient, make_user: MakeUser
) -> None:
    # None of the three takes a body, so the ordering the `POST`/`PATCH` tests
    # above make with an empty body is made here with an id that names no row: a
    # handler that ran would answer `404`, and the dependency answers `403`
    # first. That difference is the whole of "the authorization is a dependency,
    # never a line in the handler".
    caller = make_user(role=Role.STAFF)
    _sign_in(client, caller)
    missing = "00000000-0000-4000-8000-000000000000"

    for label, response in (
        ("deactivate", client.post(f"/admin/users/{missing}/deactivate")),
        ("activate", client.post(f"/admin/users/{missing}/activate")),
        ("delete", client.delete(f"/admin/users/{missing}")),
    ):
        assert response.status_code == 403, label
        assert response.json()["error"]["code"] == ADMINISTRATOR_REQUIRED, label


# --- The guard that keeps it declared -----------------------------------------


def test_the_admin_route_table_is_not_empty() -> None:
    # A guard over an empty route list passes forever. Asserted on its own, and
    # first, because every check below is vacuously true without it — and stated
    # as non-emptiness so that Stories 1.9-1.11 adding a route cannot make it
    # fail with a message about a table that is empty when it is not.
    assert _admin_routes(create_app()) != []


def test_the_admin_route_table_is_the_fourteen_routes_the_product_serves() -> None:
    # The stricter half, separated from the vacuity guard above because it is a
    # different claim with a different lifetime: this one is *meant* to fail the
    # moment a story adds a route under `/admin/` — Story 1.9 added
    # `GET /admin/users`, Story 1.10 added `PATCH /admin/users/{user_id}`, and
    # Story 1.11 added the three FR-13 verbs, and Story 1.13 added
    # `GET /admin/audit`, and Story 2.1 added `POST /admin/tiles` and
    # `GET /admin/tiles/{tile_id}/images/{image_id}`, and Story 2.2 added
    # `PATCH /admin/tiles/{tile_id}` and `GET /admin/tiles/lookup`, and Story
    # 2.3 added `DELETE /admin/tiles/{tile_id}`, and Story 2.4 added
    # `POST /admin/tiles/bulk`, and Story 2.5 added `GET /admin/tiles` — and its
    # failure means "update this list", not "the guards above stopped guarding".
    #
    # The comparison is over `f"{method} {path}"`, so the removal is a *twelfth*
    # entry rather than a second method on a path already listed, the bulk
    # upload a *thirteenth* rather than a second POST on `/admin/tiles`, and
    # Story 2.5's catalogue search a *fourteenth* rather than a second entry for
    # the path `POST /admin/tiles` already occupies — it is a `GET` on the
    # collection, which is the only method that path had left.
    #
    # The count is in the name on purpose, the same way `test_audit.py` names
    # its vocabulary size: a story that adds a route has to change the name as
    # well as the list, so the number in the name can never drift from it.
    #
    # Everything else in this section covers a new route without being touched,
    # which is the property these guards were written for: both direction
    # guards, the two negative controls and the gate-chaining test are statements
    # about the route *table*, so a further route joins them by existing.
    #
    # Compared **sorted** on both sides, so the assertion states which routes are
    # served and not the order FastAPI happens to have registered them in: with
    # two methods on one path twice over, declaration order inside `api/users.py`
    # would otherwise be a thing this file silently depends on.
    routes = _admin_routes(create_app())

    assert sorted(f"{method} {path}" for method, path, _ in routes) == sorted(
        [
            f"GET {CREATE_USER}",
            f"POST {CREATE_USER}",
            f"PATCH {EDIT_USER}",
            f"DELETE {EDIT_USER}",
            f"POST {DEACTIVATE_USER}",
            f"POST {ACTIVATE_USER}",
            f"GET {AUDIT_LOG}",
            f"POST {ADD_TILE}",
            f"GET {TILE_IMAGE}",
            f"PATCH {EDIT_TILE}",
            f"DELETE {EDIT_TILE}",
            f"GET {TILE_LOOKUP}",
            f"POST {BULK_UPLOAD}",
            f"GET {ADD_TILE}",
        ]
    )


def test_the_lookup_segment_resolves_to_the_lookup_handler() -> None:
    # `GET /admin/tiles/lookup` is a literal segment under a collection that
    # also serves typed-UUID children, and both `api/catalogue.py` and
    # `test_no_registration.py` justify it with "there is no
    # `GET /admin/tiles/{tile_id}`". The day Story 2.5 adds that route *above*
    # this one, Starlette matches in registration order and `lookup` becomes a
    # tile id that fails to parse as a UUID — and every route-table test in this
    # file compares path *sets*, so none of them would notice.
    #
    # Story 2.5 added `GET /admin/tiles` and deliberately **not** that route:
    # the catalogue list carries the whole `Tile` on every row, so the screen
    # hands one to Edit Tile rather than fetching it again by id. A route with
    # no path parameter at all cannot shadow a literal segment whatever order
    # it is registered in, which is why this test stays green without being
    # touched — and why the absence is worth stating here rather than leaving
    # the next reader to re-derive it from the collector below.
    #
    # Asserted on registration *order*, not on the declared path. A dict keyed
    # by `route.path` still holds ("GET", "/admin/tiles/lookup") after a
    # shadowing sibling is registered above it, so an endpoint lookup through
    # one would stay green through exactly the regression described above.
    # Starlette matches the first route whose pattern accepts the request, so
    # the statement that survives is: no earlier GET under /admin/tiles/ takes
    # a path parameter that would swallow the literal `lookup` segment.
    ordered = [(method, path, route) for method, path, route in _api_routes(create_app())]

    lookup_at = next(
        index
        for index, (method, path, _) in enumerate(ordered)
        if (method, path) == ("GET", TILE_LOOKUP)
    )
    assert ordered[lookup_at][2].endpoint is catalogue.lookup_tile

    shadowing = [
        f"{method} {path}"
        for index, (method, path, _) in enumerate(ordered)
        if index < lookup_at
        and method == "GET"
        and path.startswith("/admin/tiles/")
        and "{" in path.removeprefix("/admin/tiles/")
    ]
    assert shadowing == [], (
        "A GET under /admin/tiles/ taking a path parameter is registered before "
        f"{TILE_LOOKUP}, so Starlette matches it first and `lookup` is read as a "
        f"tile id: {', '.join(shadowing)}. Register the literal segment above it."
    )

    edit = next(route for method, path, route in ordered if (method, path) == ("PATCH", EDIT_TILE))
    assert edit.endpoint is catalogue.edit_tile


def test_the_bulk_segment_resolves_to_the_bulk_handler() -> None:
    # The same claim as the lookup's, for the second literal segment under the
    # collection, and made separately because the shadowing route is a
    # different one: the day anything adds `POST /admin/tiles/{tile_id}` above
    # this, Starlette matches in registration order and `bulk` is read as a
    # tile id that fails to parse as a UUID. The path-set guard above compares
    # sets, so it would not notice.
    #
    # Stated over `POST` rather than over every method, because that is what
    # the shadowing would have to be: a `GET` or a `PATCH` taking a path
    # parameter cannot swallow this route's requests at all.
    ordered = [(method, path, route) for method, path, route in _api_routes(create_app())]

    bulk_at = next(
        index
        for index, (method, path, _) in enumerate(ordered)
        if (method, path) == ("POST", BULK_UPLOAD)
    )
    assert ordered[bulk_at][2].endpoint is catalogue.bulk_upload

    shadowing = [
        f"{method} {path}"
        for index, (method, path, _) in enumerate(ordered)
        if index < bulk_at
        and method == "POST"
        and path.startswith("/admin/tiles/")
        and "{" in path.removeprefix("/admin/tiles/")
    ]
    assert shadowing == [], (
        "A POST under /admin/tiles/ taking a path parameter is registered before "
        f"{BULK_UPLOAD}, so Starlette matches it first and `bulk` is read as a tile "
        f"id: {', '.join(shadowing)}. Register the literal segment above it."
    )


def test_every_admin_route_declares_the_role_check() -> None:
    offenders = _undeclared_admin_routes(create_app())

    assert offenders == [], (
        "A route under /admin/ must declare require_administrator (AGENTS.md "
        "Policy: authorization is enforced server-side on every endpoint): " + ", ".join(offenders)
    )


def test_every_route_declaring_the_role_check_is_under_admin() -> None:
    # The other direction, and the one that makes the prefix mean anything. An
    # Administrator-only route parked outside `/admin/` would satisfy the check
    # above by never being looked at, and the next reader would take the prefix
    # for a naming convention rather than a boundary.
    offenders = _declared_outside_admin(create_app())

    assert offenders == [], (
        "A route declaring require_administrator must live under /admin/, so the "
        "authorization boundary can be read off the path: " + ", ".join(offenders)
    )


def test_the_role_check_is_built_on_the_forced_change_gate() -> None:
    # Chaining on `current_user` instead would leave an admin surface reachable
    # on an unclaimed temporary credential — a credential that travelled by note
    # could then provision a second one — and would put `/admin/users` in
    # `test_forced_change_gate.py`'s allowlist, where it does not belong.
    routes = {(method, path): route for method, path, route in _api_routes(_guarded_app())}

    assert _declares(routes[("GET", GUARDED)], require_claimed_user)
    assert _declares(routes[("POST", CREATE_USER)], require_claimed_user)


def test_the_guard_catches_an_admin_route_that_forgets_the_check() -> None:
    # A guard nobody has seen fail is a guard nobody knows works. This is the
    # Story 1.9 mistake in miniature: an admin surface declared with the gate and
    # without the role check, which serves every signed-in user the user list.
    app = create_app()

    @app.get("/admin/test-only/forgetful")
    def forgetful(user: Annotated[User, Depends(require_claimed_user)]) -> dict[str, str]:
        return {"users": "everyone"}

    assert _undeclared_admin_routes(app) == ["GET /admin/test-only/forgetful"]


def test_the_guard_catches_the_role_check_declared_outside_admin() -> None:
    # The negative control for the other direction.
    app = create_app()

    @app.get("/test-only/misplaced", dependencies=[Depends(require_administrator)])
    def misplaced() -> dict[str, str]:
        return {"users": "everyone"}

    assert _declared_outside_admin(app) == ["GET /test-only/misplaced"]


def test_the_walk_refuses_a_route_type_it_does_not_understand() -> None:
    # The omission this guard cannot afford: a route the walk does not recognise
    # would be reported as fully checked while being served ungated.
    app = create_app()

    @app.websocket("/admin/test-only/socket")
    async def socket(websocket: Any) -> None:  # pragma: no cover - never connected
        await websocket.accept()

    with pytest.raises(AssertionError, match="does not understand"):
        _api_routes(app)
