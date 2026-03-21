"""Service-owned artifact persistence for forge runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge.evals.models import EvalRunSummary
from sophia_forge_protocol.artifact_models import RunArtifact
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge_protocol.verification_models import VerificationResult


class ArtifactManager:
    """Writes stable runtime artifacts under the forge output root."""

    def __init__(self, settings: ForgeSettings) -> None:
        self.settings = settings

    def persist_run_artifacts(
        self,
        *,
        request: RunRequest,
        result: RunResult,
        verification_results: tuple[VerificationResult, ...] = (),
    ) -> tuple[RunArtifact, ...]:
        run_id = request.run_id or "forge_run"
        run_dir = self._ensure_run_dir(run_id)
        artifacts: list[RunArtifact] = []

        artifacts.append(
            self._write_artifact(
                run_id=run_id,
                artifact_type="task_spec",
                path=run_dir / "task.json",
                payload={
                    "run_id": run_id,
                    "client_name": request.client_name,
                    "task": request.task,
                    "backend": request.backend,
                    "workspace_root": request.workspace_root,
                    "timeout_sec": request.timeout_sec,
                    "metadata": request.metadata,
                },
                index=len(artifacts) + 1,
            )
        )
        artifacts.append(
            self._write_artifact(
                run_id=run_id,
                artifact_type="run_result",
                path=run_dir / "run_result.json",
                payload=result.model_dump(mode="json"),
                index=len(artifacts) + 1,
            )
        )
        if result.changed_files:
            artifacts.append(
                self._write_artifact(
                    run_id=run_id,
                    artifact_type="changed_files",
                    path=run_dir / "changed_files.json",
                    payload={"changed_files": list(result.changed_files)},
                    index=len(artifacts) + 1,
                )
            )
        if result.summary:
            artifacts.append(
                self._write_artifact(
                    run_id=run_id,
                    artifact_type="summary",
                    path=run_dir / "summary.json",
                    payload={
                        "summary": result.summary,
                        "status": result.status,
                        "error": result.error,
                    },
                    index=len(artifacts) + 1,
                )
            )
        if verification_results:
            verification_dir = run_dir / "verification"
            verification_dir.mkdir(parents=True, exist_ok=True)
            artifacts.append(
                self._write_artifact(
                    run_id=run_id,
                    artifact_type="verification_log",
                    path=verification_dir / "verification.json",
                    payload={
                        "verification": [
                            item.model_dump(mode="json") for item in verification_results
                        ]
                    },
                    index=len(artifacts) + 1,
                )
            )
        self._write_artifact_index(run_id=run_id, artifacts=tuple(artifacts))
        return tuple(artifacts)

    def persist_eval_summary(
        self,
        *,
        eval_run_id: str,
        summary: EvalRunSummary,
    ) -> EvalRunSummary:
        eval_dir = self._ensure_eval_dir(eval_run_id)
        summary_path = eval_dir / "summary.json"
        created_at = _utc_now()
        artifact_id = f"{_sanitize_run_id(eval_run_id)}_eval_summary_001"
        persisted = summary.model_copy(
            update={
                "eval_run_id": eval_run_id,
                "artifact_id": artifact_id,
                "summary_path": str(summary_path),
                "created_at": created_at,
            }
        )
        summary_path.write_text(
            json.dumps(persisted.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return persisted

    def persist_checkpoint_summary(
        self,
        *,
        session_id: str,
        run_id: str,
        checkpoint_id: str,
        payload: dict[str, object],
    ) -> RunArtifact:
        run_dir = self._ensure_run_dir(run_id)
        checkpoint_dir = run_dir / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        path = checkpoint_dir / f"{_sanitize_run_id(checkpoint_id)}.json"
        return self._write_artifact(
            run_id=run_id,
            artifact_type="checkpoint_summary",
            path=path,
            payload={"session_id": session_id, "checkpoint_id": checkpoint_id, **payload},
            index=900,
        )

    def write_artifact_index(self, *, run_id: str, artifacts: tuple[RunArtifact, ...]) -> None:
        self._write_artifact_index(run_id=run_id, artifacts=artifacts)

    def _write_artifact(
        self,
        *,
        run_id: str,
        artifact_type: str,
        path: Path,
        payload: dict[str, object],
        index: int,
    ) -> RunArtifact:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return RunArtifact(
            artifact_id=f"{_sanitize_run_id(run_id)}_{artifact_type}_{index:03d}",
            run_id=run_id,
            artifact_type=artifact_type,
            content_type="application/json",
            path=str(path),
            payload=None,
            created_at=_utc_now(),
        )

    def _write_artifact_index(self, *, run_id: str, artifacts: tuple[RunArtifact, ...]) -> Path:
        run_dir = self._ensure_run_dir(run_id)
        index_path = run_dir / "artifacts.json"
        payload = {
            "run_id": run_id,
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        }
        index_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return index_path

    def _ensure_run_dir(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _ensure_eval_dir(self, eval_run_id: str) -> Path:
        eval_dir = self.eval_dir(eval_run_id)
        eval_dir.mkdir(parents=True, exist_ok=True)
        return eval_dir

    def run_dir(self, run_id: str) -> Path:
        return self.settings.output_dir / _sanitize_run_id(run_id)

    def eval_dir(self, eval_run_id: str) -> Path:
        return self.settings.output_dir / "evals" / _sanitize_run_id(eval_run_id)

    def workspaces_root(self) -> Path:
        return self.settings.output_dir / "workspaces"

    def environments_root(self) -> Path:
        return self.settings.output_dir / "environments"


def _sanitize_run_id(run_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in run_id)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
