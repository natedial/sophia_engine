"""Sentry client for publication-triggered background watch evaluation."""

from __future__ import annotations

from typing import Any

import httpx


class SentryClient:
    """HTTP client for Sophia Sentry notification hooks."""

    def __init__(
        self,
        base_url: str,
        timeout_sec: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout_sec)

    def close(self) -> None:
        """Close underlying resources when owned by this client."""
        if self._owns_client:
            self._client.close()

    def notify_publication(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Notify Sentry that a production publication changed."""
        response = self._client.post("/v1/integrations/oikonomia/publications", json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected Sentry response for publication notification")
        return [item for item in data if isinstance(item, dict)]
