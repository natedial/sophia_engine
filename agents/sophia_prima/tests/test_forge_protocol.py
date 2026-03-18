from __future__ import annotations

from sophia_forge_protocol.artifact_models import RunArtifact
from sophia_forge_protocol.event_models import RunEvent
from sophia_forge_protocol.run_models import (
    CapabilityAdded,
    ExecutionPolicy,
    FailureClassCount,
    CapabilityHandoff,
    CapabilityHandoffUpdate,
    RetentionSummary,
    RunMetricsSummary,
    RunRequest,
    RunResult,
    StructuredRunOutput,
    TaskTypeMetrics,
    run_output_schema,
)
from sophia_forge_protocol.verification_models import VerificationPolicy, VerificationResult


def test_run_result_defaults_success_from_status() -> None:
    result = RunResult(status="completed", summary="Implemented the missing scaffold.")
    assert result.success is True


def test_run_result_allows_explicit_success_override() -> None:
    result = RunResult(
        success=False,
        status="completed",
        summary="Backend reported completed output but process failed.",
        error="non-zero exit",
    )
    assert result.success is False


def test_run_output_schema_tracks_required_structured_fields() -> None:
    schema = run_output_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "status",
        "summary",
        "changed_files",
        "verification",
        "follow_ups",
    ]


def test_structured_run_output_accepts_backend_payload_shape() -> None:
    output = StructuredRunOutput.model_validate(
        {
            "status": "completed",
            "summary": "Implemented the requested pipeline hook.",
            "changed_files": ["services/foo/pipeline.py"],
            "verification": ["pytest services/foo/tests/test_pipeline.py"],
            "follow_ups": [],
            "capabilities_added": [
                {
                    "capability_type": "tool",
                    "tool_name": "get_market_ohlcv",
                    "service_name": "scrivener",
                    "registration_path": "services/sophia_pylon/src/pylon/core.py",
                    "description": "Get OHLCV market data.",
                    "when_to_use": "Use when the user asks for historical OHLCV data.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                        },
                        "required": ["symbol"],
                    },
                    "usage_example": {"symbol": "ZN"},
                }
            ],
        }
    )
    assert output.changed_files == ("services/foo/pipeline.py",)
    assert output.capabilities_added[0].tool_name == "get_market_ohlcv"
    assert output.capabilities_added[0].usage_example == {"symbol": "ZN"}


def test_run_request_uses_verification_policy_defaults() -> None:
    request = RunRequest(
        client_name="sophia_prima",
        task="Implement the missing scheduler hook.",
        workspace_root="/tmp/workspace",
        backend="codex",
        timeout_sec=30.0,
        verification_policy=VerificationPolicy(),
    )
    assert request.verification_policy.mode == "auto"


def test_run_request_syncs_top_level_roots_into_execution_policy() -> None:
    request = RunRequest(
        client_name="sophia_prima",
        task="Implement the missing scheduler hook.",
        workspace_root="/tmp/workspace",
        readable_roots=("/tmp/read",),
        writable_roots=("/tmp/write",),
        backend="codex",
        timeout_sec=30.0,
    )
    assert request.execution_policy.readable_roots == ("/tmp/read",)
    assert request.execution_policy.writable_roots == ("/tmp/write",)


def test_run_request_syncs_execution_policy_roots_back_to_top_level() -> None:
    request = RunRequest(
        client_name="sophia_prima",
        task="Implement the missing scheduler hook.",
        workspace_root="/tmp/workspace",
        backend="codex",
        timeout_sec=30.0,
        execution_policy=ExecutionPolicy(
            readable_roots=("/tmp/read",),
            writable_roots=("/tmp/write",),
        ),
    )
    assert request.readable_roots == ("/tmp/read",)
    assert request.writable_roots == ("/tmp/write",)


