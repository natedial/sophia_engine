"""Base computation class."""

import logging
import time
from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..config import settings
from .types import (
    ComputationResult,
    Observation,
    OutputMode,
    ParamSpec,
    PrecisionType,
)

logger = logging.getLogger("sophia_arithmos.computation")


class Computation(ABC):
    """Abstract base class for all computations.

    Subclasses must implement:
        - name: Unique identifier for this computation
        - description: Human-readable description
        - compute(): The actual computation logic

    Optional overrides:
        - params: Parameter specifications
        - precision_type: Which precision setting to use for rounding
    """

    name: str
    description: str
    params: dict[str, ParamSpec] = {}
    precision_type: PrecisionType = PrecisionType.DEFAULT

    def execute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode = OutputMode.LATEST,
    ) -> ComputationResult:
        """Execute the computation with validation and rounding.

        This is the public entry point. It validates parameters,
        calls the subclass compute() method, and rounds results.
        """
        start_time = time.perf_counter()
        logger.info(
            "Executing computation: %s | data_points=%d | output=%s | params=%s",
            self.name,
            len(data),
            output.value,
            params or {},
        )

        validated_params = self._validate_params(params)
        result = self.compute(data, validated_params, output)
        rounded_result = self._round_result(result)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "Completed computation: %s | elapsed=%.2fms",
            self.name,
            elapsed_ms,
        )

        return rounded_result

    @abstractmethod
    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        """Perform the computation. Implemented by subclasses."""
        pass

    def _validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate parameters against specs and apply defaults."""
        validated = {}

        for name, spec in self.params.items():
            if name in params:
                value = params[name]
                # Type coercion
                if spec.type == "int":
                    value = int(value)
                elif spec.type == "float":
                    value = float(value)
                elif spec.type == "bool":
                    if isinstance(value, bool):
                        pass
                    elif isinstance(value, str):
                        normalized = value.strip().lower()
                        if normalized in ("true", "1", "yes", "y", "t"):
                            value = True
                        elif normalized in ("false", "0", "no", "n", "f"):
                            value = False
                        else:
                            raise ValueError(f"{name} must be a boolean")
                    elif isinstance(value, (int, float)):
                        value = bool(value)
                    else:
                        raise ValueError(f"{name} must be a boolean")

                # Range validation
                if spec.min_value is not None and value < spec.min_value:
                    raise ValueError(f"{name} must be >= {spec.min_value}")
                if spec.max_value is not None and value > spec.max_value:
                    raise ValueError(f"{name} must be <= {spec.max_value}")

                # Choice validation
                if spec.choices is not None and value not in spec.choices:
                    raise ValueError(f"{name} must be one of {spec.choices}")

                validated[name] = value
            elif spec.required:
                raise ValueError(f"Missing required parameter: {name}")
            elif spec.default is not None:
                validated[name] = spec.default

        return validated

    def _get_precision(self) -> int:
        """Get the decimal precision for this computation."""
        precision_map = {
            PrecisionType.RATE: settings.precision.rate,
            PrecisionType.PERCENT: settings.precision.percent,
            PrecisionType.INDEX: settings.precision.index,
            PrecisionType.RATIO: settings.precision.ratio,
            PrecisionType.CURRENCY: settings.precision.currency,
            PrecisionType.DEFAULT: settings.precision.default,
        }
        return precision_map.get(self.precision_type, settings.precision.default)

    def _round_value(self, value: float | Decimal) -> float:
        """Round a value to the configured precision."""
        precision = self._get_precision()
        if isinstance(value, Decimal):
            quantize_str = "0." + "0" * precision
            rounded = value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
            return float(rounded)
        return round(value, precision)

    def _round_result(self, result: ComputationResult) -> ComputationResult:
        """Round all values in a computation result."""
        if result.series:
            result.series = [
                Observation(date=obs.date, value=self._round_value(obs.value))
                for obs in result.series
            ]

        if result.latest:
            result.latest = Observation(
                date=result.latest.date,
                value=self._round_value(result.latest.value)
            )

        # Round numeric values in summary
        if result.summary:
            result.summary = {
                k: self._round_value(v) if isinstance(v, (int, float, Decimal)) else v
                for k, v in result.summary.items()
            }

        return result

    def to_schema(self) -> dict[str, Any]:
        """Export computation spec for API discovery."""
        return {
            "name": self.name,
            "description": self.description,
            "params": {
                name: {
                    "type": spec.type,
                    "description": spec.description,
                    "required": spec.required,
                    "default": spec.default,
                }
                for name, spec in self.params.items()
            },
            "precision_type": self.precision_type.value,
        }
