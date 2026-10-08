"""Versioned research-case contracts.

These models are the ingestion boundary. Schema validity is not empirical
support: unverified provenance and unidentified methods stay visible.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


PROTOCOL_VERSION = "1"


class ProvenanceStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    INVALID = "invalid"


class EvidenceKind(str, Enum):
    SOURCE_CLAIM = "source_claim"
    EMPIRICAL_RESULT = "empirical_result"
    AGENT_INTERPRETATION = "agent_interpretation"


class Stance(str, Enum):
    SUPPORTING = "supporting"
    CHALLENGING = "challenging"
    NON_DIAGNOSTIC = "non_diagnostic"


class HypothesisRecordStatus(str, Enum):
    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    LEGACY_UNASSESSED = "legacy_unassessed"
    USEFUL_BOUNDED = "useful_bounded"
    UNMET_REQUIREMENTS = "unmet_requirements"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class AllowedUse(str, Enum):
    EXPLAIN = "explain"
    PREDICT = "predict"
    INTERVENE = "intervene"
    COUNTERFACTUAL = "counterfactual"


class QuestionType(str, Enum):
    PREDICTIVE = "predictive"
    ASSOCIATION = "association"
    IDENTIFIED_CAUSAL = "identified_causal"
    INTERVENTION = "intervention"
    COUNTERFACTUAL = "counterfactual"


class ResultStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class Sign(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceClaimRef(ResearchModel):
    """Immutable, attributed source evidence. Not an agent interpretation."""

    namespace: str
    occurrence_id: str
    document_revision: str | None = None
    content_hash: str | None = None
    snapshot_hash: str | None = None
    author: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    captured_at: datetime | None = None
    locations: list[str] = Field(default_factory=list)
    excerpt: str | None = None
    qualifications: list[str] = Field(default_factory=list)
    independence_group: str | None = None
    citation: str | None = None
    parser_versions: dict[str, str] = Field(default_factory=dict)

    def provenance_status(self) -> ProvenanceStatus:
        if not self.occurrence_id.strip() or not self.namespace.strip():
            return ProvenanceStatus.INVALID
        has_identity = bool(self.snapshot_hash or self.content_hash or self.document_revision)
        has_locus = bool(self.locations or (self.excerpt and self.excerpt.strip()))
        if has_identity and has_locus:
            return ProvenanceStatus.VERIFIED
        if self.citation and not has_identity and not has_locus:
            return ProvenanceStatus.UNVERIFIED
        if has_identity or has_locus:
            return ProvenanceStatus.UNVERIFIED
        return ProvenanceStatus.UNVERIFIED


class VariableSpec(ResearchModel):
    variable_id: str
    definition: str
    units: str | None = None
    geography: str | None = None
    entity: str | None = None
    frequency: str | None = None
    transformations: list[str] = Field(default_factory=list)
    source_series: list[str] = Field(default_factory=list)


class MechanismHypothesis(ResearchModel):
    hypothesis_id: str
    revision: int
    case_id: str
    cause_variable_id: str
    effect_variable_id: str
    channel: str
    sign: Sign = Sign.UNKNOWN
    lag: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    alternatives: list[str] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)
    expected_observations: list[str] = Field(default_factory=list)
    falsifiers: list[str] = Field(default_factory=list)
    submitting_actor: str
    rationale: str = ""


class ObservationPoint(ResearchModel):
    date: str
    value: float


class InputSnapshot(ResearchModel):
    vintage: str
    as_of: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    transformations: list[str] = Field(default_factory=list)
    source_observations: list[ObservationPoint] = Field(default_factory=list)
    target_observations: list[ObservationPoint] = Field(default_factory=list)
    source_series: str | None = None
    target_series: str | None = None


class EmpiricalResult(ResearchModel):
    run_id: str
    case_id: str
    hypothesis_id: str | None = None
    fingerprint: str
    method: str
    method_version: str
    question_type: QuestionType
    estimand: str
    status: ResultStatus
    input_snapshot: InputSnapshot
    estimate: float | None = None
    estimate_units: str | None = None
    interval_low: float | None = None
    interval_high: float | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    scope_limitations: list[str] = Field(default_factory=list)
    identification_resolved: bool = False


class EvidenceAssessment(ResearchModel):
    contribution_id: str
    case_id: str
    hypothesis_id: str | None = None
    evidence_kind: EvidenceKind
    stance: Stance = Stance.NON_DIAGNOSTIC
    independence_group: str
    provenance_status: ProvenanceStatus
    justification: str = ""
    method: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    provenance: SourceClaimRef | None = None
    result_id: str | None = None
    assessed_at: datetime
    event_time: datetime | None = None
    known_as_of: datetime | None = None


class AgentProposal(ResearchModel):
    proposal_id: str
    case_id: str
    hypothesis_id: str | None = None
    case_revision: int
    submitting_actor: str
    kind: str
    cited_evidence_ids: list[str] = Field(default_factory=list)
    cited_result_ids: list[str] = Field(default_factory=list)
    requested_uses: list[AllowedUse] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    rationale: str = ""


class HypothesisAssessment(ResearchModel):
    hypothesis_id: str
    case_id: str
    status: HypothesisRecordStatus
    contributing_evidence_ids: list[str] = Field(default_factory=list)
    contributing_result_ids: list[str] = Field(default_factory=list)
    contributing_proposal_ids: list[str] = Field(default_factory=list)
    unresolved_alternatives: list[str] = Field(default_factory=list)
    applicability: str | None = None
    allowed_uses: list[AllowedUse] = Field(default_factory=list)
    unmet_requirements: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    policy_version: str = PROTOCOL_VERSION
    revision: int = 1


class CaseScope(ResearchModel):
    jurisdiction: str | None = None
    measure: str | None = None
    surprise_baseline: str | None = None
    horizon: str | None = None
    competing_explanations: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ResearchCase(ResearchModel):
    case_id: str
    revision: int
    question: str
    scope: CaseScope = Field(default_factory=CaseScope)
    submitting_actor: str
    created_at: datetime
    updated_at: datetime
    decisions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)


class MethodCapability(ResearchModel):
    name: str
    available: bool
    question_types: list[QuestionType]
    required_inputs: list[str]
    notes: str = ""


class Capabilities(ResearchModel):
    protocol_version: str = PROTOCOL_VERSION
    methods: list[MethodCapability]
    unavailable_optional: list[str] = Field(default_factory=list)
    permitted_question_types: list[QuestionType]
