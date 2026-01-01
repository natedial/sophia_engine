"""Computation registry for dynamic lookup."""

import logging
from typing import Type

from .base import Computation

logger = logging.getLogger("sophia_arithmos.registry")


class ComputationRegistry:
    """Registry for computation types.

    Allows dynamic registration and lookup of computations by name.
    """

    def __init__(self) -> None:
        self._computations: dict[str, Computation] = {}

    def register(self, computation_class: Type[Computation]) -> Type[Computation]:
        """Register a computation class. Can be used as a decorator."""
        instance = computation_class()
        self._computations[instance.name] = instance
        logger.debug("Registered computation: %s", instance.name)
        return computation_class

    def get(self, name: str) -> Computation | None:
        """Get a computation by name."""
        computation = self._computations.get(name)
        if computation is None:
            logger.warning("Computation lookup failed: '%s' not found", name)
        else:
            logger.debug("Computation lookup: '%s' found", name)
        return computation

    def list_all(self) -> dict[str, Computation]:
        """List all registered computations."""
        return dict(self._computations)

    def list_schemas(self) -> dict[str, dict]:
        """List schemas for all registered computations."""
        return {
            name: comp.to_schema()
            for name, comp in self._computations.items()
        }


# Global registry instance
registry = ComputationRegistry()


def get_computation(name: str) -> Computation | None:
    """Get a computation by name from the global registry."""
    return registry.get(name)


def list_computations() -> dict[str, Computation]:
    """List all registered computations."""
    return registry.list_all()
