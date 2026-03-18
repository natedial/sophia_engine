"""Retention inspection and cleanup for forge-managed outputs."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge.core.artifacts import ArtifactManager
from sophia_forge.storage.run_store import ForgeRunStore
from sophia_forge_protocol.run_models import RetentionBucket, RetentionSummary


class RetentionManager:
    """Inspect and clean old forge workspaces, environments, and artifacts."""

    def __init__(
        self,
        *,
        settings: ForgeSettings,
        run_store: ForgeRunStore,
        artifact_manager: ArtifactManager,
    ) -> None:
        self.settings = settings
        self.run_store = run_store
        self.artifact_manager = artifact_manager

    def inspect(self, *, dry_run: bool = True) -> RetentionSummary:
        active_run_ids = set(self.run_store.list_active_run_ids())
        workspace_cutoff = _cutoff(self.settings.workspace_retention_days)
        environment_cutoff = _cutoff(self.settings.environment_retention_days)
        run_artifact_cutoff = _cutoff(self.settings.run_artifact_retention_days)
        eval_artifact_cutoff = _cutoff(self.settings.eval_artifact_retention_days)

        workspace_entries = self._collect_fs_candidates(
            base_dir=self.artifact_manager.workspaces_root(),
            cutoff=workspace_cutoff,
            active_run_ids=active_run_ids,
        )
        environment_entries = self._collect_fs_candidates(
            base_dir=self.artifact_manager.environments_root(),
            cutoff=environment_cutoff,
            active_run_ids=active_run_ids,
        )
        run_artifact_entries = tuple(
            (run_id, self.artifact_manager.run_dir(run_id))
            for run_id in self.run_store.list_terminal_run_ids_before(run_artifact_cutoff)
            if self.artifact_manager.run_dir(run_id).exists()
        )
        eval_artifact_entries = tuple(
            (eval_run_id, self.artifact_manager.eval_dir(eval_run_id))
            for eval_run_id in self.run_store.list_eval_run_ids_before(eval_artifact_cutoff)
            if self.artifact_manager.eval_dir(eval_run_id).exists()
        )

        deleted_workspaces = self._delete_fs_entries(workspace_entries) if not dry_run else ()
        deleted_environments = self._delete_fs_entries(environment_entries) if not dry_run else ()
        deleted_run_artifacts = (
            self._delete_run_artifacts(run_artifact_entries) if not dry_run else ()
        )
        deleted_eval_artifacts = (
            self._delete_eval_artifacts(eval_artifact_entries) if not dry_run else ()
        )

        return RetentionSummary(
            dry_run=dry_run,
            workspaces=_bucket(
                "workspaces",
                eligible_entries=workspace_entries,
                deleted_entries=deleted_workspaces,
            ),
            environments=_bucket(
                "environments",
                eligible_entries=environment_entries,
                deleted_entries=deleted_environments,
            ),
            run_artifacts=_bucket(
                "run_artifacts",
                eligible_entries=run_artifact_entries,
                deleted_entries=deleted_run_artifacts,
            ),
            eval_artifacts=_bucket(
                "eval_artifacts",
                eligible_entries=eval_artifact_entries,
                deleted_entries=deleted_eval_artifacts,
            ),
        )

    def _collect_fs_candidates(
        self,
        *,
        base_dir: Path,
        cutoff: datetime,
        active_run_ids: set[str],
    ) -> tuple[tuple[str, Path], ...]:
        if not base_dir.exists():
            return ()
        candidates: list[tuple[str, Path]] = []
        for path in sorted(item for item in base_dir.iterdir() if item.is_dir()):
            if path.name in active_run_ids:
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified < cutoff:
                candidates.append((path.name, path))
        return tuple(candidates)

    def _delete_fs_entries(self, entries: tuple[tuple[str, Path], ...]) -> tuple[tuple[str, Path], ...]:
        deleted: list[tuple[str, Path]] = []
        for run_id, path in entries:
            shutil.rmtree(path, ignore_errors=True)
            deleted.append((run_id, path))
        return tuple(deleted)

    def _delete_run_artifacts(
        self,
        entries: tuple[tuple[str, Path], ...],
    ) -> tuple[tuple[str, Path], ...]:
        deleted: list[tuple[str, Path]] = []
        for run_id, path in entries:
            shutil.rmtree(path, ignore_errors=True)
            self.run_store.prune_run_artifacts(run_id)
            deleted.append((run_id, path))
        return tuple(deleted)

    def _delete_eval_artifacts(
        self,
        entries: tuple[tuple[str, Path], ...],
    ) -> tuple[tuple[str, Path], ...]:
        deleted: list[tuple[str, Path]] = []
        for eval_run_id, path in entries:
            shutil.rmtree(path, ignore_errors=True)
            self.run_store.prune_eval_artifact(eval_run_id)
            deleted.append((eval_run_id, path))
        return tuple(deleted)


def _bucket(
    category: str,
    *,
    eligible_entries: tuple[tuple[str, Path], ...],
    deleted_entries: tuple[tuple[str, Path], ...],
) -> RetentionBucket:
    return RetentionBucket(
        category=category,
        eligible_count=len(eligible_entries),
        deleted_count=len(deleted_entries),
        eligible_paths=tuple(str(path) for _, path in eligible_entries),
        deleted_paths=tuple(str(path) for _, path in deleted_entries),
    )


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=max(0, days))
