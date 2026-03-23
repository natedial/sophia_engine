"""Configuration for the Sophia Forge runtime service."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ForgeSettings(BaseModel):
    """Runtime service settings."""

    model_config = ConfigDict(extra="forbid")

    bind_host: str = "127.0.0.1"
    bind_port: int = 8040
    store_path: Path = Path(".sophia/forge/forge_runs.db")
    output_dir: Path = Path(".sophia/forge/runs")
    default_backend: Literal["codex", "claude_code"] = "codex"
    max_concurrent_runs: int = 1
    enable_cancellation: bool = True
    codex_command: str = "codex"
    codex_model: str = ""
    codex_sandbox: str = "workspace-write"
    claude_code_command: str = "claude"
    claude_code_model: str = ""
    claude_code_max_turns: int = 8
    claude_code_permission_mode: str = "acceptEdits"
    claude_code_allowed_tools: str = "Bash,Edit,Glob,Grep,LS,MultiEdit,Read,Write"
    max_message_chars: int = 12000
    verification_timeout_sec: float = 120.0
    workspace_strategy_default: Literal["shared", "git_worktree"] = "shared"
    workspace_cleanup_policy_default: Literal[
        "keep", "cleanup_on_success", "cleanup_always"
    ] = "keep"
    environment_strategy_default: Literal["shared", "ephemeral"] = "shared"
    environment_cleanup_policy_default: Literal[
        "keep", "cleanup_on_success", "cleanup_always"
    ] = "keep"
    secret_env_allowlist: tuple[str, ...] = ()
    workspace_retention_days: int = 7
    environment_retention_days: int = 7
    run_artifact_retention_days: int = 30
    eval_artifact_retention_days: int = 30
    git_author_name: str = "Sophia Forge"
    git_author_email: str = "forge@example.local"
    git_remote_name: str = "origin"
    git_host_provider: Literal["disabled", "github", "gitlab"] = "disabled"
    git_host_request_timeout_sec: float = 15.0
    github_api_base_url: str = "https://api.github.com"
    github_token_env_var: str = "GITHUB_TOKEN"
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"
    gitlab_token_env_var: str = "GITLAB_TOKEN"
