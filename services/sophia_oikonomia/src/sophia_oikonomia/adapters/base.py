"""Adapter boundary for external economic and market models."""

from abc import ABC, abstractmethod
from typing import Any

from ..core.types import (
    InputSnapshotRef,
    ModelDefinition,
    ModelExecutionResult,
    ModelRun,
    ModelTrigger,
)


class ModelAdapter(ABC):
    """Base adapter for promoted model wrappers."""

    @abstractmethod
    def build_input_snapshot(
        self,
        definition: ModelDefinition,
        trigger: ModelTrigger,
    ) -> InputSnapshotRef:
        """Construct an immutable input snapshot reference for a model run."""

    @abstractmethod
    def execute(
        self,
        definition: ModelDefinition,
        run: ModelRun,
    ) -> ModelExecutionResult:
        """Execute the model and return normalized run results."""
