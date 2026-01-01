"""Core type definitions for Sophia Kampe."""

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelType(str, Enum):
    """Supported financial model types."""

    # Yield Curves
    NELSON_SIEGEL = "nelson_siegel"
    SVENSSON = "svensson"
    CUBIC_SPLINE = "cubic_spline"
    POLYNOMIAL = "polynomial"
    ZERO_CURVE = "zero_curve"
    FORWARD_CURVE = "forward_curve"

    # Volatility Surfaces
    SABR = "sabr"
    SVI = "svi"
    LOCAL_VOL = "local_vol"
    IMPLIED_VOL = "implied_vol"

    # Credit
    HAZARD_CURVE = "hazard_curve"
    CREDIT_SPREAD = "credit_spread"


class ModelState(str, Enum):
    """Lifecycle state of a model."""

    PENDING = "pending"         # Awaiting initial fit
    FITTED = "fitted"           # Successfully fitted
    REFINING = "refining"       # Being refined with constraints
    PUBLISHED = "published"     # Ready for consumption
    STALE = "stale"             # Needs refresh
    ERROR = "error"             # Fitting failed


class ModelConstraint(BaseModel):
    """Constraint applied to model fitting."""

    model_config = ConfigDict(extra="forbid")

    name: str
    constraint_type: str                    # "min", "max", "equal", "range"
    target: str                             # What to constrain: "beta0", "slope_at_0", "atm_vol", etc.
    value: float | None = None              # For min/max/equal
    min_value: float | None = None          # For range
    max_value: float | None = None          # For range
    weight: float = 1.0                     # Penalty weight for soft constraints


class Model(BaseModel):
    """A fitted financial model (curve, surface, etc.) with lifecycle management."""

    model_config = ConfigDict(extra="forbid")

    id: str                                 # Unique identifier
    name: str                               # Human-readable name
    model_type: ModelType
    state: ModelState = ModelState.PENDING

    # Timing
    as_of_date: date                        # Model date
    fitted_at: datetime | None = None       # When last fitted
    published_at: datetime | None = None    # When published

    # Fit details - flexible to support different model types
    parameters: dict[str, Any] = Field(default_factory=dict)
    constraints: list[ModelConstraint] = Field(default_factory=list)

    # Input data - flexible structure for different model types
    input_data: dict[str, Any] = Field(default_factory=dict)

    # Quality metrics
    fit_metrics: dict[str, float] = Field(default_factory=dict)  # rmse, r_squared, etc.

    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)


# Legacy aliases for backward compatibility during transition
CurveType = ModelType
CurveState = ModelState
CurveConstraint = ModelConstraint
Curve = Model
