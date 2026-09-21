"""Application factory and the `/health` endpoint.

Every error response this service produces is the shared envelope from
`shared_schema.errors` — `{"error": {"code": ..., "message": ...}}`. That is a
claim about *all* of them, not just the ones we raise deliberately, so the four
ways an error can reach a client are each handled here:

* `ApiError` — raised by our own code.
* `HTTPException` — raised by Starlette/FastAPI routing (404, 405).
* `RequestValidationError` — a malformed request body or query (422).
* Anything else — an unhandled exception (500).

Without the last three, FastAPI's default `{"detail": ...}` would leak through
and `apps/web` would have two error shapes to parse instead of one.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from shared_schema.errors import ApiError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import audit, auth, users
from api.db import lifespan

#: Stable, machine-readable codes for the HTTP statuses routing produces. A
#: client branches on these, so they are part of the API contract: rename one
#: only with `apps/web`.
STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
}

FALLBACK_CODE = "http_error"
INTERNAL_ERROR_CODE = "internal_error"

#: Deliberately generic. An unhandled exception's text can carry a file path, a
#: query fragment or a credential, and this response goes to the browser. The
#: promise it makes is kept by `unhandled_error_handler`, which logs the
#: traceback before this is returned — do not make a claim here that no code
#: below honours.
INTERNAL_ERROR_MESSAGE = "An unexpected error occurred. The incident has been logged."

logger = logging.getLogger("rocell.api")


def _envelope(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiError(code=code, message=message, status_code=status_code)
        .to_envelope()
        .model_dump(),
        headers=headers,
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an `ApiError` as the shared error envelope.

    Routed through `_envelope` rather than building its own response, so this
    path cannot drift from the routing path — and so the error's headers reach
    the client. A `401` raised as `ApiError` needs its `WWW-Authenticate`
    challenge exactly as much as one raised as `HTTPException` does.
    """
    if not isinstance(exc, ApiError):  # pragma: no cover - registered for ApiError only
        raise exc
    return _envelope(exc.status_code, exc.code, exc.message, headers=exc.headers)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render a routing-level `HTTPException` as the shared error envelope.

    The exception's own headers are carried through. They are not decoration:
    RFC 9110 requires `Allow` on a 405, and the 401s Story 1.3 adds are
    meaningless to a client without their `WWW-Authenticate` challenge.
    Rebuilding the response from scratch is exactly how those get dropped.
    """
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - defensive
        raise exc
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else "Request failed."
    return _envelope(
        exc.status_code,
        STATUS_CODES.get(exc.status_code, FALLBACK_CODE),
        detail,
        headers=getattr(exc, "headers", None),
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render a request-validation failure as the shared error envelope.

    The per-field detail is deliberately dropped: it echoes the submitted value
    back to the caller, and the envelope has no field for it.
    """
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - defensive
        raise exc
    return _envelope(422, STATUS_CODES[422], "The request was not in the expected shape.")


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an unhandled exception as the shared error envelope, saying nothing.

    Nothing about the exception reaches the client, so the traceback has to go
    somewhere or it is lost outright — and `INTERNAL_ERROR_MESSAGE` tells the
    user the incident has been logged. This is where that promise is kept.
    """
    logger.exception(
        "Unhandled exception serving %s %s", request.method, request.url.path, exc_info=exc
    )
    return _envelope(500, INTERNAL_ERROR_CODE, INTERNAL_ERROR_MESSAGE)


def create_app() -> FastAPI:
    """Build the FastAPI application with the cross-cutting error contract installed."""
    app = FastAPI(
        title="Rocell Tile Scanner API",
        version="0.1.0",
        description="Internal API for the Rocell Tile Scanner. Staff only.",
        # Opens the connection pool and reads DATABASE_URL at startup, so a
        # service with no database fails where an operator sees it rather than
        # at the first sign-in.
        lifespan=lifespan,
        # The interactive schema browsers are off from the scaffold on, not
        # retrofitted later. Catalogue exfiltration through a compromised
        # account is this product's primary commercial threat, and an
        # unauthenticated endpoint index is a map of the attack surface.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe. Unauthenticated by design — it reveals nothing.

        Deliberately does not touch the database: a probe that failed whenever
        Postgres hiccuped would take the process down with it, and the one
        thing this endpoint answers is whether the process is alive.
        """
        return {"status": "ok"}

    # The only unauthenticated endpoints in the product are `/health` and
    # `POST /auth/login`. Everything a later story adds goes behind
    # `api.dependencies.require_claimed_user`, which is `lookup_session` (AD-3)
    # plus Story 1.4's forced-change gate — `tests/test_forced_change_gate.py`
    # walks the route table below and fails on any route outside its written
    # allowlist that does not declare it.
    app.include_router(auth.router)
    # `/admin/` is an authorization boundary, not a naming convention: every
    # route under it declares `api.dependencies.require_administrator`, and
    # `tests/test_admin_authorization.py` reads that requirement off the path
    # for both directions — nothing under the prefix may omit the dependency,
    # and nothing outside it may declare it. That is what lets Stories 1.9–1.11
    # inherit the rule by choosing a path rather than by remembering a habit —
    # and what lets Story 1.13's `GET /admin/audit` inherit it from a third
    # router, registered here rather than folded into `users` because the audit
    # table has exactly one owning module (AD-4) and its read lives there.
    app.include_router(users.router)
    app.include_router(audit.router)

    return app


app = create_app()
