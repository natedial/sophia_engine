from __future__ import annotations

import json

import pytest

from pylon.tools.scrivener import ScrivenerToolExecutor


class _FakeScrivenerClient:
    def __init__(self) -> None:
        self.forecast_calls: list[dict] = []

    async def get_forecasts(
        self,
        *,
        indicator_key: str | None = None,
        source: str | None = None,
        country: str | None = None,
        release_date: str | None = None,
        release_date_from: str | None = None,
        release_date_to: str | None = None,
        source_date_from: str | None = None,
        source_date_to: str | None = None,
        review_status: str | None = None,
        forecast_type: str | None = None,
        economic_event_id: str | None = None,
        parsed_research_id: int | None = None,
        event_name_contains: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        call = {
            "indicator_key": indicator_key,
            "source": source,
            "country": country,
            "release_date": release_date,
            "release_date_from": release_date_from,
            "release_date_to": release_date_to,
            "source_date_from": source_date_from,
            "source_date_to": source_date_to,
            "review_status": review_status,
            "forecast_type": forecast_type,
            "economic_event_id": economic_event_id,
            "parsed_research_id": parsed_research_id,
            "event_name_contains": event_name_contains,
            "limit": limit,
        }
        self.forecast_calls.append(call)
        return [
            {
                "id": "fc-1",
                "indicator_key": indicator_key or "us_nfp",
                "source": source or "Goldman Sachs",
                "forecast_value_text": "+57k jobs",
                "release_date": release_date or "2026-04-03",
            }
        ]


@pytest.mark.asyncio
async def test_get_forecasts_passes_filters_through() -> None:
    client = _FakeScrivenerClient()
    executor = ScrivenerToolExecutor(client)

    result = await executor.execute(
        "get_forecasts",
        {
            "indicator_key": "us_nfp",
            "source": "Goldman Sachs",
            "release_date": "2026-04-03",
            "source_date_from": "2026-03-24",
            "review_status": "approved",
            "limit": 10,
        },
    )

    assert result.success is True
    assert client.forecast_calls == [
        {
            "indicator_key": "us_nfp",
            "source": "Goldman Sachs",
            "country": None,
            "release_date": "2026-04-03",
            "release_date_from": None,
            "release_date_to": None,
            "source_date_from": "2026-03-24",
            "source_date_to": None,
            "review_status": "approved",
            "forecast_type": None,
            "economic_event_id": None,
            "parsed_research_id": None,
            "event_name_contains": None,
            "limit": 10,
        }
    ]
    payload = json.loads(result.data)
    assert payload[0]["forecast_value_text"] == "+57k jobs"
