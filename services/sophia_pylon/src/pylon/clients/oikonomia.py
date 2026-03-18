"""Oikonomia client - published economic model projections."""

from typing import Any

from pylon.clients.base import BaseClient


class OikonomiaClient(BaseClient):
    """HTTP client for the Oikonomia model orchestration service."""

    @property
    def name(self) -> str:
        return "oikonomia"

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def get_model(self, model_id: str) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.get(f"/v1/models/{model_id}")
        response.raise_for_status()
        return response.json()

    async def get_slot_champion(self, production_slot: str) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.get(f"/v1/slots/{production_slot}/champion")
        response.raise_for_status()
        return response.json()

    async def list_publications(self) -> list[dict[str, Any]]:
        client = await self._get_client()
        response = await client.get("/v1/publications")
        response.raise_for_status()
        return response.json()

    async def get_latest_publication(self, model_id: str) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.get(f"/v1/publications/latest/{model_id}")
        response.raise_for_status()
        return response.json()

    async def get_latest_publication_for_slot(self, production_slot: str) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.get(f"/v1/publications/latest/slot/{production_slot}")
        response.raise_for_status()
        return response.json()
