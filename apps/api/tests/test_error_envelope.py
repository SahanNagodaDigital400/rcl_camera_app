"""Every error this service returns is the shared envelope — all four kinds.

`ApiError` is the one we raise deliberately; the other three (routing,
validation, unhandled) are the ones FastAPI would otherwise answer with its own
`{"detail": ...}` shape, leaving `apps/web` two formats to parse.
"""

from __future__ import annotations

import logging

import pytest
from api.main import FALLBACK_CODE, create_app
from api.main import app as served_app
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from shared_schema.errors import ApiError


def _assert_envelope(body: object, code: str) -> None:
    assert isinstance(body, dict)
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]


def _app_that_raises(error: Exception) -> FastAPI:
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise error

    return app


class _Body(BaseModel):
    code: str


def test_api_error_renders_the_shared_envelope() -> None:
    error = ApiError(code="tile_not_found", message="No Tile with that Code.", status_code=404)

    with TestClient(_app_that_raises(error)) as client:
        response = client.get("/boom")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "tile_not_found", "message": "No Tile with that Code."}
    }


def test_error_body_carries_nothing_beyond_code_and_message() -> None:
    with TestClient(_app_that_raises(ApiError(code="bad_request", message="Nope."))) as client:
        _assert_envelope(client.get("/boom").json(), "bad_request")


def test_unrouted_path_returns_the_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/no-such-path")

    assert response.status_code == 404
    _assert_envelope(response.json(), "not_found")


def test_wrong_method_returns_the_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/health")

    assert response.status_code == 405
    _assert_envelope(response.json(), "method_not_allowed")


def test_validation_failure_returns_the_envelope() -> None:
    app = create_app()

    @app.post("/echo")
    async def echo(body: _Body) -> dict[str, str]:
        return {"code": body.code}

    with TestClient(app) as client:
        response = client.post("/echo", json={"wrong": "shape"})

    assert response.status_code == 422
    _assert_envelope(response.json(), "validation_error")


def test_validation_failure_does_not_echo_the_submitted_value() -> None:
    app = create_app()
    secret = "swordfish"

    @app.post("/echo")
    async def echo(body: _Body) -> dict[str, str]:
        return {"code": body.code}

    with TestClient(app) as client:
        response = client.post("/echo", json={"code": {"nested": secret}})

    assert response.status_code == 422
    assert secret not in response.text


def test_unhandled_exception_returns_the_envelope_and_leaks_nothing() -> None:
    secret = "postgres://user:swordfish@db/rocell"
    app = _app_that_raises(RuntimeError(secret))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    _assert_envelope(response.json(), "internal_error")
    assert secret not in response.text
    assert "RuntimeError" not in response.text


def test_the_served_app_has_the_same_contract() -> None:
    # `make dev` serves api.main:app, not create_app(). Exercise that instance
    # so the tested app and the served app cannot drift apart.
    with TestClient(served_app) as client:
        health = client.get("/health")
        missing = client.get("/no-such-path")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert missing.status_code == 404
    _assert_envelope(missing.json(), "not_found")


def test_the_schema_browsers_are_off() -> None:
    # An unauthenticated endpoint index is a map of the attack surface.
    with TestClient(served_app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404, f"{path} is still served"


def test_the_405_keeps_its_allow_header() -> None:
    # RFC 9110 makes Allow mandatory on a 405. Rebuilding the response from
    # scratch is exactly how a header like that gets dropped.
    with TestClient(create_app()) as client:
        response = client.post("/health")

    assert response.status_code == 405
    assert "GET" in response.headers.get("allow", "")


def test_an_http_exceptions_own_headers_survive_the_envelope() -> None:
    # The shape Story 1.3's 401 takes: without the challenge header a client
    # cannot tell an unauthenticated request from a forbidden one.
    error = HTTPException(
        status_code=401,
        detail="Sign in first.",
        headers={"WWW-Authenticate": 'Session realm="rocell"'},
    )

    with TestClient(_app_that_raises(error)) as client:
        response = client.get("/boom")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Session realm="rocell"'
    _assert_envelope(response.json(), "unauthorized")


def test_an_unmapped_status_falls_back_to_a_generic_code() -> None:
    # STATUS_CODES does not list every status routing can produce, and the
    # fallback is what a client sees when it does not.
    with TestClient(_app_that_raises(HTTPException(status_code=503))) as client:
        response = client.get("/boom")

    assert response.status_code == 503
    _assert_envelope(response.json(), FALLBACK_CODE)


def test_the_unhandled_handler_logs_what_the_response_withholds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The 500 body tells the user "the incident has been logged". Nothing else
    # records the exception, so if that is not true the traceback is gone.
    marker = "canary-9f31"

    with caplog.at_level(logging.ERROR, logger="rocell.api"):
        with TestClient(_app_that_raises(RuntimeError(marker)), raise_server_exceptions=False) as (
            client
        ):
            response = client.get("/boom")

    assert response.status_code == 500
    assert marker not in response.text
    logged = any(
        marker in record.getMessage() or marker in (record.exc_text or "")
        for record in caplog.records
    )
    assert logged, "nothing was logged, so the response body's promise is false"


def test_an_api_error_carries_its_headers_to_the_client() -> None:
    # Story 1.3 raises its 401s through ApiError. A 401 with no
    # WWW-Authenticate challenge tells the client nothing about how to
    # authenticate, and this handler used to build its own header-less response.
    error = ApiError(
        code="unauthorized",
        message="Sign in to continue.",
        status_code=401,
        headers={"WWW-Authenticate": 'Session realm="rocell"'},
    )

    with TestClient(_app_that_raises(error)) as client:
        response = client.get("/boom")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Session realm="rocell"'
    _assert_envelope(response.json(), "unauthorized")


def test_an_api_error_without_headers_still_renders_the_envelope() -> None:
    error = ApiError(code="conflict", message="Taken.", status_code=409)

    with TestClient(_app_that_raises(error)) as client:
        response = client.get("/boom")

    assert response.status_code == 409
    assert "www-authenticate" not in response.headers
    _assert_envelope(response.json(), "conflict")


@pytest.mark.parametrize("status_code", [204, 304, 302])
def test_a_non_error_http_exception_becomes_an_enveloped_500(status_code: int) -> None:
    # The envelope is claimed for *every* error response, and `_envelope`
    # refuses a non-error status — so `http_exception_handler` raises on one.
    # What keeps the claim true is that `unhandled_error_handler` is registered
    # for `Exception` and catches that raise too. Unregister it and this stops
    # being an envelope, so the claim is pinned here rather than assumed.
    with TestClient(
        _app_that_raises(HTTPException(status_code=status_code)), raise_server_exceptions=False
    ) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    _assert_envelope(response.json(), "internal_error")
