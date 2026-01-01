"""Core type definitions for Sophia Arithmos."""

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class OutputMode(str, Enum):
    """Output format options for computation results."""

    FULL = "full"           # Return complete series
    LATEST = "latest"       # Return only most recent value
    SUMMARY = "summary"     # Return statistical summary


class PrecisionType(str, Enum):
    """Precision categories for rounding."""

    RATE = "rate"           # Interest rates
    PERCENT = "percent"     # Percentages
    INDEX = "index"         # Index values
    RATIO = "ratio"         # Ratios
    CURRENCY = "currency"   # Dollar amounts
    DEFAULT = "default"     # Fallback


class Observation(BaseModel):
    """A single data point in a time series."""

    model_config = ConfigDict(ser_json_timedelta="iso8601")

    date: date
    value: float

    @field_serializer("date")
    def serialize_date(self, v: date) -> str:
        return v.isoformat()


class ComputationResult(BaseModel):
    """Result of a computation."""

    series: list[Observation] | None = None
    latest: Observation | None = None
    summary: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComputationSpec(BaseModel):
    """Specification for a computation to execute."""

    type: str
    id: str | None = None           # Optional key for result (defaults to type)
    params: dict[str, Any] = Field(default_factory=dict)


class ParamSpec(BaseModel):
    """Specification for a computation parameter."""

    type: str                       # "int", "float", "bool", "str"
    description: str
    required: bool = False
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    choices: list[Any] | None = None
