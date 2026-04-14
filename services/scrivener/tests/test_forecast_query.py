"""Tests for forecast query formatting and API exposure."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.api.main import app
from src.query.forecasts import ForecastQuery
import src.api.main as api_main


def test_format_forecast_rows_serializes_types() -> None:
    rows = [
        SimpleNamespace(
            id="fc-1",
            economic_event_id="evt-1",
            parsed_research_id=181,
            source="Goldman Sachs",
            source_date=date(2026, 3, 30),
            document_name="US Daily",
            document_link="https://example.com/report",
            document_hash="abc123",
            indicator_key="us_nfp",
            event_name="Nonfarm Payrolls",
            country="US",
            period="Mar-2026",
            release_date=date(2026, 4, 3),
            forecast_type="point",
            forecast_value_numeric=Decimal("57000"),
            forecast_value_low=Decimal("25000"),
            forecast_value_high=Decimal("90000"),
            forecast_value_text="+57k jobs",
            forecast_unit="jobs",
            qualifier_text=None,
            extraction_confidence="high",
            evidence_text="Goldman Sachs forecasts +57k jobs in NFP for April 3.",
            review_status="approved",
            upload_source="research_analysis_layer",
            created_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
        )
    ]

    payload = ForecastQuery._format_forecast_rows(rows)

    assert payload == [
        {
            "id": "fc-1",
            "economic_event_id": "evt-1",
            "parsed_research_id": 181,
            "source": "Goldman Sachs",
            "source_date": "2026-03-30",
            "document_name": "US Daily",
            "document_link": "https://example.com/report",
            "document_hash": "abc123",
            "indicator_key": "us_nfp",
            "event_name": "Nonfarm Payrolls",
            "country": "US",
            "period": "Mar-2026",
            "release_date": "2026-04-03",
            "forecast_type": "point",
            "forecast_value_numeric": 57000.0,
            "forecast_value_low": 25000.0,
            "forecast_value_high": 90000.0,
            "forecast_value_text": "+57k jobs",
            "forecast_unit": "jobs",
            "qualifier_text": None,
            "extraction_confidence": "high",
            "evidence_text": "Goldman Sachs forecasts +57k jobs in NFP for April 3.",
            "review_status": "approved",
            "upload_source": "research_analysis_layer",
            "created_at": "2026-03-30T10:00:00+00:00",
            "updated_at": "2026-03-30T10:05:00+00:00",
        }
    ]


def test_forecast_api_endpoint_passes_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_forecasts(**kwargs):
        captured.update(kwargs)
        return [
            {
                "id": "fc-1",
                "economic_event_id": "evt-1",
                "parsed_research_id": 181,
                "source": "Goldman Sachs",
                "source_date": "2026-03-30",
                "document_name": "US Daily",
                "document_link": "https://example.com/report",
                "document_hash": "abc123",
                "indicator_key": "us_nfp",
                "event_name": "Nonfarm Payrolls",
                "country": "US",
                "period": "Mar-2026",
                "release_date": "2026-04-03",
                "forecast_type": "point",
                "forecast_value_numeric": 57000.0,
                "forecast_value_low": None,
                "forecast_value_high": None,
                "forecast_value_text": "+57k jobs",
                "forecast_unit": "jobs",
                "qualifier_text": None,
                "extraction_confidence": "high",
                "evidence_text": "Goldman Sachs forecasts +57k jobs in NFP for April 3.",
                "review_status": "approved",
                "upload_source": "research_analysis_layer",
                "created_at": "2026-03-30T10:00:00+00:00",
                "updated_at": "2026-03-30T10:05:00+00:00",
            }
        ]

    monkeypatch.setattr(api_main, "ForecastQuery", SimpleNamespace(list_forecasts=fake_list_forecasts))

    with TestClient(app) as client:
        response = client.get(
            "/forecasts",
            params={
                "indicator_key": "us_nfp",
                "release_date": "2026-04-03",
                "source_date_from": "2026-03-24",
                "review_status": "approved",
                "limit": 10,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["indicator_key"] == "us_nfp"
    assert captured == {
        "indicator_key": "us_nfp",
        "source": None,
        "country": None,
        "release_date": date(2026, 4, 3),
        "release_date_from": None,
        "release_date_to": None,
        "source_date_from": date(2026, 3, 24),
        "source_date_to": None,
        "review_status": "approved",
        "forecast_type": None,
        "economic_event_id": None,
        "parsed_research_id": None,
        "event_name_contains": None,
        "limit": 10,
    }
