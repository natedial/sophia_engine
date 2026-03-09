"""Fed Textual Change Tracker client — Fed communications analysis service."""

from typing import Any

from pylon.clients.base import BaseClient


class FedTrackerClient(BaseClient):
    """HTTP client for the Fed Textual Change Tracker service.

    This is an external local-only service (not managed by sophia_engine)
    that provides textual analysis of Federal Reserve communications.

    All responses (except /openapi.json) use a versioned envelope:
        {"api_version": "v1", "ok": bool, "transport": ...,
         "operation": ..., "status_code": int, "data": ...}
    """

    @property
    def name(self) -> str:
        return "fed_tracker"

    async def health_check(self) -> bool:
        """Check if the Fed Tracker service is available."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            if response.status_code != 200:
                return False
            body = response.json()
            return body.get("ok", False) if isinstance(body, dict) else False
        except Exception:
            return False

    def _unwrap(self, response_json: dict[str, Any]) -> Any:
        """Unwrap the versioned envelope, returning the 'data' payload.

        Raises ValueError if the envelope signals failure.
        """
        if not response_json.get("ok", False):
            msg = response_json.get("data") or response_json.get("operation", "unknown error")
            raise ValueError(f"Fed Tracker API error: {msg}")
        return response_json.get("data")

    # ------------------------------------------------------------------
    # Speaker endpoints
    # ------------------------------------------------------------------

    async def speaker_brief(
        self,
        speaker_name: str,
        theme: str | None = None,
    ) -> Any:
        """Get a high-level brief for a speaker."""
        client = await self._get_client()
        params: dict[str, Any] = {"speaker_name": speaker_name}
        if theme is not None:
            params["theme"] = theme
        response = await client.get("/speaker/brief", params=params)
        response.raise_for_status()
        return self._unwrap(response.json())

    async def speaker_question(
        self,
        speaker_name: str,
        question: str,
    ) -> Any:
        """Ask a question against stored artifacts for a speaker."""
        client = await self._get_client()
        response = await client.post(
            "/speaker/question",
            json={"speaker_name": speaker_name, "question": question},
        )
        response.raise_for_status()
        return self._unwrap(response.json())

    async def speaker_timeline(
        self,
        speaker_name: str,
        limit: int | None = None,
    ) -> Any:
        """Get a speaker's communication timeline."""
        client = await self._get_client()
        params: dict[str, Any] = {"speaker_name": speaker_name}
        if limit is not None:
            params["limit"] = limit
        response = await client.get("/speaker/timeline", params=params)
        response.raise_for_status()
        return self._unwrap(response.json())

    async def speaker_comparisons(
        self,
        speaker_name: str,
        comparison_type: str = "t_minus_1",
        limit: int | None = None,
    ) -> Any:
        """Get t-1 or other comparisons for a speaker."""
        client = await self._get_client()
        params: dict[str, Any] = {
            "speaker_name": speaker_name,
            "comparison_type": comparison_type,
        }
        if limit is not None:
            params["limit"] = limit
        response = await client.get("/speaker/comparisons", params=params)
        response.raise_for_status()
        return self._unwrap(response.json())

    async def speaker_orphaned(
        self,
        speaker_name: str,
        window_days: int = 75,
        min_emphasis: int = 3,
    ) -> Any:
        """Get orphaned concepts for a speaker."""
        client = await self._get_client()
        params: dict[str, Any] = {
            "speaker_name": speaker_name,
            "window_days": window_days,
            "min_emphasis": min_emphasis,
        }
        response = await client.get("/speaker/orphaned", params=params)
        response.raise_for_status()
        return self._unwrap(response.json())

    async def speaker_drift(
        self,
        speaker_name: str,
        theme: str = "INFLATION",
        window_days: int = 730,
    ) -> Any:
        """Get theme drift analysis for a speaker."""
        client = await self._get_client()
        params: dict[str, Any] = {
            "speaker_name": speaker_name,
            "theme": theme,
            "window_days": window_days,
        }
        response = await client.get("/speaker/drift", params=params)
        response.raise_for_status()
        return self._unwrap(response.json())

    # ------------------------------------------------------------------
    # Ingest endpoints
    # ------------------------------------------------------------------

    async def ingest_url(self, url: str, skip_existing: bool = True) -> Any:
        """Ingest a single URL into the tracker."""
        client = await self._get_client()
        response = await client.post(
            "/ingest/url",
            json={"url": url, "skip_existing": skip_existing},
        )
        response.raise_for_status()
        return self._unwrap(response.json())

    async def ingest_urls(self, urls: list[str], skip_existing: bool = True) -> Any:
        """Ingest multiple URLs into the tracker."""
        client = await self._get_client()
        response = await client.post(
            "/ingest/urls",
            json={"urls": urls, "skip_existing": skip_existing},
        )
        response.raise_for_status()
        return self._unwrap(response.json())

    async def ingest_markdown(
        self,
        markdown_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Ingest raw markdown text with optional metadata."""
        client = await self._get_client()
        body: dict[str, Any] = {"markdown_text": markdown_text}
        if metadata is not None:
            body["metadata"] = metadata
        response = await client.post("/ingest/markdown", json=body)
        response.raise_for_status()
        return self._unwrap(response.json())
