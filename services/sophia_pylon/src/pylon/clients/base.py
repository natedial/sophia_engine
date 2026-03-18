"""Base HTTP client for backend services."""

from abc import ABC, abstractmethod

import httpx


class BaseClient(ABC):
    """Base class for HTTP clients connecting to backend services."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=self._headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this client."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the service is available."""
        ...
