"""`require_claimed_user` — the gate, and the guard that keeps it declared.

Story 1.4's second half, and the half that has to outlive the story. Two
different things are checked here and neither substitutes for the other:

* **The gate works.** A route declaring `require_claimed_user` refuses a user on
  an unclaimed temporary credential with `403 password_change_required`, runs
  normally once the flag is cleared, and still answers `401` when there is no
  usable session at all. Driven through a throwaway route mounted on a
  test-built app — no fake route ships, and the product has no route declaring
  the dependency yet, because Story 1.4 adds no surface that serves real data.

* **The gate is declared.** Every route in `create_app()`'s table outside an
  allowlist written down below, with a reason each, must declare it. That is
  what makes AGENTS.md line 18 enforceable rather than aspirational: a route
  added in Epic 2 that forgets the dependency fails this file rather than
  quietly serving a catalogue to someone holding a sticky note.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import psycopg
import pytest
from api.db import DATABASE_URL
from api.dependencies import (
    NO_SESSION,
    PASSWORD_CHANGE_REQUIRED,
    SET_A_PASSWORD_FIRST,
    UNAUTHORIZED,
    require_claimed_user,
)
from api.main import create_app
from fastapi import Depends, FastAPI, WebSocket
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from shared_schema.user import User

#: The throwaway route. Declared inside this module and mounted on an app built
#: here, so nothing resembling it reaches the product's own route table — which
#: the guard at the bottom of this file reads.
GUARDED = "/test-only/guarded"

LOGIN = "/auth/login"

MakeUser = Callable[..., Any]

#: The routes that may exist without declaring `require_claimed_user`, each with
#: the reason it is exempt. A route not in this mapping has to opt in, so
#: forgetting the dependency is a failing test rather than an access-control
#: hole nobody looks for.
ALLOWED_WITHOUT_THE_GATE: dict[tuple[str, str], str] = {
    ("GET", "/health"): (
        "Liveness probe. Unauthenticated by design and reveals nothing — it does "
        "not even touch the database."
    ),
    ("POST", "/auth/login"): (
        "The one place a credential is presented. Gating it would require a "
        "session to get a session."
    ),
    ("GET", "/auth/session"): (
        "How apps/web learns the flag is set at all. A 403 here would leave the "
        "front end unable to tell a gated user from a signed-out one, and the "
        "forced-change screen would never render."
    ),
    ("POST", "/auth/logout"): (
        "A user must always be able to leave, including one who cannot yet reach anything else."
    ),
    ("POST", "/auth/password"): (
        "The change itself. Gating the escape hatch on having already escaped "
        "leaves the account unreachable forever."
    ),
}


def _declares(route: APIRoute, dependency: Callable[..., object]) -> bool:
    """Whether `route` resolves `dependency`, at any depth of its dependency tree.

    Walked rather than matched on the handler's signature: `require_claimed_user`
    may be declared directly, through `dependencies=[...]`, or behind a
    role-checking dependency a later story wraps around it, and all three are
    the route declaring it.
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

    Recursion through `original_router` is defence, not the normal path:
    `create_app()` uses `include_router`, which copies each route into the
    parent's table, so on this application the walk finds every `APIRoute` at
    the top level and the branch never fires. It stays because a router
    *mounted* rather than included would appear as one opaque entry, and a
    guard whose whole purpose is that nothing is skipped must not skip a whole
    router. `test_no_registration.py` walks the table the same way.

    **Anything this walk does not recognise fails the run**, rather than being
    skipped. A guard whose whole purpose is that a route cannot forget the gate
    by omission cannot itself omit a route: a WebSocket route, a `Mount`, or a
    sub-application would each be served by the product, would each be invisible
    to `isinstance(route, APIRoute)`, and would each pass the allowlist check by
    never reaching it. Extending the walk is then a deliberate decision about
    how that kind of route declares the gate, taken with the failure in hand.
    """
    found: list[tuple[str, str, APIRoute]] = []

    def walk(router: Any) -> None:
        for route in router.routes:
            if isinstance(route, APIRoute):
                # HEAD and OPTIONS are added by the framework, not declared by
                # anyone, and they answer with no body — checking them would
                # make every route look like two. A route left with *nothing*
                # after that filter was declared with only those methods, and
                # would otherwise vanish from the walk entirely: neither
                # gate-checked nor allowlisted, exactly the silent omission the
                # rest of this docstring says cannot happen.
                methods = sorted((route.methods or set()) - {"HEAD", "OPTIONS"})
                if not methods:
                    raise AssertionError(
                        f"{route.path!r} declares only {sorted(route.methods or set())}, so it "
                        "is neither checked for require_claimed_user nor covered by "
                        "ALLOWED_WITHOUT_THE_GATE. Decide how a route of that shape declares "
                        "the gate, and teach _api_routes about it."
                    )
                found.extend((method, route.path, route) for method in methods)
                continue

            inner = getattr(route, "original_router", None)
            if inner is not None:
                walk(inner)
                continue

            kind = f"{type(route).__module__}.{type(route).__name__}"
            raise AssertionError(
                f"{kind} at {getattr(route, 'path', '<no path>')!r} is a route this guard "
                "does not understand, so it is neither checked for require_claimed_user nor "
                "covered by ALLOWED_WITHOUT_THE_GATE. Extend _api_routes to walk it, and "
                "decide there how a route of that kind declares the gate."
            )

    walk(app)
    return found


def _ungated_routes(app: FastAPI) -> list[str]:
    """Every route `app` serves that neither declares the gate nor is exempt.

    One expression, called by both the guard below and the negative control that
    proves the guard fires. Written twice they would be two guards, and the one
    nobody ever sees fail would be the one that ships — a copy left behind by an
    edit to the other is exactly the silent pass this file exists to prevent.
    """
    return [
        f"{method} {path}"
        for method, path, route in _api_routes(app)
        if (method, path) not in ALLOWED_WITHOUT_THE_GATE
        and not _declares(route, require_claimed_user)
    ]


def _guarded_app() -> FastAPI:
    """The product's app plus one route that declares the gate."""
    app = create_app()

    @app.get(GUARDED)
    def guarded(user: Annotated[User, Depends(require_claimed_user)]) -> dict[str, str]:
        return {"name": user.name}

    return app


