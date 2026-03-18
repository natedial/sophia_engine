from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge.core.artifacts import ArtifactManager
from sophia_forge.core.environments import EnvironmentManager
from sophia_forge.core.scheduler import RuntimeScheduler
from sophia_forge.core.verification import VerificationRunner
from sophia_forge.core.workspaces import WorkspaceManager
from sophia_forge.storage.run_store import ForgeRunStore
from sophia_forge_protocol.run_models import ExecutionPolicy, RunRequest, RunResult


def test_workspace_manager_shared_strategy_uses_existing_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    manager = WorkspaceManager(
        ForgeSettings(
            output_dir=tmp_path / "forge_runs",
            workspace_strategy_default="shared",
        )
    )
    request = RunRequest(
        run_id="shared-run",
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(workspace),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        execution_policy=ExecutionPolicy(
            readable_roots=(str(tmp_path),),
            writable_roots=(str(tmp_path),),
        ),
    )

    prepared = manager.prepare(request)

    assert prepared.strategy == "shared"
    assert prepared.workspace_root == workspace.resolve(strict=False)
    assert prepared.workspace_root.exists()


def test_workspace_manager_git_worktree_creates_and_cleans_isolated_workspace(tmp_path: Path) -> None:
    repo_root = _init_git_repo(tmp_path / "repo")
    workspace = repo_root / "services" / "foo"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "tool.py").write_text("def run():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "add tool"],
        check=True,
        capture_output=True,
        text=True,
    )

    manager = WorkspaceManager(
        ForgeSettings(
            output_dir=tmp_path / "forge_runs",
            workspace_strategy_default="git_worktree",
            workspace_cleanup_policy_default="cleanup_always",
        )
    )
    request = RunRequest(
        run_id="isolated-run",
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(workspace),
        readable_roots=(str(repo_root),),
        writable_roots=(str(workspace),),
        backend="codex",
        timeout_sec=30.0,
        execution_policy=ExecutionPolicy(
            readable_roots=(str(repo_root),),
            writable_roots=(str(workspace),),
            workspace_strategy="git_worktree",
            workspace_cleanup_policy="cleanup_always",
        ),
    )

    prepared = manager.prepare(request)

    assert prepared.strategy == "git_worktree"
    assert prepared.repo_root == repo_root.resolve(strict=False)
    assert prepared.worktree_root is not None and prepared.worktree_root.exists()
    assert prepared.workspace_root != workspace.resolve(strict=False)
    assert prepared.workspace_root.exists()
    assert (prepared.workspace_root / "tool.py").exists()

    manager.cleanup(prepared, final_status="completed")

    assert not prepared.worktree_root.exists()


def test_environment_manager_ephemeral_strategy_injects_allowed_secrets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    manager = EnvironmentManager(
        ForgeSettings(
            output_dir=tmp_path / "forge_runs",
            environment_strategy_default="ephemeral",
            environment_cleanup_policy_default="cleanup_always",
            secret_env_allowlist=("OPENAI_API_KEY",),
        )
    )
    request = RunRequest(
        run_id="env-run",
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(tmp_path / "workspace"),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        execution_policy=ExecutionPolicy(
            environment_strategy="ephemeral",
            environment_cleanup_policy="cleanup_always",
            secret_env_vars=("OPENAI_API_KEY", "SHOULD_NOT_PASS"),
        ),
    )

    prepared = manager.prepare(request)

    assert prepared.strategy == "ephemeral"
    assert prepared.env_root is not None and prepared.env_root.exists()
    assert prepared.variables["OPENAI_API_KEY"] == "secret-key"
    assert "SHOULD_NOT_PASS" not in prepared.variables
    assert prepared.variables["HOME"].startswith(str(prepared.env_root))

    manager.cleanup(prepared, final_status="completed")

    assert not prepared.env_root.exists()


def test_scheduler_verifies_inside_isolated_workspace_before_cleanup(tmp_path: Path) -> None:
    repo_root = _init_git_repo(tmp_path / "repo")
    workspace = repo_root / "services" / "foo"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "tool.py").write_text("def run():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "seed tool"],
        check=True,
        capture_output=True,
        text=True,
    )

    settings = ForgeSettings(
        store_path=tmp_path / "forge_runs.db",
        output_dir=tmp_path / "forge_runs",
        workspace_strategy_default="git_worktree",
        workspace_cleanup_policy_default="cleanup_always",
    )
    run_store = ForgeRunStore(settings.store_path)
    artifact_manager = ArtifactManager(settings)
    verification_runner = VerificationRunner(settings=settings)

    async def _executor(request: RunRequest, env=None) -> RunResult:
        effective_workspace = Path(request.workspace_root)
        tests_dir = effective_workspace / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "smoke.txt").write_text("ok\n", encoding="utf-8")
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Implemented in isolated workspace.",
            changed_files=("tool.py",),
        )

    scheduler = RuntimeScheduler(
        run_store=run_store,
        artifact_manager=artifact_manager,
        verification_runner=verification_runner,
        executor=_executor,
    )
    request = RunRequest(
        run_id="verify-isolated",
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(workspace),
        readable_roots=(str(repo_root),),
        writable_roots=(str(workspace),),
        backend="codex",
        timeout_sec=30.0,
        execution_policy=ExecutionPolicy(
            readable_roots=(str(repo_root),),
            writable_roots=(str(workspace),),
            workspace_strategy="git_worktree",
            workspace_cleanup_policy="cleanup_always",
        ),
        verification_policy={
            "mode": "explicit",
            "steps": [{"name": "smoke", "command": "test -f tests/smoke.txt", "required": True}],
        },
    )
    run_store.create_run(request)

    asyncio.run(scheduler._execute(request))

    result = run_store.get_run("verify-isolated")
    verification = run_store.list_verification_results("verify-isolated")
    worktree_root = settings.output_dir / "workspaces" / "verify-isolated"

    assert result.status == "completed"
    assert verification[0].status == "passed"
    assert not worktree_root.exists()


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "forge-tests@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Forge Tests"],
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "README.md").write_text("# Repo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    return path
