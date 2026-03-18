"""Helpers for reviewing and curating eval corpus cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sophia_forge.evals.models import EvalCase, EvalCaseReviewRecord, EvalCaseStatus


def list_eval_cases(
    *,
    corpus_dir: Path,
    statuses: tuple[EvalCaseStatus, ...] | None = None,
) -> tuple[EvalCase, ...]:
    """List eval cases from a corpus directory, optionally filtered by status."""

    files = sorted(corpus_dir.resolve(strict=False).rglob("*.json"))
    cases = tuple(
        EvalCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in files
    )
    if statuses is None:
        return cases
    return tuple(case for case in cases if case.status in statuses)


def review_eval_case(
    *,
    corpus_dir: Path,
    case_id: str,
    status: EvalCaseStatus,
    curation_notes: str = "",
) -> EvalCase:
    """Update one eval case JSON file with a new curation status."""

    path = find_eval_case_path(corpus_dir=corpus_dir, case_id=case_id)
    case = EvalCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
    updated = case.model_copy(
        update={
            "status": status,
            "curation_notes": curation_notes,
            "curation_history": case.curation_history
            + (
                EvalCaseReviewRecord(
                    reviewed_at=_utc_now(),
                    previous_status=case.status,
                    new_status=status,
                    curation_notes=curation_notes,
                ),
            ),
        }
    )
    path.write_text(
        json.dumps(updated.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return updated


def find_eval_case_path(*, corpus_dir: Path, case_id: str) -> Path:
    """Locate the JSON file for one eval case."""

    for path in sorted(corpus_dir.resolve(strict=False).rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("case_id") == case_id:
            return path
    raise KeyError(case_id)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
