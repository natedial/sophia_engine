"""Tests for privileged endpoint authentication."""

from fastapi.testclient import TestClient

from src.api.main import app
from src.config import get_settings
from src.fetchers.treasury import TreasuryFetcher


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


def test_speaker_calendar_sync_requires_key() -> None:
    with TestClient(app) as client:
        response = client.post("/speaker-events/sync")

    assert response.status_code == 401


def test_announced_auction_sync_requires_key() -> None:
    with TestClient(app) as client:
        response = client.post("/auctions/sync-announced")

    assert response.status_code == 401


def test_announced_auction_sync_hides_internal_error(monkeypatch) -> None:
    monkeypatch.setattr(
        TreasuryFetcher,
        "fetch_and_store_announced",
        lambda self: {
            "status": "error",
            "error": "database password appeared in traceback",
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/auctions/sync-announced",
            headers={"X-Scrivener-API-Key": "test-scrivener-key"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Treasury auction sync failed"


def test_announced_auction_sync_returns_only_safe_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        TreasuryFetcher,
        "fetch_and_store_announced",
        lambda self: {
            "status": "success",
            "records_fetched": 3,
            "records_stored": 2,
            "diagnostic": "internal connection details",
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/auctions/sync-announced",
            headers={"X-Scrivener-API-Key": "test-scrivener-key"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "records_fetched": 3,
        "records_stored": 2,
    }
