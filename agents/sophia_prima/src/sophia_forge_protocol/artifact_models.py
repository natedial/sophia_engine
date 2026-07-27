"""Artifact contracts for coding runtime runs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


ArtifactType = Literal[
    "task_spec",
    "run_request",
    "prompt_package",
    "backend_output",
    "changed_files",
    "checkpoint_summary",
    "verification_log",
    "summary",
    "run_result",
    "capability_adoption",
    "promotion_status",
    "pr_request",
    "patch",
]


class RunArtifact(BaseModel):
    """Persisted artifact descriptor for a coding run."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    run_id: str
    artifact_type: ArtifactType
    content_type: str
    path: str | None = None
    payload: dict[str, Any] | None = None
    created_at: str
