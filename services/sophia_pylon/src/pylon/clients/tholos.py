"""Tholos client — research corpus search service."""

from typing import Any

import httpx

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
            response = await client.get("/ready")
            if response.status_code == 503:
                raise RuntimeError("Corpus not loaded")
            response.raise_for_status()
            return True
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            return False

    async def get_status(self) -> dict[str, Any]:
        """Fetch detailed readiness metadata."""
        client = await self._get_client()
        response = await client.get("/ready")
        if response.status_code == 503:
            raise RuntimeError("Corpus not loaded")
        response.raise_for_status()
        return response.json()

    async def search(
        self,
        query: str,
        limit: int = 10,
        keyword_weight: float | None = None,
        semantic_weight: float | None = None,
        min_lexical_score: float | None = None,
        semantic_tail_mode: str | None = None,
        run_id: str | None = None,
        run_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        exclude_source_paths: list[str] | None = None,
        source_path_prefix: str | None = None,
        source_path_contains: str | None = None,
        min_page_number: int | None = None,
        max_page_number: int | None = None,
        max_per_source: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
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
        if run_id is not None:
            body["run_id"] = run_id
        if run_ids is not None:
            body["run_ids"] = run_ids
        if source_paths is not None:
            body["source_paths"] = source_paths
        if exclude_source_paths is not None:
            body["exclude_source_paths"] = exclude_source_paths
        if source_path_prefix is not None:
            body["source_path_prefix"] = source_path_prefix
        if source_path_contains is not None:
            body["source_path_contains"] = source_path_contains
        if min_page_number is not None:
            body["min_page_number"] = min_page_number
        if max_page_number is not None:
            body["max_page_number"] = max_page_number
        if max_per_source is not None:
            body["max_per_source"] = max_per_source
        if date_from is not None:
            body["date_from"] = date_from
        if date_to is not None:
            body["date_to"] = date_to
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
