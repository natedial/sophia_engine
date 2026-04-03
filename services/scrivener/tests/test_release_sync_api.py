"""Tests for release sync API failure semantics."""

from fastapi.testclient import TestClient

import src.fetchers.fred as fred_module
from src.api.main import app


def test_release_sync_endpoint_returns_503_for_degraded_sync(monkeypatch) -> None:
    """The API should surface degraded calendar syncs as an operational failure."""

    class FakeFetcher:
        def sync_release_calendar(self, *, days_ahead):
            assert days_ahead == 90
            return {
                "status": "degraded",
                "ready": False,
                "degraded_reason": "anchor_validation_failed",
                "releases": {
                    "fetched": 5,
                    "expected": 5,
                    "inserted": 0,
                    "updated": 5,
                    "complete": True,
                    "status": "complete",
                    "degraded_reason": None,
                },
                "dates": {
                    "fetched": 20,
                    "expected": 20,
                    "inserted": 0,
                    "skipped": 20,
                    "skipped_missing_release": 0,
                    "removed": 0,
                    "complete": True,
                    "status": "degraded",
                    "degraded_reason": "anchor_validation_failed",
                    "destructive_cleanup_performed": False,
                    "integrity_ok": False,
                    "anchor_validation": {
                        "enabled": True,
                        "ok": False,
                        "checked_until": "2026-05-18",
                        "missing_releases": ["Employment Situation"],
                    },
                },
            }

    monkeypatch.setattr(fred_module, "FredFetcher", FakeFetcher)

    with TestClient(app) as client:
        response = client.post("/releases/sync", params={"days_ahead": 90})

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["message"] == "Release calendar sync completed in degraded mode"
    assert payload["detail"]["sync"]["degraded_reason"] == "anchor_validation_failed"
