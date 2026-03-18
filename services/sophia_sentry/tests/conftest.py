"""Pytest fixtures for Sophia Sentry."""

import pytest
from fastapi.testclient import TestClient

from sophia_sentry.main import app, store


@pytest.fixture(autouse=True)
def clear_store() -> None:
    """Reset persisted state before each test."""
    store.reset()


@pytest.fixture
def client() -> TestClient:
    """Test client."""
    return TestClient(app)
