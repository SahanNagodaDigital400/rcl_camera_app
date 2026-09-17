"""The API error envelope, shared by every `apps/api` endpoint.

The architecture spine's Consistency Conventions table fixes one error shape for
the whole service::

    {"error": {"code": "...", "message": "..."}}

Nothing else is ever returned on an error path. `apps/web` compiles against the
TypeScript twin of these models in `shared_schema/ts/errors.ts`; the two files
are one contract in two languages and are changed together or not at all.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

DEFAULT_ERROR_STATUS = 400

#: The envelope is a closed shape, not an open one. `isErrorEnvelope` in the
#: TypeScript twin rejects a body carrying any key beyond the contract, so the
#: Python half has to reject it too or the two halves disagree about what "is
#: an error envelope" means — and pydantic's default is to accept and discard.
_CLOSED = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    """The inner object of the error envelope."""

    model_config = _CLOSED

    code: str
    message: str


class ErrorEnvelope(BaseModel):
    """The complete body of any error response."""

    model_config = _CLOSED

    error: ErrorBody


class ApiError(Exception):
    """An error that renders as the shared envelope.

    Raise this anywhere in `apps/api`; the app-level handler installed by
    `api.main.create_app` turns it into the envelope with `status_code` and
    `headers`.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = DEFAULT_ERROR_STATUS,
        headers: dict[str, str] | None = None,
    ) -> None:
        # An envelope carrying {"code": "", "message": ""} is worse than no
        # envelope: the client cannot branch on it and the user is shown a
        # blank error. Refuse it where it is constructed, not where it lands.
        if not code.strip():
            raise ValueError("ApiError requires a non-empty code.")
        if not message.strip():
            raise ValueError("ApiError requires a non-empty message.")
        # An envelope served under 200 is read by the client as success, and
        # `JSONResponse` will not accept a status outside the HTTP range at
        # all. Same reasoning as above: refuse it where it is constructed.
        if not 400 <= status_code <= 599:
            raise ValueError("ApiError requires a 4xx or 5xx status_code.")

        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        # Some failures are not complete without a header. RFC 9110 makes
        # `Allow` mandatory on a 405, and a 401 without `WWW-Authenticate` tells
        # the client nothing about how to authenticate. `HTTPException` can
        # carry them; an error raised through this class has to be able to as
        # well, or the shape of the failure depends on which class produced it.
        self.headers = headers

    def to_envelope(self) -> ErrorEnvelope:
        """Render this error as the wire-format envelope."""
        return ErrorEnvelope(error=ErrorBody(code=self.code, message=self.message))
