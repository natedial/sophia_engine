"""Scrivener client for building immutable model snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx


@dataclass(frozen=True)
class ObservationPoint:
    """One Scrivener observation."""

    date: str
    value: float


@dataclass(frozen=True)
class SeriesSnapshot:
    """Series metadata plus observations for an input snapshot."""

    external_id: str
    source: str | None
    metadata: dict[str, Any]
    observations: list[ObservationPoint]


class ScrivenerClient:
    """HTTP client for Scrivener APIs used by Oikonomia."""

    def __init__(
        self,
        base_url: str,
        timeout_sec: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout_sec)

    def close(self) -> None:
        """Close underlying resources when owned by this client."""
        if self._owns_client:
            self._client.close()

    def get_series_info(self, series_id: str, source: str | None = None) -> dict[str, Any]:
        """Fetch Scrivener series metadata."""
        response = self._client.get(f"/series/{series_id}", params=self._params(source=source))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected Scrivener series payload for {series_id}")
        return payload

    def get_observations(
        self,
        series_id: str,
        *,
        source: str | None = None,
        days: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> list[ObservationPoint]:
        """Fetch Scrivener observations for a series."""
        params = self._params(source=source)
        if days is not None:
            params["days"] = days
        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()
        if limit is not None:
            params["limit"] = limit

        response = self._client.get(f"/series/{series_id}/observations", params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Unexpected Scrivener observation payload for {series_id}")

        return [
            ObservationPoint(date=str(item["date"]), value=float(item["value"]))
            for item in payload
            if isinstance(item, dict)
        ]

    def build_series_snapshot(
        self,
        series_id: str,
        *,
        source: str | None = None,
        days: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> SeriesSnapshot:
        """Build a full snapshot for one series."""
        metadata = self.get_series_info(series_id, source=source)
        observations = self.get_observations(
            series_id,
            source=source,
            days=days,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        return SeriesSnapshot(
            external_id=series_id,
            source=source,
            metadata=metadata,
            observations=observations,
        )

    @staticmethod
    def _params(*, source: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if source:
            params["source"] = source
        return params
