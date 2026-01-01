"""Arithmos client - statistical and econometric computation."""

from typing import Any

from pylon.clients.base import BaseClient


class ArithmosClient(BaseClient):
    """
    HTTP client for the Arithmos computation service.

    Provides access to:
    - Descriptive statistics (mean, median, std_dev, percentiles)
    - Compounding and annualization
    - Period comparisons (YoY, MoM)
    - Regression (linear, multiple, rolling)
    - Transformations (percent_change, log, normalize, moving_average)
    """

    @property
    def name(self) -> str:
        return "arithmos"

    async def health_check(self) -> bool:
        """Check if Arithmos service is available."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def get_computation_types(self) -> dict[str, Any]:
        """List all available computation types with their parameters."""
        client = await self._get_client()
        response = await client.get("/compute/types")
        response.raise_for_status()
        return response.json()

    async def compute(
        self,
        data: list[dict[str, Any]],
        computations: list[dict[str, Any]],
        output: str = "latest",
    ) -> dict[str, Any]:
        """
        Execute computations on time series data.

        Args:
            data: Time series as list of {date, value} observations
            computations: List of computations to run, each with {type, ...params}
            output: Output mode - "latest", "all", or "summary"

        Returns:
            Results for each computation with metadata
        """
        client = await self._get_client()
        response = await client.post(
            "/compute",
            json={
                "data": data,
                "computations": computations,
                "output": output,
            },
        )
        response.raise_for_status()
        return response.json()
