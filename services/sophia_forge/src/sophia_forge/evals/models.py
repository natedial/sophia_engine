"""Models for forge eval corpora and replay results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sophia_forge_protocol.run_models import RunRequest, RunStatus

EvalCaseStatus = Literal["candidate", "approved", "rejected"]


class EvalCaseReviewRecord(BaseModel):
    """One curation decision applied to an eval case."""

    model_config = ConfigDict(extra="forbid")

    reviewed_at: str
    previous_status: EvalCaseStatus
    new_status: EvalCaseStatus
    curation_notes: str = ""


class EvalCaseExpectation(BaseModel):
    """Expected high-level outcome for one replayed coding run."""

    model_config = ConfigDict(extra="forbid")

    status: RunStatus
    required_verification_passed: bool | None = None
    changed_files_subset: tuple[str, ...] = Field(default_factory=tuple)
    failure_class: str | None = None


class EvalCase(BaseModel):
    """One persisted coding task fixture used for replay evals."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    name: str
    description: str = ""
    status: EvalCaseStatus = "approved"
    curation_notes: str = ""
    source_run_id: str | None = None
    curation_history: tuple[EvalCaseReviewRecord, ...] = Field(default_factory=tuple)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    request: RunRequest
    expectation: EvalCaseExpectation


class EvalCaseResult(BaseModel):
    """Actual outcome of replaying one eval case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    name: str
    passed: bool
    actual_status: RunStatus
    expected_status: RunStatus
    required_verification_passed: bool | None = None
    actual_failure_class: str | None = None
    mismatches: tuple[str, ...] = Field(default_factory=tuple)
    changed_files: tuple[str, ...] = Field(default_factory=tuple)
    verification: tuple[str, ...] = Field(default_factory=tuple)
    summary: str = ""


class EvalRunSummary(BaseModel):
    """Aggregate replay result for an eval corpus."""

    model_config = ConfigDict(extra="forbid")

    eval_run_id: str | None = None
    corpus_name: str
    backend_override: Literal["codex", "claude_code"] | None = None
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    artifact_id: str | None = None
    summary_path: str | None = None
    created_at: str | None = None
    results: tuple[EvalCaseResult, ...] = Field(default_factory=tuple)


class EvalReplayRequest(BaseModel):
    """Request to replay one eval corpus through forge."""

    model_config = ConfigDict(extra="forbid")

    corpus_dir: str | None = None
    backend_override: Literal["codex", "claude_code"] | None = None


class EvalCaseExport(BaseModel):
    """Candidate eval case exported from one persisted forge run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    case: EvalCase
    output_path: str | None = None


class EvalCaseExportRequest(BaseModel):
    """Request to export a completed forge run into a candidate eval case."""

    model_config = ConfigDict(extra="forbid")

    output_dir: str | None = None
    case_id: str | None = None
    name: str | None = None
    description: str = ""
    tags: tuple[str, ...] = Field(default_factory=tuple)


class EvalCaseReviewRequest(BaseModel):
    """Request to update the curation state of one eval case."""

    model_config = ConfigDict(extra="forbid")

    corpus_dir: str
    status: EvalCaseStatus
    curation_notes: str = ""
