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

#: The product's own route under it, and the only one until Story 1.9.
CREATE_USER = "/admin/users"

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


# --- The guard that keeps it declared -----------------------------------------


def test_the_admin_route_table_is_not_empty() -> None:
    # A guard over an empty route list passes forever. Asserted on its own, and
    # first, because every check below is vacuously true without it — and stated
    # as non-emptiness so that Stories 1.9-1.11 adding a route cannot make it
    # fail with a message about a table that is empty when it is not.
    assert _admin_routes(create_app()) != []


def test_the_admin_route_table_is_the_one_route_this_story_serves() -> None:
    # The stricter half, separated from the vacuity guard above because it is a
    # different claim with a different lifetime: this one is *meant* to fail the
    # moment Story 1.9 adds `GET /admin/users`, and its failure means "update
    # this list", not "the guards above stopped guarding".
    routes = _admin_routes(create_app())

    assert [f"{method} {path}" for method, path, _ in routes] == [f"POST {CREATE_USER}"]


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
