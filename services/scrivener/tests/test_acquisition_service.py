"""Tests for on-demand acquisition and ingestion scaffolding."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from src.acquisition.service import (
    AcquisitionCandidate,
    AcquisitionRequest,
    AcquisitionService,
    BaseAcquisitionAdapter,
)
from src.api.main import app
import src.api.main as api_main
from src.fetchers.bls import BlsFetcher


class FakeAdapter(BaseAcquisitionAdapter):
    source_name = "FRED"

    def search_candidates(self, query: str, *, limit: int = 5) -> list[AcquisitionCandidate]:
        assert query == "real gdp"
        return [
            AcquisitionCandidate(
                external_id="GDPC1",
                name="Real Gross Domestic Product",
                source="FRED",
                frequency="quarterly",
                units="Billions of Chained 2017 Dollars",
            )
        ][:limit]

    def ingest_series(
        self,
        external_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, object]:
        return {
            "status": "success",
            "external_id": external_id,
            "records_fetched": 12,
            "records_inserted": 12,
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None,
        }


def test_acquisition_service_resolve_and_ingest() -> None:
    service = AcquisitionService(adapters={"FRED": FakeAdapter()})

    resolved = service.resolve(
        AcquisitionRequest(source="FRED", query="real gdp", max_candidates=3)
    )
    assert resolved["status"] == "ok"
    assert resolved["candidates"][0]["external_id"] == "GDPC1"

    ingested = service.ingest(
        AcquisitionRequest(
            source="FRED",
            query="real gdp",
            retention_target="staging",
            promote_if_valid=True,
        )
    )
    assert ingested["status"] == "success"
    assert ingested["external_id"] == "GDPC1"
    assert ingested["promotion"]["eligible"] is True


def test_acquisition_api_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(
        api_main,
        "get_acquisition_service",
        lambda: AcquisitionService(adapters={"FRED": FakeAdapter()}),
    )

    with TestClient(app) as client:
        resolve_response = client.post(
            "/ingestion/resolve",
            json={"source": "FRED", "query": "real gdp", "max_candidates": 3},
        )
        assert resolve_response.status_code == 200
        assert resolve_response.json()["candidates"][0]["external_id"] == "GDPC1"

        ingest_response = client.post(
            "/ingestion/series",
            json={
                "source": "FRED",
                "query": "real gdp",
                "retention_target": "staging",
                "promote_if_valid": True,
            },
        )
        assert ingest_response.status_code == 200
        payload = ingest_response.json()
        assert payload["status"] == "success"
        assert payload["external_id"] == "GDPC1"


class AmbiguousAdapter(BaseAcquisitionAdapter):
    source_name = "BLS"

    def search_candidates(self, query: str, *, limit: int = 5) -> list[AcquisitionCandidate]:
        return [
            AcquisitionCandidate(
                external_id="CUSR0000SA0",
                name="CPI-U All Items (seasonally adjusted)",
                source="BLS",
            ),
            AcquisitionCandidate(
                external_id="CES0500000003",
                name="Average Hourly Earnings, Private",
                source="BLS",
            ),
        ][:limit]

    def ingest_series(
        self,
        external_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, object]:
        raise AssertionError("ambiguous matches should not be ingested")


def test_acquisition_service_returns_ambiguous_for_multiple_matches() -> None:
    service = AcquisitionService(adapters={"BLS": AmbiguousAdapter()})

    result = service.ingest(
        AcquisitionRequest(
            source="BLS",
            query="health care and social assistance wage growth",
        )
    )

    assert result["status"] == "ambiguous"
    assert "No unambiguous sector-level candidate" in result["message"]


def test_bls_fetcher_returns_sector_specific_ahe_candidate() -> None:
    fetcher = BlsFetcher()

    candidates = fetcher.search_series_candidates(
        "average hourly earnings health care and social assistance naics 62",
        limit=5,
    )

    assert candidates
    assert candidates[0]["external_id"] == "CES6562000003"


def test_bls_fetcher_refuses_generic_jolts_for_sector_query() -> None:
    fetcher = BlsFetcher()

    candidates = fetcher.search_series_candidates(
        "job openings health care and social assistance naics 62 jolts",
        limit=5,
    )

    assert candidates == []
