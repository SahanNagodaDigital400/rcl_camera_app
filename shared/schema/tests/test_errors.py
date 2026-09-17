"""The error envelope is a cross-layer contract, so its shape is asserted here."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from shared_schema.errors import ApiError, ErrorBody, ErrorEnvelope


def test_api_error_renders_the_shared_envelope() -> None:
    error = ApiError(code="tile_not_found", message="No Tile with that Code.")

    assert error.to_envelope().model_dump() == {
        "error": {"code": "tile_not_found", "message": "No Tile with that Code."}
    }


def test_envelope_has_no_keys_beyond_the_contract() -> None:
    envelope = ErrorEnvelope.model_validate({"error": {"code": "bad_request", "message": "Nope."}})

    assert set(envelope.model_dump()) == {"error"}
    assert set(envelope.model_dump()["error"]) == {"code", "message"}


def test_api_error_defaults_to_a_client_error_status() -> None:
    assert ApiError(code="bad_request", message="Nope.").status_code == 400


def test_api_error_is_raisable_and_carries_its_message() -> None:
    try:
        raise ApiError(code="unauthorized", message="Sign in first.", status_code=401)
    except ApiError as exc:
        assert str(exc) == "Sign in first."
        assert exc.status_code == 401


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("", "Nope."),
        ("   ", "Nope."),
        ("bad_request", ""),
        ("bad_request", "\t "),
    ],
)
def test_api_error_refuses_an_empty_code_or_message(code: str, message: str) -> None:
    # A blank envelope is unbranchable by the client and blank on screen.
    with pytest.raises(ValueError, match="non-empty"):
        ApiError(code=code, message=message)


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": "c", "message": "m"}, "detail": "legacy"},
        {"error": {"code": "c", "message": "m", "field": "code"}},
    ],
)
def test_envelope_refuses_keys_beyond_the_contract(body: dict[str, object]) -> None:
    # The TypeScript twin's isErrorEnvelope rejects these. Pydantic's default is
    # to accept and silently drop them, which would leave the two halves
    # disagreeing about what an error envelope is.
    with pytest.raises(ValidationError):
        ErrorEnvelope.model_validate(body)


def test_error_body_refuses_keys_beyond_the_contract() -> None:
    with pytest.raises(ValidationError):
        ErrorBody.model_validate({"code": "c", "message": "m", "field": "code"})


@pytest.mark.parametrize("status_code", [0, 200, 204, 302, 399, 600, 999])
def test_api_error_refuses_a_status_that_is_not_an_error(status_code: int) -> None:
    # A 200 carrying an error envelope reads to the client as success.
    with pytest.raises(ValueError, match="4xx or 5xx"):
        ApiError(code="bad_request", message="Nope.", status_code=status_code)


@pytest.mark.parametrize("status_code", [400, 401, 404, 422, 500, 503, 599])
def test_api_error_accepts_every_error_status(status_code: int) -> None:
    assert ApiError(code="c", message="m", status_code=status_code).status_code == status_code
