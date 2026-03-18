"""Runtime-managed process environments for forge runs."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge_protocol.run_models import RunRequest


@dataclass(frozen=True)
class PreparedEnvironment:
    """Resolved process environment for one forge run."""

    run_id: str
    strategy: str
    cleanup_policy: str
    variables: dict[str, str]
    env_root: Path | None = None
    injected_secret_env_vars: tuple[str, ...] = ()


class EnvironmentManager:
    """Prepare explicit process environments and secret passthrough for forge."""

    def __init__(self, settings: ForgeSettings) -> None:
        self.settings = settings

    def prepare(self, request: RunRequest) -> PreparedEnvironment:
        strategy = request.execution_policy.environment_strategy
        if strategy == "inherit":
            strategy = self.settings.environment_strategy_default
        cleanup_policy = request.execution_policy.environment_cleanup_policy
        if cleanup_policy == "inherit":
            cleanup_policy = self.settings.environment_cleanup_policy_default

        variables = _base_environment()
        allowed_secret_names = [
            name
            for name in request.execution_policy.secret_env_vars
            if name in self.settings.secret_env_allowlist and os.environ.get(name)
        ]
        for name in allowed_secret_names:
            variables[name] = os.environ[name]

        if strategy != "ephemeral":
            return PreparedEnvironment(
                run_id=request.run_id or "forge_run",
                strategy="shared",
                cleanup_policy=cleanup_policy,
                variables=variables,
                injected_secret_env_vars=tuple(sorted(allowed_secret_names)),
            )

        env_root = self.settings.output_dir / "environments" / _sanitize_run_id(request.run_id or "forge_run")
        home_dir = env_root / "home"
        cache_dir = env_root / "cache"
        tmp_dir = env_root / "tmp"
        for path in (home_dir, cache_dir, tmp_dir):
            path.mkdir(parents=True, exist_ok=True)
        variables.update(
            {
                "HOME": str(home_dir),
                "TMPDIR": str(tmp_dir),
                "XDG_CACHE_HOME": str(cache_dir),
            }
        )
        return PreparedEnvironment(
            run_id=request.run_id or "forge_run",
            strategy="ephemeral",
            cleanup_policy=cleanup_policy,
            variables=variables,
            env_root=env_root,
            injected_secret_env_vars=tuple(sorted(allowed_secret_names)),
        )

    def cleanup(self, prepared: PreparedEnvironment, *, final_status: str) -> None:
        if prepared.strategy != "ephemeral" or prepared.env_root is None:
            return
        if prepared.cleanup_policy == "keep":
            return
        if prepared.cleanup_policy == "cleanup_on_success" and final_status != "completed":
            return
        shutil.rmtree(prepared.env_root, ignore_errors=True)


def _base_environment() -> dict[str, str]:
    variables: dict[str, str] = {}
    for key in (
        "PATH",
        "LANG",
        "LC_ALL",
        "TERM",
        "SHELL",
        "USER",
        "LOGNAME",
        "HOME",
        "TMPDIR",
        "PYENV_ROOT",
        "VIRTUAL_ENV",
    ):
        value = os.environ.get(key)
        if value:
            variables[key] = value
    return variables


def _sanitize_run_id(run_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in run_id)
