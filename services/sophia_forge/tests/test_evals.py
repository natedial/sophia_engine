from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge.core.runtime import ForgeRuntime
from sophia_forge.evals import EvalReplayRunner, load_eval_cases
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge_protocol.verification_models import VerificationResult


def test_load_eval_cases_reads_json_corpus(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "case.json").write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "name": "Simple success case",
                "request": {
                    "run_id": "eval-1",
                    "client_name": "sophia_prima",
                    "task": "Implement a tool.",
                    "workspace_root": str(tmp_path),
                    "writable_roots": [str(tmp_path)],
                    "readable_roots": [str(tmp_path)],
                    "backend": "codex",
                    "timeout_sec": 30.0,
                    "verification_policy": {"mode": "none", "steps": []},
                    "metadata": {"task_type": "capability"},
                },
                "expectation": {"status": "completed"},
            }
        ),
        encoding="utf-8",
    )

    cases = load_eval_cases(corpus_dir)

    assert len(cases) == 1
    assert cases[0].case_id == "case-1"
    assert cases[0].request.backend == "codex"


def test_eval_replay_runner_scores_cases_against_expectations(tmp_path: Path) -> None:
    success_request = RunRequest(
        run_id="eval-success",
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(tmp_path),
        writable_roots=(str(tmp_path),),
        readable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        verification_policy={"mode": "explicit", "steps": ()},
        metadata={"task_type": "capability"},
    )
    failure_request = success_request.model_copy(
        update={
            "run_id": "eval-failure",
            "task": "Broken run.",
        }
    )
    cases = load_eval_cases(_write_eval_corpus(tmp_path, success_request, failure_request))

    async def _fake_executor(request: RunRequest) -> RunResult:
        if request.run_id == "eval-failure":
            return RunResult(
                run_id=request.run_id,
                status="failed",
                summary="",
                error="backend launch failed: missing binary",
            )
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Implemented the tool.",
            changed_files=("services/foo/tool.py",),
        )

    class _FakeVerificationRunner:
        async def run(self, request: RunRequest, result: RunResult) -> tuple[VerificationResult, ...]:
            if request.run_id == "eval-success":
                return (
                    VerificationResult(
                        name="smoke_check",
                        status="passed",
                        command="printf ok",
                        required=True,
                        details="ok",
                    ),
                )
            return ()

    runner = EvalReplayRunner(
        executor=_fake_executor,
        verification_runner=_FakeVerificationRunner(),
    )

    summary = asyncio.run(runner.run_cases(cases, corpus_name="tmp_corpus"))

    assert summary.total_cases == 2
    assert summary.passed_cases == 2
    assert summary.failed_cases == 0
    by_case_id = {result.case_id: result for result in summary.results}
    assert by_case_id["eval-success"].passed is True
    assert by_case_id["eval-failure"].actual_failure_class == "backend_launch_failed"


def test_runtime_can_replay_eval_corpus(tmp_path: Path) -> None:
    request = RunRequest(
        run_id="eval-runtime-success",
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(tmp_path),
        writable_roots=(str(tmp_path),),
        readable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        verification_policy={"mode": "explicit", "steps": ()},
        metadata={"task_type": "capability"},
    )
    corpus_dir = _write_runtime_corpus(tmp_path, request)

    async def _fake_executor(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Implemented the tool.",
            changed_files=("services/foo/tool.py",),
        )

    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_fake_executor,
    )

    summary = asyncio.run(runtime.run_eval_corpus(corpus_dir=corpus_dir))

    assert summary.corpus_name == "corpus"
    assert summary.total_cases == 1
    assert summary.passed_cases == 1
    assert summary.eval_run_id is not None
    assert summary.artifact_id is not None
    assert summary.summary_path is not None
    assert Path(summary.summary_path).exists()
    persisted = runtime.get_eval_run(summary.eval_run_id)
    assert persisted.eval_run_id == summary.eval_run_id
    assert runtime.list_eval_runs()[0].eval_run_id == summary.eval_run_id


