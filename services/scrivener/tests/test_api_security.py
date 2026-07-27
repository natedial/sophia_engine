"""Tests for privileged endpoint authentication."""

from fastapi.testclient import TestClient

from src.api.main import app
from src.config import get_settings


def test_privileged_endpoint_rejects_missing_key() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/ingestion/resolve",
            json={"source": "FRED", "external_id": "GDP"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing Scrivener API key"


def test_privileged_endpoint_is_disabled_without_config(monkeypatch) -> None:
    monkeypatch.delenv("SCRIVENER_API_KEY")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.post(
            "/ingestion/resolve",
            headers={"X-Scrivener-API-Key": "anything"},
            json={"source": "FRED", "external_id": "GDP"},
        )

    assert response.status_code == 503


def test_health_endpoint_remains_public() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
