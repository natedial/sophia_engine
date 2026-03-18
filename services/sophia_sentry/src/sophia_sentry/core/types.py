"""Core type definitions for background watch monitoring."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WatchKind(str, Enum):
    """Supported watch kinds."""

    NUMERIC_THRESHOLD = "numeric_threshold"
    MODEL_REVISION = "model_revision"
    WEB_TOPIC = "web_topic"


class WatchState(str, Enum):
    """Lifecycle state for a watch."""

    ENABLED = "enabled"
    DISABLED = "disabled"


class DeliveryChannel(str, Enum):
    """Intended delivery targets for an event."""

    INBOX = "inbox"
    TELEGRAM = "telegram"
    DASHBOARD = "dashboard"
    WEBHOOK = "webhook"


class EventSeverity(str, Enum):
    """Severity assigned to a material event."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class EvaluationSource(str, Enum):
    """Origin of a watch evaluation."""

    MANUAL = "manual"
    CRON = "cron"
    DATA_TRIGGER = "data_trigger"
    MODEL_TRIGGER = "model_trigger"


class WatchDefinition(BaseModel):
    """Registered watch definition."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: WatchKind
    owner: str
    description: str | None = None
    state: WatchState = WatchState.ENABLED
    schedule_cron: str | None = None
    tags: list[str] = Field(default_factory=list)
    spec: dict[str, Any] = Field(default_factory=dict)
    delivery_channels: list[DeliveryChannel] = Field(
        default_factory=lambda: [DeliveryChannel.INBOX]
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WatchRuntimeState(BaseModel):
    """Persisted state used during repeated evaluations."""

    model_config = ConfigDict(extra="forbid")

    watch_id: str
    last_value: float | None = None
    last_evaluated_at: datetime | None = None
    last_triggered_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WatchEvaluationRequest(BaseModel):
    """Input payload for evaluating one or more watches."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    source: EvaluationSource = EvaluationSource.MANUAL
    observations: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    watch_ids: list[str] = Field(default_factory=list)


class WatchEvent(BaseModel):
    """Durable event emitted by a triggered watch."""

    model_config = ConfigDict(extra="forbid")

    id: str
    watch_id: str
    watch_name: str
    kind: WatchKind
    severity: EventSeverity
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    delivery_channels: list[DeliveryChannel] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WatchEvaluationResult(BaseModel):
    """Outcome of one watch evaluation."""

    model_config = ConfigDict(extra="forbid")

    watch_id: str
    triggered: bool
    reason: str
    severity: EventSeverity | None = None
    event_id: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class NumericThresholdSpec(BaseModel):
    """Spec for threshold-based numeric watches."""

    model_config = ConfigDict(extra="forbid")

    signal_key: str
    threshold: float | None = None
    delta_threshold: float | None = None
    direction: str = "above"


class ModelRevisionSpec(BaseModel):
    """Spec for watches based on model output revisions."""

    model_config = ConfigDict(extra="forbid")

    production_slot: str
    metric_key: str
    minimum_absolute_delta: float


class PublicationUpdatePayload(BaseModel):
    """Incoming publication notification from Oikonomia."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    production_slot: str
    as_of: datetime
    published_at: datetime
    current_summary: dict[str, Any] = Field(default_factory=dict)
    prior_summary: dict[str, Any] = Field(default_factory=dict)
    insights: list[str] = Field(default_factory=list)
