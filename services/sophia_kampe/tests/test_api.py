"""Tests for API endpoints."""

from fastapi.testclient import TestClient


def test_health_check(client: TestClient) -> None:
    """Test health endpoint returns expected structure."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "sophia_kampe"
    assert "version" in data
    assert "curves_count" in data


def test_list_curves_empty(client: TestClient) -> None:
    """Test listing curves when store is empty."""
    response = client.get("/curves")
    assert response.status_code == 200

    data = response.json()
    assert data["curves"] == []
    assert data["count"] == 0


def test_get_curve_not_found(client: TestClient) -> None:
    """Test 404 for non-existent curve."""
    response = client.get("/curves/nonexistent")
    assert response.status_code == 404


def test_fit_curve_not_implemented(client: TestClient) -> None:
    """Test that fit endpoint returns 501 (scaffold)."""
    response = client.post(
        "/curves",
        json={
            "name": "US Treasury",
            "as_of_date": "2024-12-30",
            "maturities": [0.25, 0.5, 1, 2, 5, 10, 30],
            "yields": [4.5, 4.4, 4.3, 4.2, 4.1, 4.0, 3.9],
        },
    )
    assert response.status_code == 501
    assert "scaffold" in response.json()["detail"].lower()


def test_delete_curve_not_found(client: TestClient) -> None:
    """Test 404 when deleting non-existent curve."""
    response = client.delete("/curves/nonexistent")
    assert response.status_code == 404
