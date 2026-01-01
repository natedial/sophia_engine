"""API request and response schemas."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from ..core.types import ModelType, ModelState, ModelConstraint

# Legacy aliases
CurveType = ModelType
CurveState = ModelState
CurveConstraint = ModelConstraint


class FitCurveRequest(BaseModel):
    """Request to fit a new curve."""

    name: str = Field(..., description="Human-readable curve name")
    curve_type: CurveType = Field(default=CurveType.NELSON_SIEGEL)
    as_of_date: date = Field(..., description="Curve date")
    maturities: list[float] = Field(..., description="Maturities in years")
    yields: list[float] = Field(..., description="Corresponding yields")
    constraints: list[CurveConstraint] = Field(default_factory=list)
    auto_publish: bool = Field(default=False, description="Publish immediately if fit succeeds")


class RefineCurveRequest(BaseModel):
    """Request to refine an existing curve."""

    constraints: list[CurveConstraint] = Field(
        default_factory=list,
        description="Updated constraints to apply",
    )
    publish: bool = Field(default=False, description="Publish after refinement")


class CurveResponse(BaseModel):
    """Response containing curve/model details."""

    id: str
    name: str
    curve_type: CurveType
    state: CurveState
    as_of_date: date
    fitted_at: datetime | None
    published_at: datetime | None
    parameters: dict[str, Any] = Field(default_factory=dict)
    constraints: list[CurveConstraint]
    fit_metrics: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CurveListResponse(BaseModel):
    """Response containing list of curves."""

    curves: list[CurveResponse]
    count: int


class InterpolateRequest(BaseModel):
    """Request to interpolate yields from a curve."""

    curve_id: str
    maturities: list[float] = Field(..., description="Maturities to interpolate")


class InterpolateResponse(BaseModel):
    """Response with interpolated yields."""

    curve_id: str
    maturities: list[float]
    yields: list[float]
    as_of_date: date


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    version: str
    arithmos_status: str | None = None
    curves_count: int