def test_runtime_can_export_completed_run_to_candidate_eval_case(tmp_path: Path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        )
    )
    request = RunRequest(
        run_id="forge-export-1",
        client_name="sophia_prima",
        task="Implement a scheduler hook.",
        workspace_root=str(tmp_path),
        writable_roots=(str(tmp_path),),
        readable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        verification_policy={"mode": "none", "steps": ()},
        metadata={"task_type": "capability"},
    )
    runtime.run_store.create_run(request)
    runtime.run_store.replace_verification_results(
        "forge-export-1",
        (
            VerificationResult(
                name="smoke_check",
                status="passed",
                command="printf ok",
                required=True,
                details="ok",
            ),
        ),
    )
    runtime.run_store.finish_run(
        RunResult(
            run_id="forge-export-1",
            status="completed",
            summary="Implemented the scheduler hook.",
            changed_files=("services/foo/scheduler.py",),
        )
    )

    export_dir = tmp_path / "exported_corpus"
    exported = runtime.export_eval_case_from_run(
        "forge-export-1",
        output_dir=export_dir,
        tags=("scheduler",),
    )

    assert exported.run_id == "forge-export-1"
    assert exported.case.expectation.status == "completed"
    assert exported.case.status == "candidate"
    assert exported.case.source_run_id == "forge-export-1"
    assert exported.case.expectation.required_verification_passed is True
    assert exported.case.expectation.changed_files_subset == ("services/foo/scheduler.py",)
    assert "scheduler" in exported.case.tags
    assert exported.output_path is not None
    assert Path(exported.output_path).exists()


def test_load_eval_cases_defaults_to_approved_only(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "approved.json").write_text(
        json.dumps(
            {
                "case_id": "approved-case",
                "name": "Approved case",
                "status": "approved",
                "request": _case_request(tmp_path, run_id="approved-run").model_dump(mode="json"),
                "expectation": {"status": "completed"},
            }
        ),
        encoding="utf-8",
    )
    (corpus_dir / "candidate.json").write_text(
        json.dumps(
            {
                "case_id": "candidate-case",
                "name": "Candidate case",
                "status": "candidate",
                "request": _case_request(tmp_path, run_id="candidate-run").model_dump(mode="json"),
                "expectation": {"status": "completed"},
            }
        ),
        encoding="utf-8",
    )

    approved = load_eval_cases(corpus_dir)
    all_cases = load_eval_cases(corpus_dir, statuses=None)

    assert [case.case_id for case in approved] == ["approved-case"]
    assert {case.case_id for case in all_cases} == {"approved-case", "candidate-case"}


def test_runtime_can_review_candidate_eval_case(tmp_path: Path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        )
    )
    request = _case_request(tmp_path, run_id="forge-export-review")
    runtime.run_store.create_run(request)
    runtime.run_store.finish_run(
        RunResult(
            run_id="forge-export-review",
            status="completed",
            summary="Implemented the scheduler hook.",
            changed_files=("services/foo/scheduler.py",),
        )
    )
    export_dir = tmp_path / "exported_corpus"
    exported = runtime.export_eval_case_from_run("forge-export-review", output_dir=export_dir)

    with_candidate = runtime.list_curated_eval_cases(corpus_dir=export_dir, statuses=("candidate",))
    assert with_candidate[0].case_id == exported.case.case_id

    reviewed = runtime.review_eval_case(
        exported.case.case_id,
        corpus_dir=export_dir,
        status="approved",
        curation_notes="Looks representative.",
    )

    assert reviewed.status == "approved"
    assert reviewed.curation_notes == "Looks representative."
    assert reviewed.curation_history[-1].previous_status == "candidate"
    assert reviewed.curation_history[-1].new_status == "approved"
    approved = runtime.list_curated_eval_cases(corpus_dir=export_dir)
    assert approved[0].case_id == exported.case.case_id


def _write_eval_corpus(
    tmp_path: Path,
    success_request: RunRequest,
    failure_request: RunRequest,
) -> Path:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "success.json").write_text(
        json.dumps(
            {
                "case_id": "eval-success",
                "name": "Capability succeeds",
                "request": success_request.model_dump(mode="json"),
                "expectation": {
                    "status": "completed",
                    "required_verification_passed": True,
                    "changed_files_subset": ["services/foo/tool.py"],
                },
            }
        ),
        encoding="utf-8",
    )
    (corpus_dir / "failure.json").write_text(
        json.dumps(
            {
                "case_id": "eval-failure",
                "name": "Backend launch fails",
                "request": failure_request.model_dump(mode="json"),
                "expectation": {
                    "status": "failed",
                    "failure_class": "backend_launch_failed",
                },
            }
        ),
        encoding="utf-8",
    )
    return corpus_dir


def _write_runtime_corpus(tmp_path: Path, request: RunRequest) -> Path:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "runtime.json").write_text(
        json.dumps(
            {
                "case_id": "runtime-success",
                "name": "Runtime replay works",
                "request": request.model_dump(mode="json"),
                "expectation": {
                    "status": "completed",
                    "changed_files_subset": ["services/foo/tool.py"],
                },
            }
        ),
        encoding="utf-8",
    )
    return corpus_dir


def _case_request(tmp_path: Path, *, run_id: str) -> RunRequest:
    return RunRequest(
        run_id=run_id,
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(tmp_path),
        writable_roots=(str(tmp_path),),
        readable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        verification_policy={"mode": "none", "steps": ()},
        metadata={"task_type": "capability"},
    )
