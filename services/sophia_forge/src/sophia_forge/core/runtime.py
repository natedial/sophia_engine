"""Top-level runtime facade for the forge service."""

from __future__ import annotations

import uuid

from sophia_forge.config import ForgeSettings
from sophia_forge.core.artifacts import ArtifactManager
from sophia_forge.core.scheduler import ForgeExecutor, RuntimeScheduler
from sophia_forge.core.verification import VerificationRunner
from sophia_forge.storage.run_store import ForgeRunStore
from sophia_forge_protocol.artifact_models import RunArtifact
from sophia_forge_protocol.event_models import RunEvent
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge_protocol.verification_models import VerificationResult


class ForgeRuntime:
    """Coordinates run submission, persistence, and background execution."""

    def __init__(
        self,
        *,
        settings: ForgeSettings | None = None,
        executor: ForgeExecutor | None = None,
    ) -> None:
        self.settings = settings or ForgeSettings()
        self.run_store = ForgeRunStore(self.settings.store_path)
        self.artifact_manager = ArtifactManager(self.settings)
        self.verification_runner = VerificationRunner(settings=self.settings)
        self.scheduler = RuntimeScheduler(
            run_store=self.run_store,
            artifact_manager=self.artifact_manager,
            verification_runner=self.verification_runner,
            executor=executor,
            max_concurrent_runs=self.settings.max_concurrent_runs,
        )

    async def submit_run(self, request: RunRequest) -> RunResult:
        run_id = request.run_id or f"forge_{uuid.uuid4().hex[:12]}"
        normalized = request.model_copy(update={"run_id": run_id})
        snapshot = self.run_store.create_run(normalized)
        self.run_store.append_event(
            RunEvent(
                run_id=run_id,
                sequence=1,
                event_type="run_queued",
                timestamp=_utc_now(),
                payload={"backend": normalized.backend, "client_name": normalized.client_name},
            )
        )
        await self.scheduler.enqueue(normalized)
        return snapshot

    def get_run(self, run_id: str) -> RunResult:
        return self.run_store.get_run(run_id)

    def get_events(self, run_id: str) -> tuple[RunEvent, ...]:
        return self.run_store.list_events(run_id)

    def get_artifacts(self, run_id: str) -> tuple[RunArtifact, ...]:
        return self.run_store.list_artifacts(run_id)

    def get_verification_results(self, run_id: str) -> tuple[VerificationResult, ...]:
        return self.run_store.list_verification_results(run_id)

    async def cancel_run(self, run_id: str) -> RunResult:
        return await self.scheduler.cancel(run_id)


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
