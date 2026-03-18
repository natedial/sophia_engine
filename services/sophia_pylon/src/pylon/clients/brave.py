"""Brave Search API client for live web retrieval."""

from typing import Any

from pylon.clients.base import BaseClient


class BraveClient(BaseClient):
    """HTTP client for Brave Search APIs."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 30.0) -> None:
        self.api_key = api_key.strip()
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-Subscription-Token"] = self.api_key
        super().__init__(base_url=base_url, timeout=timeout, headers=headers)

    @property
    def name(self) -> str:
        return "brave"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def health_check(self) -> bool:
        if not self.is_configured:
            return False

        try:
            client = await self._get_client()
            response = await client.get(
                "/res/v1/web/search",
                params={"q": "Brave Search API", "count": 1},
            )
            return response.status_code == 200
        except Exception:
            return False

    async def search_web(
        self,
        *,
        query: str,
        count: int = 5,
        country: str | None = None,
        search_lang: str | None = None,
        freshness: str | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()
        params: dict[str, Any] = {"q": query, "count": count}
        if country:
            params["country"] = country
        if search_lang:
            params["search_lang"] = search_lang
        if freshness:
            params["freshness"] = freshness

        response = await client.get("/res/v1/web/search", params=params)
        response.raise_for_status()
        return response.json()

    async def get_llm_context(
        self,
        *,
        query: str,
        count: int = 5,
        country: str | None = None,
        search_lang: str | None = None,
        freshness: str | None = None,
        maximum_number_of_urls: int = 5,
        maximum_number_of_tokens: int = 4096,
        context_threshold_mode: str = "balanced",
    ) -> dict[str, Any]:
        client = await self._get_client()
        params: dict[str, Any] = {
            "q": query,
            "count": count,
            "maximum_number_of_urls": maximum_number_of_urls,
            "maximum_number_of_tokens": maximum_number_of_tokens,
            "context_threshold_mode": context_threshold_mode,
        }
        if country:
            params["country"] = country
        if search_lang:
            params["search_lang"] = search_lang
        if freshness:
            params["freshness"] = freshness

        response = await client.get("/res/v1/llm/context", params=params)
        response.raise_for_status()
        return response.json()
