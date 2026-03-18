"""Helpers for exporting completed forge runs into candidate eval cases."""

from __future__ import annotations

import json
from pathlib import Path

from sophia_forge.core.outcomes import classify_failure, required_verification_passed
from sophia_forge.evals.models import EvalCase, EvalCaseExpectation, EvalCaseExport
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge_protocol.verification_models import VerificationResult


def build_eval_case_from_run(
    *,
    run_id: str,
    request: RunRequest,
    result: RunResult,
    verification_results: tuple[VerificationResult, ...],
    case_id: str | None = None,
    name: str | None = None,
    description: str = "",
    tags: tuple[str, ...] = (),
) -> EvalCase:
    """Create a candidate eval case from one persisted forge run."""

    normalized_case_id = case_id or _sanitize_identifier(run_id)
    task_type = str(request.metadata.get("task_type") or "").strip().lower()
    merged_tags = tuple(
        item
        for item in dict.fromkeys(
            [*tags, *([task_type] if task_type else []), "exported_from_run"]
        )
        if item
    )
    failure_class = None
    if result.status != "completed":
        failure_class = classify_failure(status=result.status, error=result.error)
    expectation = EvalCaseExpectation(
        status=result.status,
        required_verification_passed=required_verification_passed(verification_results),
        changed_files_subset=result.changed_files if result.status == "completed" else (),
        failure_class=failure_class,
    )
    return EvalCase(
        case_id=normalized_case_id,
        name=name or _default_case_name(request=request, run_id=run_id),
        description=description or f"Exported from forge run {run_id}.",
        status="candidate",
        source_run_id=run_id,
        tags=merged_tags,
        request=request,
        expectation=expectation,
    )


def export_eval_case_to_dir(
    *,
    case: EvalCase,
    output_dir: Path,
) -> Path:
    """Write one candidate eval case JSON file to disk."""

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{case.case_id}.json"
    output_path.write_text(
        json.dumps(case.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


def export_eval_case_record(
    *,
    run_id: str,
    request: RunRequest,
    result: RunResult,
    verification_results: tuple[VerificationResult, ...],
    output_dir: Path | None = None,
    case_id: str | None = None,
    name: str | None = None,
    description: str = "",
    tags: tuple[str, ...] = (),
) -> EvalCaseExport:
    """Build and optionally write a candidate eval case export."""

    case = build_eval_case_from_run(
        run_id=run_id,
        request=request,
        result=result,
        verification_results=verification_results,
        case_id=case_id,
        name=name,
        description=description,
        tags=tags,
    )
    output_path = None
    if output_dir is not None:
        output_path = str(export_eval_case_to_dir(case=case, output_dir=output_dir))
    return EvalCaseExport(run_id=run_id, case=case, output_path=output_path)


def _default_case_name(*, request: RunRequest, run_id: str) -> str:
    task = request.task.strip()
    if not task:
        return f"Exported eval case from {run_id}"
    first_line = task.splitlines()[0].strip()
    return first_line[:80]


def _sanitize_identifier(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)
    return normalized.strip("._") or "eval_case"
