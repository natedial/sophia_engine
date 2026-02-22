"""HTTP client for Sophia Canvas visualization service."""

from typing import Any

from pylon.clients.base import BaseClient


class CanvasClient(BaseClient):
    """Client for communicating with the sophia_canvas service.

    Handles all HTTP operations for canvas and chart management.
    """

    @property
    def name(self) -> str:
        return "canvas"

    async def health_check(self) -> bool:
        """Check if the canvas service is available."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    # ----- Canvas Operations -----

    async def create_canvas(self, session_id: str, user_id: str | None = None, name: str = "Untitled Dashboard") -> dict[str, Any]:
        """Create a new canvas for a session."""
        client = await self._get_client()
        response = await client.post(
            "/canvases",
            json={"session_id": session_id, "user_id": user_id, "name": name},
        )
        response.raise_for_status()
        return response.json()

    async def get_canvas(self, canvas_id: str) -> dict[str, Any]:
        """Get a canvas by ID with all its charts."""
        client = await self._get_client()
        response = await client.get(f"/canvases/{canvas_id}")
        response.raise_for_status()
        return response.json()

    async def list_canvases(self, session_id: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
        """List canvases, optionally filtered."""
        client = await self._get_client()
        params = {}
        if session_id:
            params["session_id"] = session_id
        if user_id:
            params["user_id"] = user_id
        response = await client.get("/canvases", params=params)
        response.raise_for_status()
        return response.json()

    async def delete_canvas(self, canvas_id: str) -> dict[str, str]:
        """Delete a canvas and all its charts."""
        client = await self._get_client()
        response = await client.delete(f"/canvases/{canvas_id}")
        response.raise_for_status()
        return response.json()

    async def update_layout(self, canvas_id: str, layout: list[dict[str, Any]]) -> dict[str, Any]:
        """Update chart positions in the canvas layout."""
        client = await self._get_client()
        response = await client.patch(
            f"/canvases/{canvas_id}/layout",
            json={"layout": layout},
        )
        response.raise_for_status()
        return response.json()

    # ----- Chart Operations -----

    async def create_chart(
        self,
        canvas_id: str,
        chart_type: str,
        spec: dict[str, Any],
        title: str | None = None,
        data_query: dict[str, Any] | None = None,
        position: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new chart in a canvas."""
        client = await self._get_client()
        payload: dict[str, Any] = {
            "chart_type": chart_type,
            "spec": spec,
        }
        if title:
            payload["title"] = title
        if data_query:
            payload["data_query"] = data_query
        if position:
            payload["position"] = position

        response = await client.post(f"/canvases/{canvas_id}/charts", json=payload)
        response.raise_for_status()
        return response.json()

    async def get_chart(self, canvas_id: str, chart_id: str) -> dict[str, Any]:
        """Get a specific chart by ID."""
        client = await self._get_client()
        response = await client.get(f"/canvases/{canvas_id}/charts/{chart_id}")
        response.raise_for_status()
        return response.json()

    async def update_chart(
        self,
        canvas_id: str,
        chart_id: str,
        title: str | None = None,
        spec: dict[str, Any] | None = None,
        data_query: dict[str, Any] | None = None,
        position: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a chart."""
        client = await self._get_client()
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if spec is not None:
            payload["spec"] = spec
        if data_query is not None:
            payload["data_query"] = data_query
        if position is not None:
            payload["position"] = position

        response = await client.patch(
            f"/canvases/{canvas_id}/charts/{chart_id}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def delete_chart(self, canvas_id: str, chart_id: str) -> dict[str, str]:
        """Delete a chart from a canvas."""
        client = await self._get_client()
        response = await client.delete(f"/canvases/{canvas_id}/charts/{chart_id}")
        response.raise_for_status()
        return response.json()
