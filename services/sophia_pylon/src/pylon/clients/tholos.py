"""Tholos client — research corpus search service."""

from typing import Any

from pylon.clients.base import BaseClient


class TholosClient(BaseClient):
    """HTTP client for the sophia_tholos research search service."""

    @property
    def name(self) -> str:
        return "tholos"

    async def health_check(self) -> bool:
        """Check if Tholos service is available."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def search(
        self,
        query: str,
        limit: int = 10,
        keyword_weight: float | None = None,
        semantic_weight: float | None = None,
        min_lexical_score: float | None = None,
        semantic_tail_mode: str | None = None,
    ) -> dict[str, Any]:
        """Hybrid search over the research corpus."""
        client = await self._get_client()
        body: dict[str, Any] = {"query": query, "limit": limit}
        if keyword_weight is not None:
            body["keyword_weight"] = keyword_weight
        if semantic_weight is not None:
            body["semantic_weight"] = semantic_weight
        if min_lexical_score is not None:
            body["min_lexical_score"] = min_lexical_score
        if semantic_tail_mode is not None:
            body["semantic_tail_mode"] = semantic_tail_mode
        response = await client.post("/search", json=body)
        response.raise_for_status()
        return response.json()

    async def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        """Fetch a single chunk by ID."""
        client = await self._get_client()
        response = await client.get(f"/chunk/{chunk_id}")
        response.raise_for_status()
        return response.json()

    async def list_sources(self) -> dict[str, Any]:
        """List distinct source paths with chunk counts."""
        client = await self._get_client()
        response = await client.get("/sources")
        response.raise_for_status()
        return response.json()
