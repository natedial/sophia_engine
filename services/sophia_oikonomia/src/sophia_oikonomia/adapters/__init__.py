"""Adapter interfaces for productionized economic model wrappers."""

from .bistro import BistroAdapter
from .base import ModelAdapter
from .hypothesis_test import ADAPTER_ID as HYPOTHESIS_TEST_ADAPTER_ID
from .hypothesis_test import HypothesisTestAdapter
from .registry import AdapterRegistry

__all__ = [
    "AdapterRegistry",
    "BistroAdapter",
    "HYPOTHESIS_TEST_ADAPTER_ID",
    "HypothesisTestAdapter",
    "ModelAdapter",
]
