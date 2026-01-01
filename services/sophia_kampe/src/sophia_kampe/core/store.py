"""In-memory model store.

This is a placeholder implementation. In production, this would be
backed by a database or distributed cache.
"""

from datetime import date
from typing import Any

from .types import Model, ModelState


class ModelStore:
    """In-memory store for financial models (curves, surfaces, etc.).

    Provides:
        - Storage for fitted models
        - Lookup by ID, by date, by type
        - History tracking

    Note:
        This is a simple in-memory implementation for development.
        Production would use Redis, PostgreSQL, or similar.
    """

    def __init__(self) -> None:
        self._models: dict[str, Model] = {}
        self._by_date: dict[date, list[str]] = {}
        self._by_type: dict[str, list[str]] = {}

    def put(self, model: Model) -> None:
        """Store a model."""
        self._models[model.id] = model

        # Index by date
        if model.as_of_date not in self._by_date:
            self._by_date[model.as_of_date] = []
        if model.id not in self._by_date[model.as_of_date]:
            self._by_date[model.as_of_date].append(model.id)

        # Index by type
        type_key = model.model_type.value
        if type_key not in self._by_type:
            self._by_type[type_key] = []
        if model.id not in self._by_type[type_key]:
            self._by_type[type_key].append(model.id)

    def get(self, model_id: str) -> Model | None:
        """Get a model by ID."""
        return self._models.get(model_id)

    def get_by_date(self, as_of_date: date) -> list[Model]:
        """Get all models for a specific date."""
        model_ids = self._by_date.get(as_of_date, [])
        return [self._models[mid] for mid in model_ids if mid in self._models]

    def get_by_type(self, model_type: str) -> list[Model]:
        """Get all models of a specific type."""
        model_ids = self._by_type.get(model_type, [])
        return [self._models[mid] for mid in model_ids if mid in self._models]

    def get_latest(self, name: str | None = None, model_type: str | None = None) -> Model | None:
        """Get the most recent model, optionally filtered by name and/or type."""
        candidates = list(self._models.values())

        if name:
            candidates = [m for m in candidates if m.name == name]

        if model_type:
            candidates = [m for m in candidates if m.model_type.value == model_type]

        # Filter to published models
        published = [m for m in candidates if m.state == ModelState.PUBLISHED]

        if not published:
            return None

        # Return most recent by as_of_date
        return max(published, key=lambda m: m.as_of_date)

    def list_all(self, model_type: str | None = None) -> list[Model]:
        """List all models, optionally filtered by type."""
        if model_type:
            return self.get_by_type(model_type)
        return list(self._models.values())

    def delete(self, model_id: str) -> bool:
        """Delete a model by ID."""
        if model_id not in self._models:
            return False

        model = self._models.pop(model_id)

        # Remove from date index
        if model.as_of_date in self._by_date:
            self._by_date[model.as_of_date] = [
                mid for mid in self._by_date[model.as_of_date] if mid != model_id
            ]

        # Remove from type index
        type_key = model.model_type.value
        if type_key in self._by_type:
            self._by_type[type_key] = [
                mid for mid in self._by_type[type_key] if mid != model_id
            ]

        return True

    def clear(self) -> None:
        """Clear all models."""
        self._models.clear()
        self._by_date.clear()
        self._by_type.clear()

    def stats(self) -> dict[str, Any]:
        """Get store statistics."""
        by_state = {}
        by_type = {}

        for model in self._models.values():
            # Count by state
            by_state[model.state.value] = by_state.get(model.state.value, 0) + 1
            # Count by type
            by_type[model.model_type.value] = by_type.get(model.model_type.value, 0) + 1

        return {
            "total_models": len(self._models),
            "unique_dates": len(self._by_date),
            "by_state": by_state,
            "by_type": by_type,
        }


# Global singleton
model_store = ModelStore()

# Legacy alias
curve_store = model_store
