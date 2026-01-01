"""API request and response schemas."""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ObservationInput(BaseModel):
    """Input observation for computation."""

    date: date
    value: float


class ComputationRequest(BaseModel):
    """Request for a single computation."""

    type: str = Field(..., description="Computation type (e.g., 'mean', 'yoy_percent')")
    id: str | None = Field(None, description="Optional key for result (defaults to type)")
    params: dict[str, Any] = Field(default_factory=dict, description="Computation parameters")


class ComputeRequest(BaseModel):
    """Request body for POST /compute."""

    data: list[ObservationInput] = Field(
        ...,
        min_length=1,
        description="Time series data as list of {date, value} observations",
    )
    computations: list[ComputationRequest] = Field(
        ...,
        min_length=1,
        description="List of computations to perform",
    )
    output: str = Field(
        default="latest",
        description="Output format: 'full' (all points), 'latest' (most recent), 'summary'",
    )

    @field_validator("output")
    @classmethod
    def validate_output(cls, v: str) -> str:
        if v not in ("full", "latest", "summary"):
            raise ValueError("output must be 'full', 'latest', or 'summary'")
        return v


class ObservationOutput(BaseModel):
    """Output observation from computation."""

    date: date
    value: float


class ComputationResultOutput(BaseModel):
    """Result of a single computation."""

    series: list[ObservationOutput] | None = None
    latest: ObservationOutput | None = None
    summary: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ComputeResponse(BaseModel):
    """Response body for POST /compute."""

    results: dict[str, ComputationResultOutput]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComputationTypeInfo(BaseModel):
    """Information about a computation type."""

    name: str
    description: str
    params: dict[str, dict[str, Any]]
    precision_type: str


class ComputationTypesResponse(BaseModel):
    """Response body for GET /compute/types."""

    types: dict[str, ComputationTypeInfo]
    count: int


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str
    service: str
    version: str
    computations_available: int
