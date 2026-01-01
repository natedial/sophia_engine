"""Computation implementations.

Import all computation modules to trigger registration with the global registry.
"""

from . import descriptive
from . import compounding
from . import period
from . import regression
from . import transform

__all__ = [
    "descriptive",
    "compounding",
    "period",
    "regression",
    "transform",
]
