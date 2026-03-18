"""API tests for Sophia Oikonomia."""

from fastapi.testclient import TestClient


def _model_payload() -> dict[str, object]:
    return {
        "id": "bistro-v1",
        "name": "BISTRO Macro Forecast",
        "family": "macro",
        "owner": "rates-research",
        "description": "Monthly macro forecast model",
        "state": "champion",
        "production_slot": "macro_us_inflation",
        "dependencies": [
            {
                "source": "scrivener",
                "provider": "FRED",
                "kind": "series",
                "series_id": "CPIAUCSL",
            },
            {
                "source": "scrivener",
                "provider": "FRED",
                "kind": "release",
                "release_name": "Consumer Price Index",
            },
        ],
        "cadence": {
            "cron": "0 18 * * 1-5",
            "timezone": "America/New_York",
            "event_driven": True,
        },
        "execution": {
            "adapter_id": "bistro",
            "external_model_ref": "market_models:model_harness.models.bistro",
            "default_parameters": {"horizon": 2, "frequency": "M"},
        },
        "analysis": {
            "compare_to_prior": True,
            "compare_to_actuals": True,
            "compare_to_peers": False,
            "materiality_threshold": 0.1,
        },
    }


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "sophia_oikonomia"


def test_register_and_list_models(client: TestClient) -> None:
    create = client.post("/v1/models", json=_model_payload())
    assert create.status_code == 201

    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "bistro-v1"
    assert data[0]["state"] == "champion"

    slot = client.get("/v1/slots/macro_us_inflation/champion")
    assert slot.status_code == 200
    assert slot.json()["id"] == "bistro-v1"


def test_plan_trigger_for_release_dependency(client: TestClient) -> None:
    client.post("/v1/models", json=_model_payload())

    response = client.post(
        "/v1/triggers/plan",
        json={
            "trigger_type": "economic_release",
            "as_of": "2026-03-17T13:30:00Z",
            "source": "scrivener",
            "release_name": "Consumer Price Index",
            "reason": "cpi_release_landed",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["impacted_models"]) == 1
    assert data["impacted_models"][0]["model_id"] == "bistro-v1"


def test_run_completion_and_publication_flow(client: TestClient) -> None:
    client.post("/v1/models", json=_model_payload())

    create_run = client.post(
        "/v1/runs",
        json={
            "model_id": "bistro-v1",
            "requested_by": "scheduler",
            "trigger": {
                "trigger_type": "data_refresh",
                "as_of": "2026-03-17T17:00:00Z",
                "source": "scrivener",
                "series_ids": ["CPIAUCSL"],
                "reason": "daily_close_refresh",
            },
        },
    )
    assert create_run.status_code == 201
    run_id = create_run.json()["id"]
    assert create_run.json()["input_snapshot"]["payload"]["target_series_id"] == "CPIAUCSL"

    complete = client.post(
        f"/v1/runs/{run_id}/complete",
        json={
            "status": "succeeded",
            "output_summary": {"projection": {"core_cpi_3m_annualized": 3.2}},
            "insights": ["Inflation path re-accelerated versus prior run."],
            "quality_score": 0.78,
        },
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "succeeded"

    publish = client.post(
        "/v1/publications",
        json={
            "run_id": run_id,
            "summary": {"projection": {"core_cpi_3m_annualized": 3.2}},
            "insights": ["Inflation path re-accelerated versus prior run."],
        },
    )
    assert publish.status_code == 201
    publication = publish.json()
    assert publication["model_id"] == "bistro-v1"

    latest = client.get("/v1/publications/latest/bistro-v1")
    assert latest.status_code == 200
    assert latest.json()["run_id"] == run_id

    latest_slot = client.get("/v1/publications/latest/slot/macro_us_inflation")
    assert latest_slot.status_code == 200
    assert latest_slot.json()["run_id"] == run_id


def test_promotion_gates_required_for_champion(client: TestClient) -> None:
    baseline = client.post("/v1/models", json=_model_payload())
    assert baseline.status_code == 201

    payload = _model_payload()
    payload["id"] = "bistro-candidate"
    payload["state"] = "research"
    create = client.post("/v1/models", json=payload)
    assert create.status_code == 201

    failed = client.post(
        "/v1/models/bistro-candidate/promote",
        json={"target_state": "champion", "reviewer": "ops"},
    )
    assert failed.status_code == 422

    review = client.post(
        "/v1/models/bistro-candidate/review",
        json={
            "requested_state": "champion",
            "reviewer": "ops",
            "gate_results": [
                {"gate": "contract_tests", "status": "passed"},
                {"gate": "eval_replay", "status": "passed"},
                {"gate": "shadow_runs", "status": "passed"},
                {"gate": "ops_checks", "status": "passed"},
            ],
        },
    )
    assert review.status_code == 201

    promoted = client.post(
        "/v1/models/bistro-candidate/promote",
        json={"target_state": "champion", "reviewer": "ops"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["state"] == "champion"
    assert promoted.json()["promotion"]["rollback_model_id"] == "bistro-v1"

    prior = client.get("/v1/models/bistro-v1")
    assert prior.status_code == 200
    assert prior.json()["state"] == "shadow"


def test_only_champion_can_publish(client: TestClient) -> None:
    payload = _model_payload()
    payload["id"] = "bistro-shadow"
    payload["state"] = "shadow"
    payload["production_slot"] = "macro_alt_inflation"
    create = client.post("/v1/models", json=payload)
    assert create.status_code == 201

    run = client.post(
        "/v1/runs/execute",
        json={
            "model_id": "bistro-shadow",
            "requested_by": "scheduler",
            "trigger": {
                "trigger_type": "data_refresh",
                "as_of": "2026-03-18T17:00:00Z",
                "source": "scrivener",
                "series_ids": ["CPIAUCSL"],
            },
        },
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    publish = client.post(
        "/v1/publications",
        json={"run_id": run_id},
    )
    assert publish.status_code == 422


def test_execute_run_endpoint(client: TestClient) -> None:
    client.post("/v1/models", json=_model_payload())

    response = client.post(
        "/v1/runs/execute",
        json={
            "model_id": "bistro-v1",
            "requested_by": "scheduler",
            "trigger": {
                "trigger_type": "data_refresh",
                "as_of": "2026-03-18T17:00:00Z",
                "source": "scrivener",
                "series_ids": ["CPIAUCSL"],
                "reason": "cpi_refresh",
            },
        },
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["output_summary"]["forecast_count"] == 2
    assert run["insights"] == ["Inflation is projected to cool over the next two prints."]


def test_execute_trigger_endpoint(client: TestClient) -> None:
    client.post("/v1/models", json=_model_payload())

    response = client.post(
        "/v1/triggers/execute",
        json={
            "requested_by": "scheduler",
            "trigger": {
                "trigger_type": "data_refresh",
                "as_of": "2026-03-18T17:00:00Z",
                "source": "scrivener",
                "series_ids": ["CPIAUCSL"],
                "reason": "close_refresh",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["plan"]["impacted_models"]) == 1
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["status"] == "succeeded"
