"""Registry for productionized economic model adapters."""

from .base import ModelAdapter


class AdapterRegistry:
    """Simple adapter registry keyed by adapter ID."""

    def __init__(self) -> None:
        self._adapters: dict[str, ModelAdapter] = {}

    def register(self, adapter_id: str, adapter: ModelAdapter) -> None:
        self._adapters[adapter_id] = adapter

    def get(self, adapter_id: str) -> ModelAdapter | None:
        return self._adapters.get(adapter_id)

    def list_adapter_ids(self) -> list[str]:
        return sorted(self._adapters.keys())
