"""Scrivener client - economic and market data."""

from typing import Any

import httpx

from pylon.clients.base import BaseClient


class ScrivenerClient(BaseClient):
    """
    HTTP client for the Scrivener economic data service.

    Provides access to:
    - FRED economic series (GDP, inflation, employment, rates)
    - BLS data
    - Treasury auction results
    - Economic release calendar
    - Fed speeches and communications
    """

    @property
    def name(self) -> str:
        return "scrivener"

    async def health_check(self) -> bool:
        """Check if Scrivener service is available."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def list_series(self) -> dict[str, Any]:
        """List all available series."""
        client = await self._get_client()
        response = await client.get("/series")
        response.raise_for_status()
        return response.json()

    async def search_series(self, query: str) -> dict[str, Any]:
        """Search for series by keyword."""
        client = await self._get_client()
        response = await client.get("/series/search", params={"q": query})
        response.raise_for_status()
        return response.json()

    async def get_series_info(self, series_id: str) -> dict[str, Any]:
        """Get series metadata."""
        client = await self._get_client()
        response = await client.get(f"/series/{series_id}")
        response.raise_for_status()
        return response.json()

    async def get_latest_value(self, series_id: str) -> dict[str, Any]:
        """Get the latest value for a series."""
        client = await self._get_client()
        response = await client.get(f"/series/{series_id}/latest")
        response.raise_for_status()
        return response.json()

    async def get_observations(self, series_id: str, days: int = 365) -> dict[str, Any]:
        """Get historical observations."""
        client = await self._get_client()
        response = await client.get(
            f"/series/{series_id}/observations",
            params={"days": days},
        )
        response.raise_for_status()
        return response.json()

    async def get_series_change(self, series_id: str, periods: int = 1) -> dict[str, Any]:
        """Get series change over period."""
        client = await self._get_client()
        response = await client.get(
            f"/series/{series_id}/change",
            params={"periods": periods},
        )
        response.raise_for_status()
        return response.json()

    async def get_auctions(
        self, security_type: str | None = None, days: int = 30
    ) -> dict[str, Any]:
        """Get recent auction results."""
        client = await self._get_client()
        params: dict[str, Any] = {"days": days}
        if security_type:
            params["type"] = security_type
        response = await client.get("/auctions", params=params)
        response.raise_for_status()
        return response.json()

    async def get_auction_summary(self) -> dict[str, Any]:
        """Get auction summary statistics."""
        client = await self._get_client()
        response = await client.get("/auctions/summary")
        response.raise_for_status()
        return response.json()

    # -------------------------------------------------------------------------
    # Releases (Economic Calendar)
    # -------------------------------------------------------------------------

    async def get_releases_upcoming(self, days: int = 7) -> dict[str, Any]:
        """Get upcoming economic releases."""
        client = await self._get_client()
        response = await client.get("/releases/upcoming", params={"days": days})
        response.raise_for_status()
        return response.json()

    async def get_releases_today(self) -> dict[str, Any]:
        """Get today's economic releases."""
        client = await self._get_client()
        response = await client.get("/releases/today")
        response.raise_for_status()
        return response.json()

    async def get_releases_week(self) -> dict[str, Any]:
        """Get this week's economic releases."""
        client = await self._get_client()
        response = await client.get("/releases/week")
        response.raise_for_status()
        return response.json()

    async def get_releases_summary(self) -> dict[str, Any]:
        """Get release summary statistics."""
        client = await self._get_client()
        response = await client.get("/releases/summary")
        response.raise_for_status()
        return response.json()

    async def get_release_schedule(self, release_id: str) -> dict[str, Any]:
        """Get a specific release with its upcoming dates."""
        client = await self._get_client()
        response = await client.get(f"/releases/{release_id}/schedule")
        response.raise_for_status()
        return response.json()

    # -------------------------------------------------------------------------
    # Speeches (Fed Communications)
    # -------------------------------------------------------------------------

    async def get_speeches(
        self,
        speaker: str | None = None,
        days: int = 30,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get Fed speeches, optionally filtered by speaker."""
        client = await self._get_client()
        params: dict[str, Any] = {"days": days, "limit": limit}
        if speaker:
            params["speaker"] = speaker
        response = await client.get("/speeches", params=params)
        response.raise_for_status()
        return response.json()

    async def get_speech(self, speech_id: int) -> dict[str, Any]:
        """Get a specific speech with full text."""
        client = await self._get_client()
        response = await client.get(f"/speeches/{speech_id}")
        response.raise_for_status()
        return response.json()

    async def get_speakers(self) -> dict[str, Any]:
        """Get list of Fed speakers."""
        client = await self._get_client()
        response = await client.get("/speakers")
        response.raise_for_status()
        return response.json()
