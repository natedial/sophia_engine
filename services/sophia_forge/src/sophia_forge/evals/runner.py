"""Replay runner for forge eval corpora."""

from __future__ import annotations

import json
import inspect
from collections.abc import Iterable
from pathlib import Path

from sophia_forge.core.outcomes import classify_failure, required_verification_passed
from sophia_forge.core.scheduler import ForgeExecutor
from sophia_forge.core.verification import VerificationRunner, summarize_verification
from sophia_forge.evals.models import EvalCase, EvalCaseResult, EvalCaseStatus, EvalRunSummary
from sophia_forge_protocol.run_models import RunRequest


def default_corpus_dir() -> Path:
    """Return the bundled eval corpus directory."""

    return Path(__file__).resolve().parents[3] / "evals" / "corpus"


def load_eval_cases(
    corpus_dir: Path | None = None,
    *,
    statuses: tuple[EvalCaseStatus, ...] | None = ("approved",),
) -> tuple[EvalCase, ...]:
    """Load eval cases from a corpus directory of JSON fixtures."""

    resolved_dir = (corpus_dir or default_corpus_dir()).resolve(strict=False)
    files = sorted(resolved_dir.rglob("*.json"))
    if not files:
        raise ValueError(f"No eval cases found under {resolved_dir}")
    cases = tuple(
        EvalCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in files
    )
    if statuses is None:
        return cases
    filtered = tuple(case for case in cases if case.status in statuses)
    if not filtered:
        raise ValueError(
            f"No eval cases with statuses {', '.join(statuses)} found under {resolved_dir}"
        )
    return filtered


class EvalReplayRunner:
    """Replay a corpus of run requests against a forge executor."""

    def __init__(
        self,
        *,
        executor: ForgeExecutor,
        verification_runner: VerificationRunner,
    ) -> None:
        self.executor = executor
        self.verification_runner = verification_runner

    async def run_cases(
        self,
        cases: Iterable[EvalCase],
        *,
        corpus_name: str = "ad_hoc",
        backend_override: str | None = None,
    ) -> EvalRunSummary:
        results: list[EvalCaseResult] = []
        for case in cases:
            results.append(
                await self.run_case(
                    case,
                    backend_override=backend_override,
                )
            )
        passed_cases = sum(1 for result in results if result.passed)
        total_cases = len(results)
        return EvalRunSummary(
            corpus_name=corpus_name,
            backend_override=backend_override,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=total_cases - passed_cases,
            pass_rate=(passed_cases / total_cases) if total_cases else 0.0,
            results=tuple(results),
        )

    async def run_case(
        self,
        case: EvalCase,
        *,
        backend_override: str | None = None,
    ) -> EvalCaseResult:
        request = _apply_backend_override(case.request, backend_override=backend_override)
        result = await _call_executor(self.executor, request)
        verification_results = await _call_verification_runner(
            self.verification_runner,
            request,
            result,
        )
        final_result = result.model_copy(
            update={"verification": summarize_verification(verification_results)}
        )

        mismatches: list[str] = []
        if final_result.status != case.expectation.status:
            mismatches.append(
                f"expected status={case.expectation.status}, got status={final_result.status}"
            )

        verification_passed = required_verification_passed(verification_results)
        if case.expectation.required_verification_passed is not None:
            if verification_passed != case.expectation.required_verification_passed:
                mismatches.append(
                    "required verification mismatch: "
                    f"expected {case.expectation.required_verification_passed}, got {verification_passed}"
                )

        if case.expectation.changed_files_subset:
            missing = [
                path
                for path in case.expectation.changed_files_subset
                if path not in final_result.changed_files
            ]
            if missing:
                mismatches.append(
                    "missing changed files: " + ", ".join(sorted(missing))
                )

        actual_failure_class = None
        if final_result.status != "completed":
            actual_failure_class = classify_failure(
                status=final_result.status,
                error=final_result.error,
            )
        if case.expectation.failure_class is not None:
            if actual_failure_class != case.expectation.failure_class:
                mismatches.append(
                    "failure class mismatch: "
                    f"expected {case.expectation.failure_class}, got {actual_failure_class}"
                )

        return EvalCaseResult(
            case_id=case.case_id,
            name=case.name,
            passed=not mismatches,
            actual_status=final_result.status,
            expected_status=case.expectation.status,
            required_verification_passed=verification_passed,
            actual_failure_class=actual_failure_class,
            mismatches=tuple(mismatches),
            changed_files=final_result.changed_files,
            verification=final_result.verification,
            summary=final_result.summary,
        )


def _apply_backend_override(
    request: RunRequest,
    *,
    backend_override: str | None,
) -> RunRequest:
    if backend_override is None:
        return request
    return request.model_copy(update={"backend": backend_override})


async def _call_executor(executor: ForgeExecutor, request: RunRequest):
    try:
        signature = inspect.signature(executor)
    except (TypeError, ValueError):
        signature = None

    if signature is not None and len(signature.parameters) <= 1:
        return await executor(request)
    return await executor(request, None)


async def _call_verification_runner(verification_runner, request: RunRequest, result):
    try:
        signature = inspect.signature(verification_runner.run)
    except (TypeError, ValueError):
        signature = None

    if signature is not None and len(signature.parameters) <= 2:
        return await verification_runner.run(request, result)
    return await verification_runner.run(request, result, env=None)
