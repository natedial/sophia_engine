"""Run request/result contracts for delegated coding execution."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sophia_forge_protocol.verification_models import VerificationPolicy


RunStatus = Literal[
    "queued",
    "running",
    "completed",
    "blocked",
    "failed",
    "timed_out",
    "cancelled",
    "disabled",
    "unavailable",
    "permission_denied",
    "invalid_output",
]
StructuredRunStatus = Literal["completed", "blocked", "failed"]
ToolCapability = Literal[
    "shell",
    "read",
    "write",
    "edit",
    "grep",
    "glob",
    "test",
    "git_read",
    "git_write",
]
WorkspaceStrategy = Literal["inherit", "shared", "git_worktree"]
WorkspaceCleanupPolicy = Literal[
    "inherit",
    "keep",
    "cleanup_on_success",
    "cleanup_always",
]
EnvironmentStrategy = Literal["inherit", "shared", "ephemeral"]
EnvironmentCleanupPolicy = Literal[
    "inherit",
    "keep",
    "cleanup_on_success",
    "cleanup_always",
]


class CapabilityAdded(BaseModel):
    """A newly added runtime capability produced by a coding run."""

    model_config = ConfigDict(extra="forbid")

    capability_type: Literal["tool"] = "tool"
    tool_name: str
    service_name: str
    registration_path: str
    description: str = ""
    when_to_use: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    usage_example: dict[str, Any] = Field(default_factory=dict)

    @field_validator("usage_example", mode="before")
    @classmethod
    def _normalize_usage_example(cls, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError("usage_example string must decode to a JSON object")
            return parsed
        if not isinstance(value, dict):
            raise ValueError("usage_example must be a JSON object")
        return value

    @field_validator("input_schema", mode="before")
    @classmethod
    def _normalize_input_schema(cls, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise ValueError("input_schema must be a JSON object")
        return value


class CapabilityAdoption(BaseModel):
    """Adoption status for one claimed capability after registry refresh."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    service_name: str
    adopted: bool
    handoff_ready: bool = False
    usage_example_valid: bool = False
    schema_matches: bool | None = None
    resolved_input_schema: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class CapabilityAdoptionReport(BaseModel):
    """Verification report for claimed capabilities after refresh."""

    model_config = ConfigDict(extra="forbid")

    refreshed: bool
    visible_tool_names: tuple[str, ...] = Field(default_factory=tuple)
    capabilities: tuple[CapabilityAdoption, ...] = Field(default_factory=tuple)
    error: str | None = None


class CapabilityHandoff(BaseModel):
    """Durable adopted tool handoff stored by forge."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    service_name: str
    registration_path: str
    description: str = ""
    when_to_use: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    usage_example: dict[str, Any] = Field(default_factory=dict)
    source_run_id: str | None = None
    updated_at: str | None = None


class CapabilityHandoffUpdate(BaseModel):
    """Batch update payload for durable forge capability handoffs."""

    model_config = ConfigDict(extra="forbid")

    entries: tuple[CapabilityHandoff, ...] = Field(default_factory=tuple)


class ExecutionPolicy(BaseModel):
    """Explicit execution/tool-access policy for one coding run."""

    model_config = ConfigDict(extra="forbid")

    readable_roots: tuple[str, ...] = Field(default_factory=tuple)
    writable_roots: tuple[str, ...] = Field(default_factory=tuple)
    allowed_capabilities: tuple[ToolCapability, ...] = Field(default_factory=tuple)
    allowed_command_prefixes: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)
    backend_allowed_tools: tuple[str, ...] = Field(default_factory=tuple)
    network_access: Literal["inherit", "disabled", "enabled"] = "inherit"
    workspace_strategy: WorkspaceStrategy = "inherit"
    workspace_cleanup_policy: WorkspaceCleanupPolicy = "inherit"
    environment_strategy: EnvironmentStrategy = "inherit"
    environment_cleanup_policy: EnvironmentCleanupPolicy = "inherit"
    secret_env_vars: tuple[str, ...] = Field(default_factory=tuple)


class RetryPolicy(BaseModel):
    """Runtime-owned retry behavior for one coding run."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["disabled", "transient_only"] = "disabled"
    max_attempts: int = 1
    initial_backoff_sec: float = 2.0
    max_backoff_sec: float = 30.0


