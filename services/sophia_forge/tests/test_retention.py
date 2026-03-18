from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge.core.runtime import ForgeRuntime
from sophia_forge.evals.models import EvalCaseResult, EvalRunSummary
from sophia_forge_protocol.run_models import RunRequest, RunResult


def test_runtime_retention_cleanup_prunes_old_outputs(tmp_path: Path) -> None:
    settings = ForgeSettings(
        store_path=tmp_path / "forge_runs.db",
        output_dir=tmp_path / "runs",
        workspace_retention_days=1,
        environment_retention_days=1,
        run_artifact_retention_days=1,
        eval_artifact_retention_days=1,
    )
    runtime = ForgeRuntime(settings=settings)

    request = RunRequest(
        run_id="old-run",
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(tmp_path / "workspace"),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        verification_policy={"mode": "none", "steps": ()},
    )
    runtime.run_store.create_run(request)
    runtime.run_store.finish_run(
        RunResult(
            run_id="old-run",
            status="completed",
            summary="done",
            artifact_ids=("old-run_task_spec_001",),
        )
    )
    runtime.artifact_manager.run_dir("old-run").mkdir(parents=True, exist_ok=True)
    (runtime.artifact_manager.run_dir("old-run") / "task.json").write_text("{}", encoding="utf-8")

    eval_summary = runtime.artifact_manager.persist_eval_summary(
        eval_run_id="eval-old",
        summary=EvalRunSummary(
            corpus_name="test-corpus",
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
            pass_rate=1.0,
            results=(EvalCaseResult(
                case_id="case-1",
                name="case",
                passed=True,
                actual_status="completed",
                expected_status="completed",
            ),),
        ),
    )
    runtime.run_store.save_eval_run(eval_summary)

    workspace_dir = runtime.artifact_manager.workspaces_root() / "old-run"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    environment_dir = runtime.artifact_manager.environments_root() / "old-run"
    environment_dir.mkdir(parents=True, exist_ok=True)

    old_dt = datetime.now(UTC) - timedelta(days=3)
    old_text = old_dt.isoformat().replace("+00:00", "Z")
    old_timestamp = old_dt.timestamp()
    for path in (
        runtime.artifact_manager.run_dir("old-run"),
        runtime.artifact_manager.eval_dir("eval-old"),
        workspace_dir,
        environment_dir,
    ):
        os.utime(path, (old_timestamp, old_timestamp))

    with runtime.run_store._connect() as conn:
        conn.execute(
            """
            UPDATE forge_runs
            SET created_at = ?, updated_at = ?, completed_at = ?
            WHERE run_id = ?
            """,
            (old_text, old_text, old_text, "old-run"),
        )
        conn.execute(
            """
            UPDATE forge_eval_runs
            SET created_at = ?
            WHERE eval_run_id = ?
            """,
            (old_text, "eval-old"),
        )

    summary = runtime.inspect_retention()
    assert summary.workspaces.eligible_count == 1
    assert summary.environments.eligible_count == 1
    assert summary.run_artifacts.eligible_count == 1
    assert summary.eval_artifacts.eligible_count == 1

    cleanup = runtime.cleanup_retention()
    assert cleanup.workspaces.deleted_count == 1
    assert cleanup.environments.deleted_count == 1
    assert cleanup.run_artifacts.deleted_count == 1
    assert cleanup.eval_artifacts.deleted_count == 1
    assert not runtime.artifact_manager.run_dir("old-run").exists()
    assert not runtime.artifact_manager.eval_dir("eval-old").exists()
    assert runtime.run_store.get_run("old-run").artifact_ids == ()
    assert runtime.run_store.get_eval_run("eval-old").artifact_id == ""
