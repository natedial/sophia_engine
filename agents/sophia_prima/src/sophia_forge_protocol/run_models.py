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


class ExecutionPolicy(BaseModel):
    """Explicit execution/tool-access policy for one coding run."""

    model_config = ConfigDict(extra="forbid")

    readable_roots: tuple[str, ...] = Field(default_factory=tuple)
    writable_roots: tuple[str, ...] = Field(default_factory=tuple)
    allowed_capabilities: tuple[ToolCapability, ...] = Field(default_factory=tuple)
    allowed_command_prefixes: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)
    backend_allowed_tools: tuple[str, ...] = Field(default_factory=tuple)
    network_access: Literal["inherit", "disabled", "enabled"] = "inherit"


class RunRequest(BaseModel):
    """Normalized request submitted to a coding runtime."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    client_name: str
    task: str
    workspace_root: str
    writable_roots: tuple[str, ...] = Field(default_factory=tuple)
    readable_roots: tuple[str, ...] = Field(default_factory=tuple)
    backend: Literal["codex", "claude_code"]
    timeout_sec: float
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
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


def run_output_schema() -> dict[str, object]:
    """JSON schema enforced for backend final output."""

    return StructuredRunOutput.model_json_schema()
