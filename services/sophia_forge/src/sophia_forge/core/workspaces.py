"""Workspace preparation and cleanup for forge runs."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge_protocol.run_models import RunRequest


@dataclass(frozen=True)
class PreparedWorkspace:
    """Resolved workspace information for one forge run."""

    run_id: str
    strategy: str
    cleanup_policy: str
    workspace_root: Path
    readable_roots: tuple[Path, ...]
    writable_roots: tuple[Path, ...]
    repo_root: Path | None = None
    worktree_root: Path | None = None


class WorkspaceManager:
    """Prepare isolated workspaces for forge coding backends."""

    def __init__(self, settings: ForgeSettings) -> None:
        self.settings = settings

    def prepare(self, request: RunRequest) -> PreparedWorkspace:
        strategy = request.execution_policy.workspace_strategy
        if strategy == "inherit":
            strategy = self.settings.workspace_strategy_default
        cleanup_policy = request.execution_policy.workspace_cleanup_policy
        if cleanup_policy == "inherit":
            cleanup_policy = self.settings.workspace_cleanup_policy_default

        workspace_root = Path(request.workspace_root).expanduser().resolve(strict=False)
        writable_roots = tuple(
            Path(path).expanduser().resolve(strict=False)
            for path in (request.execution_policy.writable_roots or request.writable_roots)
        ) or (workspace_root,)
        readable_roots = tuple(
            Path(path).expanduser().resolve(strict=False)
            for path in (request.execution_policy.readable_roots or request.readable_roots)
        ) or (workspace_root,)

        if strategy != "git_worktree":
            workspace_root.mkdir(parents=True, exist_ok=True)
            return PreparedWorkspace(
                run_id=request.run_id or "forge_run",
                strategy="shared",
                cleanup_policy=cleanup_policy,
                workspace_root=workspace_root,
                readable_roots=readable_roots,
                writable_roots=writable_roots,
            )

        repo_root = self._find_repo_root(workspace_root)
        if repo_root is None:
            raise ValueError(f"Git worktree strategy requested but no git repo found for {workspace_root}")

        worktree_root = (
            self.settings.output_dir / "workspaces" / _sanitize_run_id(request.run_id or "forge_run") / "repo"
        )
        worktree_root.parent.mkdir(parents=True, exist_ok=True)
        if worktree_root.exists():
            shutil.rmtree(worktree_root)
        subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(worktree_root), "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        mapped_workspace_root = (
            worktree_root / workspace_root.relative_to(repo_root)
            if _is_within(workspace_root, repo_root)
            else worktree_root
        )
        mapped_writable_roots = tuple(
            self._map_root(root, repo_root=repo_root, worktree_root=worktree_root)
            for root in writable_roots
        )
        mapped_readable_roots = tuple(
            self._map_root(root, repo_root=repo_root, worktree_root=worktree_root)
            for root in readable_roots
        )
        return PreparedWorkspace(
            run_id=request.run_id or "forge_run",
            strategy="git_worktree",
            cleanup_policy=cleanup_policy,
            workspace_root=mapped_workspace_root,
            readable_roots=mapped_readable_roots,
            writable_roots=mapped_writable_roots,
            repo_root=repo_root,
            worktree_root=worktree_root,
        )

    def cleanup(self, prepared: PreparedWorkspace, *, final_status: str) -> None:
        if prepared.strategy != "git_worktree" or prepared.worktree_root is None or prepared.repo_root is None:
            return
        if prepared.cleanup_policy == "keep":
            return
        if prepared.cleanup_policy == "cleanup_on_success" and final_status != "completed":
            return
        subprocess.run(
            ["git", "-C", str(prepared.repo_root), "worktree", "remove", "--force", str(prepared.worktree_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        if prepared.worktree_root.parent.exists():
            shutil.rmtree(prepared.worktree_root.parent, ignore_errors=True)

    @staticmethod
    def _find_repo_root(path: Path) -> Path | None:
        for candidate in (path, *path.parents):
            git_marker = candidate / ".git"
            if git_marker.exists():
                return candidate
        return None

    @staticmethod
    def _map_root(root: Path, *, repo_root: Path, worktree_root: Path) -> Path:
        if _is_within(root, repo_root):
            return worktree_root / root.relative_to(repo_root)
        return root


def _sanitize_run_id(run_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in run_id)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