def test_execution_policy_supports_environment_and_secret_controls() -> None:
    policy = ExecutionPolicy(
        environment_strategy="ephemeral",
        environment_cleanup_policy="cleanup_on_success",
        secret_env_vars=("OPENAI_API_KEY",),
    )

    assert policy.environment_strategy == "ephemeral"
    assert policy.environment_cleanup_policy == "cleanup_on_success"
    assert policy.secret_env_vars == ("OPENAI_API_KEY",)


def test_capability_handoff_update_serializes_entries() -> None:
    update = CapabilityHandoffUpdate(
        entries=(
            CapabilityHandoff(
                tool_name="get_market_ohlcv",
                service_name="scrivener",
                registration_path="services/sophia_pylon/src/pylon/core.py",
                usage_example={"symbol": "ZN"},
            ),
        )
    )

    assert update.entries[0].tool_name == "get_market_ohlcv"


def test_run_result_keeps_capabilities_added() -> None:
    result = RunResult(
        run_id="forge_run_001",
        status="completed",
        summary="Added a new tool.",
        artifact_ids=("task_spec_001", "run_result_001"),
        capabilities_added=(
            CapabilityAdded(
                tool_name="get_market_ohlcv",
                service_name="scrivener",
                registration_path="services/sophia_pylon/src/pylon/core.py",
                description="Get OHLCV market data.",
                when_to_use="Use when the user asks for historical OHLCV data.",
                input_schema={
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
                usage_example={"symbol": "ZN"},
            ),
        ),
    )
    assert result.capabilities_added[0].tool_name == "get_market_ohlcv"
    assert result.artifact_ids == ("task_spec_001", "run_result_001")


def test_capability_added_accepts_legacy_string_usage_example() -> None:
    capability = CapabilityAdded(
        tool_name="get_market_ohlcv",
        service_name="scrivener",
        registration_path="services/sophia_pylon/src/pylon/core.py",
        usage_example='{"symbol":"ZN"}',
    )

    assert capability.usage_example == {"symbol": "ZN"}


def test_run_event_uses_canonical_event_taxonomy() -> None:
    event = RunEvent(
        run_id="forge_run_001",
        sequence=1,
        event_type="run_started",
        timestamp="2026-03-16T20:00:00Z",
        payload={"backend": "codex"},
    )

    assert event.event_type == "run_started"


def test_run_artifact_supports_payload_metadata() -> None:
    artifact = RunArtifact(
        artifact_id="summary_001",
        run_id="forge_run_001",
        artifact_type="summary",
        content_type="application/json",
        path=".sophia/forge/runs/forge_run_001/summary.json",
        payload={"status": "completed"},
        created_at="2026-03-16T20:00:00Z",
    )

    assert artifact.payload == {"status": "completed"}


def test_verification_result_serializes_structured_outcome() -> None:
    result = VerificationResult(
        name="targeted_pytest",
        status="passed",
        command="uv run pytest services/foo/tests/test_pipeline.py",
        required=True,
        details="1 passed",
    )

    assert result.status == "passed"


def test_run_metrics_summary_serializes_operational_counts() -> None:
    summary = RunMetricsSummary(
        total_runs=3,
        completed_runs=2,
        failed_runs=1,
        success_rate=2 / 3,
        retry_rate=1 / 3,
        runs_with_verification=1,
        verification_pass_rate=1.0,
        common_failure_classes=(FailureClassCount(failure_class="backend_launch_failed", count=1),),
        task_types=(TaskTypeMetrics(task_type="capability", total_runs=3, completed_runs=2),),
    )

    assert summary.common_failure_classes[0].failure_class == "backend_launch_failed"
    assert summary.task_types[0].task_type == "capability"


def test_retention_summary_serializes_cleanup_state() -> None:
    summary = RetentionSummary(
        dry_run=True,
        workspaces={"category": "workspaces", "eligible_count": 1, "eligible_paths": ("/tmp/w1",)},
        environments={"category": "environments"},
        run_artifacts={"category": "run_artifacts"},
        eval_artifacts={"category": "eval_artifacts"},
    )

    assert summary.workspaces.eligible_count == 1
    assert summary.workspaces.eligible_paths == ("/tmp/w1",)
