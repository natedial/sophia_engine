"""API tests for Sophia Sentry."""

from fastapi.testclient import TestClient


def _numeric_watch_payload() -> dict[str, object]:
    return {
        "id": "watch-ust10y-threshold",
        "name": "10Y Yield Threshold",
        "kind": "numeric_threshold",
        "owner": "rates-desk",
        "description": "Alert when 10Y yield breaks above 5%.",
        "spec": {
            "signal_key": "ust10y_yield",
            "threshold": 5.0,
            "delta_threshold": 0.25,
            "direction": "above",
        },
        "tags": ["rates", "macro"],
        "delivery_channels": ["inbox"],
    }


def _revision_watch_payload() -> dict[str, object]:
    return {
        "id": "watch-core-cpi-revision",
        "name": "Core CPI Revision Watch",
        "kind": "model_revision",
        "owner": "macro-pm",
        "description": "Alert on material inflation projection revisions.",
        "spec": {
            "production_slot": "macro_us_inflation",
            "metric_key": "core_cpi_3m_annualized",
            "minimum_absolute_delta": 0.3,
        },
        "delivery_channels": ["inbox", "dashboard"],
    }


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "sophia_sentry"


def test_register_and_list_watches(client: TestClient) -> None:
    create = client.post("/v1/watches", json=_numeric_watch_payload())
    assert create.status_code == 201

    response = client.get("/v1/watches")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "watch-ust10y-threshold"


def test_numeric_threshold_watch_emits_event(client: TestClient) -> None:
    client.post("/v1/watches", json=_numeric_watch_payload())

    response = client.post(
        "/v1/watches/watch-ust10y-threshold/evaluate",
        json={
            "as_of": "2026-03-18T14:00:00Z",
            "source": "data_trigger",
            "observations": {"ust10y_yield": 5.08},
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["triggered"] is True
    assert result["reason"] == "threshold_triggered"

    events = client.get("/v1/events")
    assert events.status_code == 200
    payload = events.json()
    assert len(payload) == 1
    assert payload[0]["watch_id"] == "watch-ust10y-threshold"


def test_model_revision_watch_emits_event(client: TestClient) -> None:
    client.post("/v1/watches", json=_revision_watch_payload())

    response = client.post(
        "/v1/watches/watch-core-cpi-revision/evaluate",
        json={
            "as_of": "2026-03-18T15:00:00Z",
            "source": "model_trigger",
            "observations": {
                "current_projection": {"core_cpi_3m_annualized": 3.4},
                "prior_projection": {"core_cpi_3m_annualized": 3.0},
            },
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["triggered"] is True
    assert result["reason"] == "revision_triggered"


def test_batch_evaluate_only_enabled_watches(client: TestClient) -> None:
    client.post("/v1/watches", json=_numeric_watch_payload())
    disabled = _revision_watch_payload()
    disabled["id"] = "watch-disabled"
    disabled["state"] = "disabled"
    client.post("/v1/watches", json=disabled)

    response = client.post(
        "/v1/evaluate",
        json={
            "as_of": "2026-03-18T16:00:00Z",
            "source": "cron",
            "observations": {"ust10y_yield": 4.75},
        },
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["watch_id"] == "watch-ust10y-threshold"
    assert results[0]["triggered"] is False


def test_oikonomia_publication_hook_evaluates_matching_revision_watches(client: TestClient) -> None:
    client.post("/v1/watches", json=_revision_watch_payload())
    other = _revision_watch_payload()
    other["id"] = "watch-other-slot"
    other["spec"] = {
        "production_slot": "macro_us_growth",
        "metric_key": "core_cpi_3m_annualized",
        "minimum_absolute_delta": 0.3,
    }
    client.post("/v1/watches", json=other)

    response = client.post(
        "/v1/integrations/oikonomia/publications",
        json={
            "model_id": "bistro-v1",
            "production_slot": "macro_us_inflation",
            "as_of": "2026-03-18T15:00:00Z",
            "published_at": "2026-03-18T15:01:00Z",
            "current_summary": {"core_cpi_3m_annualized": 3.5},
            "prior_summary": {"core_cpi_3m_annualized": 3.1},
            "insights": ["Inflation projection revised higher."],
        },
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["watch_id"] == "watch-core-cpi-revision"
    assert results[0]["triggered"] is True