class RunSession(BaseModel):
    """Durable long-running session that can span multiple forge runs."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    client_name: str
    task: str
    status: Literal["active", "completed", "blocked", "failed", "cancelled"]
    latest_run_id: str | None = None
    latest_checkpoint_id: str | None = None
    run_ids: tuple[str, ...] = Field(default_factory=tuple)
    created_at: str
    updated_at: str
    completed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunSessionCreateRequest(BaseModel):
    """Request to create a durable forge run session."""

    model_config = ConfigDict(extra="forbid")

    client_name: str
    task: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ControlMessage(BaseModel):
    """Durable session control message applied by forge at a safe boundary."""

    model_config = ConfigDict(extra="forbid")

    control_id: str
    session_id: str
    run_id: str | None = None
    control_type: Literal["steer", "follow_up"]
    status: Literal["queued", "applied", "rejected", "cancelled"] = "queued"
    message: str
    created_at: str
    applied_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionControlRequest(BaseModel):
    """Request to queue a control message for a forge session."""

    model_config = ConfigDict(extra="forbid")

    control_type: Literal["steer", "follow_up"]
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCheckpoint(BaseModel):
    """Durable checkpoint created from a completed session run."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str
    session_id: str
    run_id: str
    summary_artifact_id: str
    summary: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionResumeRequest(BaseModel):
    """Request to resume a session from its latest or a chosen checkpoint."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    """Normalized request submitted to a coding runtime."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    client_name: str
    task: str
    workspace_root: str
    writable_roots: tuple[str, ...] = Field(default_factory=tuple)
    readable_roots: tuple[str, ...] = Field(default_factory=tuple)
    session_id: str | None = None
    long_running_mode: bool = False
    backend: Literal["codex", "claude_code"]
    timeout_sec: float
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    verification_policy: VerificationPolicy = Field(default_factory=VerificationPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_execution_policy_roots(self) -> "RunRequest":
        if self.readable_roots and not self.execution_policy.readable_roots:
            self.execution_policy = self.execution_policy.model_copy(
                update={"readable_roots": self.readable_roots}
            )
        elif self.execution_policy.readable_roots and not self.readable_roots:
            self.readable_roots = self.execution_policy.readable_roots

        if self.writable_roots and not self.execution_policy.writable_roots:
            self.execution_policy = self.execution_policy.model_copy(
                update={"writable_roots": self.writable_roots}
            )
        elif self.execution_policy.writable_roots and not self.writable_roots:
            self.writable_roots = self.execution_policy.writable_roots
        return self


class StructuredRunOutput(BaseModel):
    """Validated JSON payload returned by a coding backend."""

    model_config = ConfigDict(extra="forbid")

    status: StructuredRunStatus
    summary: str
    changed_files: tuple[str, ...]
    verification: tuple[str, ...]
    follow_ups: tuple[str, ...]
    capabilities_added: tuple[CapabilityAdded, ...] = Field(default_factory=tuple)


class RunResult(BaseModel):
    """Normalized outcome returned to the supervisor/runtime caller."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    success: bool | None = None
    status: RunStatus
    summary: str = ""
    changed_files: tuple[str, ...] = Field(default_factory=tuple)
    verification: tuple[str, ...] = Field(default_factory=tuple)
    follow_ups: tuple[str, ...] = Field(default_factory=tuple)
    capabilities_added: tuple[CapabilityAdded, ...] = Field(default_factory=tuple)
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    raw_message: str = ""
    error: str | None = None

    @model_validator(mode="after")
    def _default_success(self) -> "RunResult":
        if self.success is None:
            self.success = self.status == "completed"
        return self

    @classmethod
    def from_structured_output(
        cls,
        output: StructuredRunOutput,
        *,
        raw_message: str = "",
        error: str | None = None,
    ) -> "RunResult":
        return cls(
            run_id=None,
            success=output.status == "completed",
            status=output.status,
            summary=output.summary,
            changed_files=output.changed_files,
            verification=output.verification,
            follow_ups=output.follow_ups,
            capabilities_added=output.capabilities_added,
            raw_message=raw_message,
            error=error,
        )


class FailureClassCount(BaseModel):
    """Aggregate count for one normalized forge failure class."""

    model_config = ConfigDict(extra="forbid")

    failure_class: str
    count: int


class TaskTypeMetrics(BaseModel):
    """High-level run counts grouped by task type."""

    model_config = ConfigDict(extra="forbid")

    task_type: str
    total_runs: int
    completed_runs: int


class RunMetricsSummary(BaseModel):
    """Operational summary for forge runs over the current store."""

    model_config = ConfigDict(extra="forbid")

    total_runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    success_rate: float = 0.0
    retry_rate: float = 0.0
    runs_with_verification: int = 0
    verification_pass_rate: float | None = None
    common_failure_classes: tuple[FailureClassCount, ...] = Field(default_factory=tuple)
    task_types: tuple[TaskTypeMetrics, ...] = Field(default_factory=tuple)


class RetentionBucket(BaseModel):
    """Retention state for one forge runtime output category."""

    model_config = ConfigDict(extra="forbid")

    category: str
    eligible_count: int = 0
    deleted_count: int = 0
    eligible_paths: tuple[str, ...] = Field(default_factory=tuple)
    deleted_paths: tuple[str, ...] = Field(default_factory=tuple)


class RetentionSummary(BaseModel):
    """Retention summary or cleanup result for forge-managed outputs."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    workspaces: RetentionBucket
    environments: RetentionBucket
    run_artifacts: RetentionBucket
    eval_artifacts: RetentionBucket


def run_output_schema() -> dict[str, object]:
    """JSON schema enforced for backend final output."""

    return StructuredRunOutput.model_json_schema()
