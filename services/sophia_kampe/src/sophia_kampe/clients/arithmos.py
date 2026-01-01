"""HTTP client for Sophia Arithmos computation service."""

from datetime import date
from typing import Any

import httpx

from ..config import settings


class ArithmosError(Exception):
    """Error from Arithmos service."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ArithmosClient:
    """Client for calling Sophia Arithmos computation service.

    Usage:
        async with ArithmosClient() as client:
            result = await client.compute(data, [{"type": "nelson_siegel"}])

    Or use the global singleton:
        from sophia_kampe.clients import arithmos_client
        await arithmos_client.compute(...)
    """

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = base_url or settings.arithmos.url
        self.timeout = timeout or settings.arithmos.timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )

    async def stop(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "ArithmosClient":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ArithmosClient not started. Call start() first.")
        return self._client

    async def health(self) -> dict[str, Any]:
        """Check Arithmos health."""
        response = await self.client.get("/health")
        response.raise_for_status()
        return response.json()

    async def list_computation_types(self) -> dict[str, Any]:
        """List available computation types."""
        response = await self.client.get("/compute/types")
        response.raise_for_status()
        return response.json()

    async def compute(
        self,
        data: list[dict[str, Any]],
        computations: list[dict[str, Any]],
        output: str = "latest",
    ) -> dict[str, Any]:
        """Execute computations on data.

        Args:
            data: List of observations [{"date": "2024-01-01", "value": 1.5}, ...]
            computations: List of computation specs [{"type": "mean"}, ...]
            output: Output format ("full", "latest", "summary")

        Returns:
            Computation results from Arithmos

        Raises:
            ArithmosError: If the request fails
        """
        try:
            response = await self.client.post(
                "/compute",
                json={
                    "data": data,
                    "computations": computations,
                    "output": output,
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise ArithmosError(
                f"Arithmos request failed: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise ArithmosError(f"Arithmos connection error: {e}") from e

    # -------------------------------------------------------------------------
    # Curve-specific convenience methods (to be expanded)
    # -------------------------------------------------------------------------

    async def fit_nelson_siegel(
        self,
        maturities: list[float],
        yields: list[float],
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        """Fit Nelson-Siegel model to yield data.

        Args:
            maturities: List of maturities in years
            yields: List of corresponding yields
            as_of_date: Date for the curve (defaults to today)

        Returns:
            Fitted parameters: beta0, beta1, beta2, tau

        Note:
            This is a placeholder. The actual nelson_siegel computation
            needs to be implemented in Arithmos first.
        """
        # TODO: Implement when nelson_siegel is added to Arithmos
        # For now, format data and call a placeholder
        if as_of_date is None:
            as_of_date = date.today()

        data = [
            {"date": as_of_date.isoformat(), "value": y, "maturity": m}
            for m, y in zip(maturities, yields)
        ]

        return await self.compute(
            data=data,
            computations=[{"type": "nelson_siegel"}],
            output="summary",
        )

    async def fit_svensson(
        self,
        maturities: list[float],
        yields: list[float],
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        """Fit Svensson model to yield data.

        Note:
            Placeholder - requires svensson computation in Arithmos.
        """
        if as_of_date is None:
            as_of_date = date.today()

        data = [
            {"date": as_of_date.isoformat(), "value": y, "maturity": m}
            for m, y in zip(maturities, yields)
        ]

        return await self.compute(
            data=data,
            computations=[{"type": "svensson"}],
            output="summary",
        )


# Global singleton instance
arithmos_client = ArithmosClient()
