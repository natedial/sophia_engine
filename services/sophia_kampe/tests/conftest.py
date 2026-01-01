"""Pytest fixtures for Sophia Kampe tests."""

import pytest
from fastapi.testclient import TestClient

from sophia_kampe.main import app
from sophia_kampe.core import curve_store


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_store() -> None:
    """Clear curve store before each test."""
    curve_store.clear()
