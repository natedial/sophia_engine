"""Core type definitions for economic model orchestration."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelFamily(str, Enum):
    """Supported model families."""

    MACRO = "macro"
    MARKET = "market"
    CURVE = "curve"
    VOLATILITY = "volatility"
    CREDIT = "credit"
    STRATEGY = "strategy"


class ModelState(str, Enum):
    """Lifecycle state for a model definition."""

    RESEARCH = "research"
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    CHAMPION = "champion"
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"
    ARCHIVED = "archived"


class DependencyKind(str, Enum):
    """Types of upstream dependencies."""

    SERIES = "series"
    RELEASE = "release"
    MARKET_DATA = "market_data"
    SNAPSHOT = "snapshot"


class TriggerType(str, Enum):
    """Ways a model run can be triggered."""

    SCHEDULED = "scheduled"
    DATA_REFRESH = "data_refresh"
    ECONOMIC_RELEASE = "economic_release"
    MANUAL = "manual"
    HYPOTHESIS = "hypothesis"


class RunStatus(str, Enum):
    """Status of a model run."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PUBLISHED = "published"


class PromotionGate(str, Enum):
    """Required review gates before promotion."""

    CONTRACT_TESTS = "contract_tests"
    EVAL_REPLAY = "eval_replay"
    SHADOW_RUNS = "shadow_runs"
    OPS_CHECKS = "ops_checks"


class GateStatus(str, Enum):
    """Status of a promotion gate."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    WAIVED = "waived"


class PublicationState(str, Enum):
    """Publication state for a projection."""

    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class DataDependency(BaseModel):
    """Describes upstream data dependencies for a model."""

    model_config = ConfigDict(extra="forbid")

    source: str
    provider: str | None = None
    kind: DependencyKind = DependencyKind.SERIES
    series_id: str | None = None
    release_name: str | None = None
    tags: list[str] = Field(default_factory=list)


class CadencePolicy(BaseModel):
    """Defines scheduled rerun expectations."""

    model_config = ConfigDict(extra="forbid")

    cron: str | None = None
    timezone: str = "America/New_York"
    event_driven: bool = True


class ExecutionSpec(BaseModel):
    """Execution details for a model wrapper."""

    model_config = ConfigDict(extra="forbid")

    adapter_id: str
    external_model_ref: str | None = None
    workspace_root: str | None = None
    artifact_path: str | None = None
    default_parameters: dict[str, Any] = Field(default_factory=dict)


class AnalysisSpec(BaseModel):
    """Post-run analysis behavior."""

    model_config = ConfigDict(extra="forbid")

    compare_to_prior: bool = True
    compare_to_actuals: bool = True
    compare_to_peers: bool = False
    materiality_threshold: float = 0.0


class PromotionBundle(BaseModel):
    """Versioned promotion metadata for a model definition."""

    model_config = ConfigDict(extra="forbid")

    adapter_version: str | None = None
    artifact_version: str | None = None
    eval_corpus_id: str | None = None
    rollback_model_id: str | None = None
    notes: list[str] = Field(default_factory=list)


class ModelDefinition(BaseModel):
    """Registered economic or market model."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    family: ModelFamily
    owner: str
    description: str | None = None
    state: ModelState = ModelState.RESEARCH
    production_slot: str | None = None
    dependencies: list[DataDependency] = Field(default_factory=list)
    cadence: CadencePolicy = Field(default_factory=CadencePolicy)
    execution: ExecutionSpec
    analysis: AnalysisSpec = Field(default_factory=AnalysisSpec)
    promotion: PromotionBundle = Field(default_factory=PromotionBundle)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PromotionGateResult(BaseModel):
    """Outcome of one promotion gate."""

    model_config = ConfigDict(extra="forbid")

    gate: PromotionGate
    status: GateStatus
    details: str | None = None


class PromotionReview(BaseModel):
    """Review record for moving a model toward production."""

    model_config = ConfigDict(extra="forbid")

    id: str
    model_id: str
    requested_state: ModelState
    gate_results: list[PromotionGateResult] = Field(default_factory=list)
    reviewer: str = "system"
    notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ModelTrigger(BaseModel):
    """Incoming trigger describing why runs should be planned."""

    model_config = ConfigDict(extra="forbid")

    trigger_type: TriggerType
    as_of: datetime
    source: str | None = None
    series_ids: list[str] = Field(default_factory=list)
    release_name: str | None = None
    model_ids: list[str] = Field(default_factory=list)
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class InputSnapshotRef(BaseModel):
    """Reference to an immutable input snapshot."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    as_of: datetime
    source_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunPlanItem(BaseModel):
    """One planned run generated from a trigger."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    trigger_reason: str
    source_matches: list[str] = Field(default_factory=list)


class RunPlan(BaseModel):
    """Resolution of a trigger into impacted models."""

    model_config = ConfigDict(extra="forbid")

    trigger: ModelTrigger
    impacted_models: list[RunPlanItem] = Field(default_factory=list)


class ModelRun(BaseModel):
    """Run record for a model execution."""

    model_config = ConfigDict(extra="forbid")

    id: str
    model_id: str
    status: RunStatus = RunStatus.QUEUED
    trigger: ModelTrigger
    input_snapshot: InputSnapshotRef
    requested_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    raw_output: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    insights: list[str] = Field(default_factory=list)
    quality_score: float | None = None
    error: str | None = None


class CompleteRunRequest(BaseModel):
    """Marks a run complete with result metadata."""

    model_config = ConfigDict(extra="forbid")

    output_summary: dict[str, Any] = Field(default_factory=dict)
    raw_output: dict[str, Any] = Field(default_factory=dict)
    insights: list[str] = Field(default_factory=list)
    quality_score: float | None = None
    status: RunStatus = RunStatus.SUCCEEDED
    error: str | None = None


class ModelExecutionResult(BaseModel):
    """Normalized output from an adapter execution."""

    model_config = ConfigDict(extra="forbid")

    status: RunStatus
    output_summary: dict[str, Any] = Field(default_factory=dict)
    raw_output: dict[str, Any] = Field(default_factory=dict)
    insights: list[str] = Field(default_factory=list)
    quality_score: float | None = None
    error: str | None = None


class PublishedProjection(BaseModel):
    """Published projection from a successful run."""

    model_config = ConfigDict(extra="forbid")

    id: str
    model_id: str
    run_id: str
    as_of: datetime
    state: PublicationState = PublicationState.PUBLISHED
    summary: dict[str, Any] = Field(default_factory=dict)
    insights: list[str] = Field(default_factory=list)
    quality_score: float | None = None
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PublishProjectionRequest(BaseModel):
    """Promote a successful run to the current published projection."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    summary: dict[str, Any] = Field(default_factory=dict)
    insights: list[str] = Field(default_factory=list)
    quality_score: float | None = None


class ReviewModelRequest(BaseModel):
    """Submit a promotion review for a model."""

    model_config = ConfigDict(extra="forbid")

    requested_state: ModelState
    gate_results: list[PromotionGateResult] = Field(default_factory=list)
    reviewer: str = "system"
    notes: str | None = None


class PromoteModelRequest(BaseModel):
    """Promote a model to a new deployment state."""

    model_config = ConfigDict(extra="forbid")

    target_state: ModelState
    reviewer: str = "system"
    reason: str | None = None


class TriggerExecutionResult(BaseModel):
    """Result of executing all runs planned from a trigger."""

    model_config = ConfigDict(extra="forbid")

    plan: RunPlan
    runs: list[ModelRun] = Field(default_factory=list)
