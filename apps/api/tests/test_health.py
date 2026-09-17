"""The liveness probe is the one endpoint this story delivers."""

from __future__ import annotations

from api.main import create_app
from fastapi.testclient import TestClient


def test_health_returns_ok() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
