"""Adapter interfaces for productionized economic model wrappers."""

from .base import ModelAdapter
from .bistro import BistroAdapter
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
