"""Shared test configuration."""

import pytest

from src.config import get_settings


@pytest.fixture(autouse=True)
def configure_scrivener_api_key(monkeypatch):
    """Keep privileged endpoint tests explicit and independent of developer env files."""
    monkeypatch.setenv("SCRIVENER_API_KEY", "test-scrivener-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
