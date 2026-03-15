"""Core planning and lesson models for Episto."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LessonClass(str, Enum):
    METHODOLOGICAL = "methodological"
    DATA_QUALITY = "data_quality"
    SOURCE_SELECTION = "source_selection"
    FAILURE_MODE = "failure_mode"
    REGIME_BOUNDARY = "regime_boundary"


class AcquisitionMode(str, Enum):
    NONE = "none"
    FETCH_NOW = "fetch_now"
    DEFER = "defer"
    REJECT = "reject"


class DataHandlingMode(str, Enum):
    SOURCE_LOCAL = "source_local"
    ACQUIRE_AND_STORE = "acquire_and_store"
    ACQUIRE_EPHEMERAL = "acquire_ephemeral"
    REJECT_OR_ESCALATE = "reject_or_escalate"


class ReuseExpectation(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class QuestionBrief:
    question: str
    normalized_question: str
    intent: str
    answer_type: str = "analysis"
    horizon: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityCheck:
    concept: str
    indicator_family: str
    available_locally: bool
    freshness_ok: bool = True
    candidate_sources: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndicatorQuerySpec:
    indicator_family: str
    queries: tuple[str, ...]
    preferred_sources: tuple[str, ...] = ()
    structured_data: bool = True
    freshness_sensitive: bool = False
    reuse_expectation: ReuseExpectation = ReuseExpectation.HIGH
    retention_target_on_acquire: str = "staging"


@dataclass(frozen=True)
class AcquisitionDecision:
    concept: str
    indicator_family: str
    mode: AcquisitionMode
    handling_mode: DataHandlingMode
    source: str | None = None
    rationale: str = ""
    retention_target: str = "ephemeral"
    freshness_required: bool = False
    requires_human_review: bool = False
    reason_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidencePlan:
    capability_checks: tuple[CapabilityCheck, ...] = ()
    acquisition_decisions: tuple[AcquisitionDecision, ...] = ()
    required_citations: bool = True
    validation_rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchPlan:
    plan_id: str
    playbook_id: str
    question_brief: QuestionBrief
    subquestions: tuple[str, ...]
    hypotheses: tuple[str, ...] = ()
    indicator_families: tuple[str, ...] = ()
    indicator_queries: tuple[IndicatorQuerySpec, ...] = ()
    transforms: tuple[str, ...] = ()
    comparison_windows: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    evidence_plan: EvidencePlan = field(default_factory=EvidencePlan)


@dataclass(frozen=True)
class LessonRecord:
    lesson_class: LessonClass
    text: str
    tags: tuple[str, ...] = ()
    trigger_pattern: str = ""
    reuse_scope: str = "global"
    review_status: str = "active"
