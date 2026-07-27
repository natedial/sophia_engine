"""Gateway acquisition job execution helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from pylon import Pylon

from sophia.gateway.research_plan_artifacts import (
    resolve_indicator_query_spec,
    resolve_research_plan_event,
)
from sophia.gateway.run_store import GatewayRunStore


RunLookup = Callable[[str], dict[str, object] | None]


@dataclass
class GatewayAcquisitionService:
    """Executes queued acquisition jobs against the available tool stack."""

    pylon: Pylon
    run_store: GatewayRunStore
    lookup_run: RunLookup

    async def execute_job(
        self,
        *,
        job_id: str,
        observation_days: int = 365,
    ) -> dict[str, Any]:
        job = self.run_store.get_acquisition_job(job_id)
        if job is None:
            raise ValueError(f"acquisition job '{job_id}' not found")

        mode = str(job.get("mode") or "").strip().lower()
        if mode == "none":
            self.run_store.update_acquisition_job_status(job_id=job_id, status="completed")
            self.run_store.save_acquisition_artifact(
                job_id=job_id,
                run_id=_as_optional_str(job.get("run_id")),
                session_id=_required_str(job, "session_id"),
                agent_id=_required_str(job, "agent_id"),
                stage="decision",
                status="completed",
                payload={
                    "message": "No acquisition required because the series is already available locally.",
                    "indicator_family": _required_str(job, "indicator_family"),
                },
            )
            return self.run_store.get_acquisition_job(job_id) or {}

        if mode == "defer":
            self.run_store.update_acquisition_job_status(job_id=job_id, status="deferred")
            self.run_store.save_acquisition_artifact(
                job_id=job_id,
                run_id=_as_optional_str(job.get("run_id")),
                session_id=_required_str(job, "session_id"),
                agent_id=_required_str(job, "agent_id"),
                stage="decision",
                status="deferred",
                payload={
                    "message": "Acquisition deferred by policy.",
                    "indicator_family": _required_str(job, "indicator_family"),
                },
            )
            return self.run_store.get_acquisition_job(job_id) or {}

        if mode == "reject":
            self.run_store.update_acquisition_job_status(job_id=job_id, status="rejected")
            self.run_store.save_acquisition_artifact(
                job_id=job_id,
                run_id=_as_optional_str(job.get("run_id")),
                session_id=_required_str(job, "session_id"),
                agent_id=_required_str(job, "agent_id"),
                stage="decision",
                status="rejected",
                payload={
                    "message": "Acquisition rejected by source policy.",
                    "indicator_family": _required_str(job, "indicator_family"),
                },
            )
            return self.run_store.get_acquisition_job(job_id) or {}

        self.run_store.update_acquisition_job_status(job_id=job_id, status="running")
        run_id = _as_optional_str(job.get("run_id"))
        session_id = _required_str(job, "session_id")
        agent_id = _required_str(job, "agent_id")
        indicator_family = _required_str(job, "indicator_family")
        requested_source = _as_optional_str(job.get("requested_source"))

        try:
            plan_data = self._lookup_plan_data(run_id=run_id, indicator_family=indicator_family)
            query_spec = resolve_indicator_query_spec(
                plan_data,
                indicator_family=indicator_family,
            )
            queries = _coerce_queries(query_spec, indicator_family=indicator_family)
            preferred_sources = _coerce_preferred_sources(query_spec)

            resolution = await self._resolve_series_candidate(
                queries=queries,
                requested_source=requested_source,
                preferred_sources=preferred_sources,
            )
            ingestion_result: dict[str, Any] | None = None
            if resolution is None and requested_source:
                ingestion_result = await self._attempt_external_ingestion(
                    source=requested_source,
                    queries=queries,
                    retention_target=_as_optional_str(job.get("retention_target")) or "staging",
                )
                if ingestion_result is not None and ingestion_result.get("status") == "success":
                    resolution = _candidate_from_ingestion_result(ingestion_result)

            if resolution is None:
                self.run_store.update_acquisition_job_status(job_id=job_id, status="blocked")
                self.run_store.save_acquisition_artifact(
                    job_id=job_id,
                    run_id=run_id,
                    session_id=session_id,
                    agent_id=agent_id,
                    stage="resolution",
                    status="blocked",
                    payload={
                        "indicator_family": indicator_family,
                        "requested_source": requested_source,
                        "queries": list(queries),
                        "preferred_sources": list(preferred_sources),
                        "ingestion_result": ingestion_result,
                        "message": (
                            "No matching series was found in the current catalog. "
                            "An external acquisition backend or source adapter is still required."
                        ),
                        "next_action": "await_external_acquisition_backend",
                    },
                )
                return self.run_store.get_acquisition_job(job_id) or {}

            series_id = str(
                resolution.get("external_id")
                or resolution.get("series_id")
                or resolution.get("id")
                or ""
            ).strip()
            metadata = await self._load_json_object("get_series_info", {"series_id": series_id})
            observations = await self._load_json_value(
                "get_observations",
                {"series_id": series_id, "days": observation_days},
            )

            self.run_store.update_acquisition_job_status(job_id=job_id, status="completed")
            self.run_store.save_acquisition_artifact(
                job_id=job_id,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
                stage="materialization",
                status="completed",
                payload={
                    "indicator_family": indicator_family,
                    "requested_source": requested_source,
                    "query_attempts": list(queries),
                    "selected_series": resolution,
                    "series_id": series_id,
                    "retention_target": _as_optional_str(job.get("retention_target")),
                    "ingestion_result": ingestion_result,
                    "metadata": metadata,
                    "observations": observations,
                    "validation": {
                        "metadata_found": bool(metadata),
                        "observations_found": _has_observations(observations),
                    },
                    "next_action": "hand_off_to_validation_or_ingestion",
                },
            )
            return self.run_store.get_acquisition_job(job_id) or {}
        except Exception as exc:
            self.run_store.update_acquisition_job_status(job_id=job_id, status="failed")
            self.run_store.save_acquisition_artifact(
                job_id=job_id,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
                stage="execution",
                status="failed",
                payload={
                    "indicator_family": indicator_family,
                    "requested_source": requested_source,
                    "message": str(exc),
                },
            )
            raise

    def _lookup_plan_data(
        self,
        *,
        run_id: str | None,
        indicator_family: str,
    ) -> dict[str, object]:
        if run_id is not None:
            record = self.lookup_run(run_id)
            if record is not None:
                return resolve_research_plan_event(record, indicator_family=indicator_family)
        return {
            "indicator_families": (indicator_family,),
            "indicator_queries": (
                {
                    "indicator_family": indicator_family,
                    "queries": (indicator_family.replace("_", " "),),
                    "preferred_sources": (),
                },
            ),
        }

    async def _resolve_series_candidate(
        self,
        *,
        queries: tuple[str, ...],
        requested_source: str | None,
        preferred_sources: tuple[str, ...],
    ) -> dict[str, Any] | None:
        for query in queries:
            rows = await self._load_json_rows("search_series", {"query": query})
            filtered = _filter_rows_by_source(
                rows,
                requested_source=requested_source,
                preferred_sources=preferred_sources,
            )
            if filtered:
                return filtered[0]
        return None

    async def _load_json_rows(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        parsed = await self._load_json_value(tool_name, payload)
        if isinstance(parsed, list):
            return [row for row in parsed if isinstance(row, dict)]
        if isinstance(parsed, dict):
            results = parsed.get("results")
            if isinstance(results, list):
                return [row for row in results if isinstance(row, dict)]
            series = parsed.get("series")
            if isinstance(series, list):
                return [row for row in series if isinstance(row, dict)]
        return []

    async def _load_json_object(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        parsed = await self._load_json_value(tool_name, payload)
        return parsed if isinstance(parsed, dict) else {}

    async def _load_json_value(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> Any:
        result = await self.pylon.execute_tool(tool_name, payload)
        if not getattr(result, "success", False):
            raise RuntimeError(result.to_content())
        try:
            return json.loads(result.to_content())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{tool_name} returned invalid JSON") from exc

    async def _attempt_external_ingestion(
        self,
        *,
        source: str,
        queries: tuple[str, ...],
        retention_target: str,
    ) -> dict[str, Any] | None:
        if not queries:
            return None
        try:
            parsed = await self._load_json_value(
                "ingest_series",
                {
                    "source": source,
                    "query": queries[0],
                    "retention_target": retention_target,
                    "max_candidates": 5,
                    "promote_if_valid": False,
                },
            )
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None


def _filter_rows_by_source(
    rows: list[dict[str, Any]],
    *,
    requested_source: str | None,
    preferred_sources: tuple[str, ...],
) -> list[dict[str, Any]]:
    if requested_source:
        requested_upper = requested_source.upper()
        source_matches = [
            row for row in rows
            if str(row.get("source") or "").upper() == requested_upper
        ]
        if source_matches:
            return source_matches
    for source in preferred_sources:
        source_upper = str(source).upper()
        preferred_matches = [
            row for row in rows
            if str(row.get("source") or "").upper() == source_upper
        ]
        if preferred_matches:
            return preferred_matches
    return rows


def _coerce_queries(
    query_spec: dict[str, object] | None,
    *,
    indicator_family: str,
) -> tuple[str, ...]:
    if query_spec is not None:
        raw = query_spec.get("queries")
        if isinstance(raw, (list, tuple)):
            queries = tuple(str(item).strip() for item in raw if str(item).strip())
            if queries:
                return queries
    return (indicator_family.replace("_", " "),)


def _coerce_preferred_sources(query_spec: dict[str, object] | None) -> tuple[str, ...]:
    if query_spec is None:
        return ()
    raw = query_spec.get("preferred_sources")
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _required_str(job: dict[str, Any], key: str) -> str:
    value = job.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"acquisition job is missing required field '{key}'")
    return value


def _as_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _has_observations(payload: Any) -> bool:
    if isinstance(payload, list):
        return bool(payload)
    if isinstance(payload, dict):
        for key in ("observations", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                return True
    return False


def _candidate_from_ingestion_result(result: dict[str, Any]) -> dict[str, Any] | None:
    candidate = result.get("selected_candidate")
    if isinstance(candidate, dict):
        return candidate
    external_id = result.get("external_id")
    if isinstance(external_id, str) and external_id.strip():
        return {
            "external_id": external_id,
            "source": result.get("source"),
            "name": external_id,
        }
    return None