@pytest.fixture
def guarded_client(migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A client for `_guarded_app`, on this test's migrated database.

    Mirrors `conftest.client`, https base URL included, so the `Secure` session
    cookie survives the jar.
    """
    monkeypatch.setenv(DATABASE_URL, migrated_url)

    with TestClient(_guarded_app(), base_url="https://testserver") as client:
        yield client


def _unclaimed(make_user: MakeUser) -> Any:
    return make_user(
        must_change_password=True,
        temp_credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
        name="Kasun Perera",
    )


def _sign_in(client: TestClient, account: Any) -> None:
    response = client.post(LOGIN, json={"email": account.email, "password": account.password})
    assert response.status_code == 200


# --- The gate as a unit -------------------------------------------------------


def test_a_user_on_a_temporary_credential_is_refused(
    guarded_client: TestClient, make_user: MakeUser
) -> None:
    account = _unclaimed(make_user)
    _sign_in(guarded_client, account)

    response = guarded_client.get(GUARDED)

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": PASSWORD_CHANGE_REQUIRED,
        "message": SET_A_PASSWORD_FIRST,
    }


def test_the_refusal_returns_no_data(guarded_client: TestClient, make_user: MakeUser) -> None:
    # Never a 200, and never a partial body: the route's own handler must not
    # run at all, so nothing it would have returned can leak.
    account = _unclaimed(make_user)
    _sign_in(guarded_client, account)

    response = guarded_client.get(GUARDED)

    assert set(response.json()) == {"error"}
    assert account.name not in response.text


def test_the_refusal_is_never_stored(guarded_client: TestClient, make_user: MakeUser) -> None:
    account = _unclaimed(make_user)
    _sign_in(guarded_client, account)

    response = guarded_client.get(GUARDED)

    assert response.headers["cache-control"] == "no-store"


def test_a_claimed_user_reaches_the_route(guarded_client: TestClient, make_user: MakeUser) -> None:
    account = make_user(must_change_password=False, name="Kasun Perera")
    _sign_in(guarded_client, account)

    response = guarded_client.get(GUARDED)

    assert response.status_code == 200
    assert response.json() == {"name": "Kasun Perera"}


def test_the_route_opens_on_the_very_next_request_after_the_change(
    guarded_client: TestClient, make_user: MakeUser
) -> None:
    # The AC's own wording: refused before, answered normally immediately
    # after, with no re-login in between.
    account = _unclaimed(make_user)
    _sign_in(guarded_client, account)
    assert guarded_client.get(GUARDED).status_code == 403

    changed = guarded_client.post(
        "/auth/password", json={"new_password": f"{account.password}-claimed"}
    )
    assert changed.status_code == 200

    assert guarded_client.get(GUARDED).status_code == 200


def test_no_cookie_is_refused_as_unauthenticated(guarded_client: TestClient) -> None:
    # `401`, not `403`: nobody is signed in, so there is no flag to be gated on.
    response = guarded_client.get(GUARDED)

    assert response.status_code == 401
    assert response.json()["error"] == {"code": UNAUTHORIZED, "message": NO_SESSION}
    assert response.headers["www-authenticate"].startswith("Session")


def test_a_deactivated_owner_is_refused_as_unauthenticated(
    guarded_client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # AD-3: `active` is re-read on every request, so this takes effect now and
    # not at the next login — and it is a 401 because the session itself is no
    # longer usable, gate or no gate.
    account = make_user(must_change_password=False)
    _sign_in(guarded_client, account)
    conn.execute("UPDATE users SET active = false WHERE id = %s", (account.id,))

    response = guarded_client.get(GUARDED)

    assert response.status_code == 401


def test_the_gate_reads_the_flag_per_request(
    guarded_client: TestClient, conn: psycopg.Connection, make_user: MakeUser
) -> None:
    # Nothing is cached at sign-in. An Administrator reissuing a temporary
    # credential closes the route on the next request, without the user having
    # to sign out first.
    account = make_user(must_change_password=False)
    _sign_in(guarded_client, account)
    assert guarded_client.get(GUARDED).status_code == 200

    conn.execute(
        "UPDATE users SET must_change_password = true, temp_credential_expires_at = %s "
        "WHERE id = %s",
        (datetime.now(UTC) + timedelta(hours=72), account.id),
    )

    assert guarded_client.get(GUARDED).status_code == 403


# --- The guard that keeps it declared -----------------------------------------


def test_the_route_table_is_reachable_and_not_empty() -> None:
    # A guard over an empty route list passes forever.
    routes = _api_routes(create_app())

    assert len(routes) >= len(ALLOWED_WITHOUT_THE_GATE)


def test_every_route_outside_the_allowlist_declares_the_gate() -> None:
    offenders = _ungated_routes(create_app())

    assert offenders == [], (
        "A route that serves real data must declare require_claimed_user "
        "(AGENTS.md line 18) or be added to ALLOWED_WITHOUT_THE_GATE with the "
        "reason it is exempt: " + ", ".join(offenders)
    )


def test_the_allowlist_names_only_routes_that_exist() -> None:
    # An allowlist entry for a route that has been renamed or removed is an
    # exemption nobody is holding: the next route to take that path inherits it
    # silently.
    live = {(method, path) for method, path, _ in _api_routes(create_app())}

    assert set(ALLOWED_WITHOUT_THE_GATE) <= live


def test_every_allowlisted_route_states_why() -> None:
    # The exemption is the dangerous half of this file. Requiring a sentence per
    # entry is what stops the list growing by one line in a hurry.
    thin = [route for route, reason in ALLOWED_WITHOUT_THE_GATE.items() if len(reason) < 40]

    assert thin == []


def test_no_admin_route_is_exempt_from_the_gate() -> None:
    # Story 1.8's acceptance clause, as a property of the allowlist rather than
    # of the one route that first needed it. `require_administrator` chains on
    # `require_claimed_user`, so an Administrator holding a credential that
    # arrived on a note cannot use it to issue a second one — and an entry here
    # would not relax that chain, it would stop this file *checking* it, which
    # is the same exemption one step further from anybody's notice. Stories
    # 1.9-1.11 add routes under this prefix and inherit the rule.
    exempt = [f"{method} {path}" for method, path in ALLOWED_WITHOUT_THE_GATE if "/admin/" in path]

    assert exempt == [], (
        "A route under /admin/ must never be exempt from the forced-change gate: "
        + ", ".join(exempt)
    )


def test_the_guard_catches_a_route_that_forgets_the_gate() -> None:
    # A guard nobody has seen fail is a guard nobody knows works. This is the
    # Epic 2 mistake, in miniature: a route that serves real data, declared
    # without the dependency.
    app = create_app()

    @app.get("/test-only/forgetful")
    def forgetful() -> dict[str, str]:
        return {"catalogue": "everything"}

    assert _ungated_routes(app) == ["GET /test-only/forgetful"]


def test_the_walk_refuses_a_route_type_it_does_not_understand() -> None:
    # The omission this guard cannot afford. A WebSocket is the realistic case —
    # Epic 2's scan progress would be one — and it is invisible to an
    # `isinstance(route, APIRoute)` filter, so a walk that merely skipped it
    # would report a fully-gated route table while serving an ungated route.
    app = create_app()

    @app.websocket("/test-only/socket")
    async def socket(websocket: WebSocket) -> None:  # pragma: no cover - never connected
        await websocket.accept()

    with pytest.raises(AssertionError, match="does not understand"):
        _api_routes(app)


def test_the_walk_refuses_a_route_that_declares_only_framework_methods() -> None:
    # The other way a route disappears from the walk. HEAD and OPTIONS are
    # filtered because the framework adds them; a route declared with nothing
    # else is left with an empty method list and would fall out of the table
    # silently — allowlisted by never being looked at.
    app = create_app()

    @app.api_route("/test-only/options-only", methods=["OPTIONS"])
    def options_only() -> dict[str, str]:  # pragma: no cover - never called
        return {"catalogue": "everything"}

    with pytest.raises(AssertionError, match="declares only"):
        _api_routes(app)


def test_the_guard_sees_a_gate_declared_through_the_route_decorator() -> None:
    # `dependencies=[Depends(...)]` is the other way to declare it, and a check
    # that only read the handler's signature would call this route forgetful.
    app = create_app()

    @app.get("/test-only/declared", dependencies=[Depends(require_claimed_user)])
    def declared() -> dict[str, str]:
        return {"catalogue": "everything"}

    routes = {(method, path): route for method, path, route in _api_routes(app)}

    assert _declares(routes[("GET", "/test-only/declared")], require_claimed_user)
