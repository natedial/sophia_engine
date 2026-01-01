"""Base class for all financial models."""

from abc import ABC, abstractmethod
from typing import Any

from ..core.types import Model, ModelConstraint


class FinancialModel(ABC):
    """Abstract base class for all financial model implementations.

    Each model type (Nelson-Siegel, SABR, etc.) should subclass this
    and implement the fitting and evaluation methods.
    """

    @abstractmethod
    def fit(
        self,
        input_data: dict[str, Any],
        constraints: list[ModelConstraint] | None = None,
    ) -> dict[str, Any]:
        """Fit the model to input data.

        Args:
            input_data: Model-specific input (e.g., {"maturities": [...], "yields": [...]})
            constraints: Optional constraints to apply during fitting

        Returns:
            Fitted parameters as a dictionary
        """
        pass

    @abstractmethod
    def evaluate(self, parameters: dict[str, Any], points: list[Any]) -> list[float]:
        """Evaluate the fitted model at given points.

        Args:
            parameters: Fitted model parameters
            points: Points at which to evaluate (e.g., maturities, strikes)

        Returns:
            Evaluated values at each point
        """
        pass

    def compute_metrics(
        self,
        parameters: dict[str, Any],
        input_data: dict[str, Any],
    ) -> dict[str, float]:
        """Compute fit quality metrics.

        Args:
            parameters: Fitted parameters
            input_data: Original input data

        Returns:
            Quality metrics (rmse, r_squared, etc.)
        """
        # Default implementation - can be overridden
        return {}
