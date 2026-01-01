"""Pytest fixtures for Sophia Arithmos tests."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from sophia_arithmos.main import app
from sophia_arithmos.core.types import Observation


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def sample_observations() -> list[Observation]:
    """Create sample observation data for testing."""
    base_date = date(2024, 1, 1)
    return [
        Observation(date=base_date + timedelta(days=i * 30), value=100 + i * 2.5)
        for i in range(12)
    ]


@pytest.fixture
def sample_api_data() -> list[dict]:
    """Create sample data in API request format."""
    base_date = date(2024, 1, 1)
    return [
        {"date": (base_date + timedelta(days=i * 30)).isoformat(), "value": 100 + i * 2.5}
        for i in range(12)
    ]


@pytest.fixture
def monthly_rate_data() -> list[dict]:
    """Sample month-over-month rate data for compounding tests."""
    base_date = date(2024, 1, 1)
    # ~0.25% MoM ≈ ~3% annualized
    return [
        {"date": (base_date + timedelta(days=i * 30)).isoformat(), "value": 0.25}
        for i in range(12)
    ]
