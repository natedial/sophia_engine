"""Tests for API endpoints."""

from fastapi.testclient import TestClient


def test_health_check(client: TestClient) -> None:
    """Test health endpoint returns expected structure."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "sophia_arithmos"
    assert "version" in data
    assert data["computations_available"] > 0


def test_list_computation_types(client: TestClient) -> None:
    """Test computation types endpoint."""
    response = client.get("/compute/types")
    assert response.status_code == 200

    data = response.json()
    assert "types" in data
    assert "count" in data
    assert data["count"] > 0

    # Check that expected computations are registered
    types = data["types"]
    assert "mean" in types
    assert "median" in types
    assert "yoy_percent" in types
    assert "annualize_mom" in types


def test_compute_single(client: TestClient, sample_api_data: list[dict]) -> None:
    """Test single computation request."""
    response = client.post(
        "/compute",
        json={
            "data": sample_api_data,
            "computations": [{"type": "mean"}],
            "output": "latest",
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert "results" in data
    assert "mean" in data["results"]
    assert data["results"]["mean"]["latest"] is not None
    assert data["metadata"]["computations_succeeded"] == 1


def test_compute_multiple(client: TestClient, sample_api_data: list[dict]) -> None:
    """Test multiple computations in single request."""
    response = client.post(
        "/compute",
        json={
            "data": sample_api_data,
            "computations": [
                {"type": "mean"},
                {"type": "median"},
                {"type": "std_dev"},
            ],
            "output": "summary",
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data["results"]) == 3
    assert data["metadata"]["computations_succeeded"] == 3


def test_compute_with_custom_id(client: TestClient, sample_api_data: list[dict]) -> None:
    """Test computation with custom result ID."""
    response = client.post(
        "/compute",
        json={
            "data": sample_api_data,
            "computations": [
                {"type": "mean", "id": "my_average"},
            ],
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert "my_average" in data["results"]
    assert "mean" not in data["results"]


def test_compute_unknown_type(client: TestClient, sample_api_data: list[dict]) -> None:
    """Test graceful handling of unknown computation type."""
    response = client.post(
        "/compute",
        json={
            "data": sample_api_data,
            "computations": [{"type": "nonexistent_computation"}],
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert "error" in data["results"]["nonexistent_computation"]
    assert data["metadata"]["computations_failed"] == 1


def test_compute_with_params(client: TestClient, sample_api_data: list[dict]) -> None:
    """Test computation with parameters."""
    response = client.post(
        "/compute",
        json={
            "data": sample_api_data,
            "computations": [
                {"type": "percentile", "params": {"q": 75}},
            ],
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert data["results"]["percentile"]["latest"] is not None


def test_compute_full_output(client: TestClient, sample_api_data: list[dict]) -> None:
    """Test full series output."""
    response = client.post(
        "/compute",
        json={
            "data": sample_api_data,
            "computations": [{"type": "percent_change"}],
            "output": "full",
        },
    )
    assert response.status_code == 200

    data = response.json()
    # percent_change returns n-1 points
    assert data["results"]["percent_change"]["series"] is not None
    assert len(data["results"]["percent_change"]["series"]) == len(sample_api_data) - 1
