"""Smoke and behavior tests for CausalWorldModelService."""

from __future__ import annotations


def test_service_module_imports():
    """The service module must parse and import without errors."""
    import sophia_episto.causal_service as svc  # noqa: F401

    assert hasattr(svc, "CausalWorldModelService")
