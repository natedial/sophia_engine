"""Core model management logic."""

from .types import (
    ModelType,
    ModelState,
    ModelConstraint,
    Model,
    # Legacy aliases
    CurveType,
    CurveState,
    CurveConstraint,
    Curve,
)
from .store import model_store, curve_store

__all__ = [
    "ModelType",
    "ModelState",
    "ModelConstraint",
    "Model",
    "model_store",
    # Legacy aliases
    "CurveType",
    "CurveState",
    "CurveConstraint",
    "Curve",
    "curve_store",
]
