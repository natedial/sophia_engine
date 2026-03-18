"""Adapter interfaces for productionized economic model wrappers."""

from .bistro import BistroAdapter
from .base import ModelAdapter
from .registry import AdapterRegistry

__all__ = ["AdapterRegistry", "BistroAdapter", "ModelAdapter"]
