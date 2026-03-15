"""Adapter-backed on-demand series acquisition for Scrivener."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from src.fetchers import BlsFetcher, FredFetcher

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AcquisitionCandidate:
    external_id: str
    name: str
    source: str
    description: str | None = None
    frequency: str | None = None
    units: str | None = None


@dataclass(frozen=True)
class AcquisitionRequest:
    source: str
    external_id: str | None = None
    query: str | None = None
    retention_target: str = "staging"
    start_date: date | None = None
    end_date: date | None = None
    max_candidates: int = 5
    promote_if_valid: bool = False


class BaseAcquisitionAdapter:
    """Source adapter for resolving and ingesting external series."""

    source_name: str = ""

    def search_candidates(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[AcquisitionCandidate]:
        return []

    def ingest_series(
        self,
        external_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class FredAcquisitionAdapter(BaseAcquisitionAdapter):
    source_name = "FRED"

    def __init__(self) -> None:
        self.fetcher = FredFetcher()

    def search_candidates(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[AcquisitionCandidate]:
        return [
            AcquisitionCandidate(**candidate)
            for candidate in self.fetcher.search_series_candidates(query, limit=limit)
        ]

    def ingest_series(
        self,
        external_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        return self.fetcher.fetch_and_store(
            external_id,
            start_date=start_date,
            end_date=end_date,
        )


class BlsAcquisitionAdapter(BaseAcquisitionAdapter):
    source_name = "BLS"

    def __init__(self) -> None:
        self.fetcher = BlsFetcher()

    def search_candidates(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[AcquisitionCandidate]:
        return [
            AcquisitionCandidate(**candidate)
            for candidate in self.fetcher.search_series_candidates(query, limit=limit)
        ]

    def ingest_series(
        self,
        external_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        return self.fetcher.fetch_and_store(
            external_id,
            start_date=start_date,
            end_date=end_date,
        )


class AcquisitionService:
    """Resolve and ingest series through a controlled adapter registry."""

    def __init__(
        self,
        *,
        adapters: dict[str, BaseAcquisitionAdapter] | None = None,
    ) -> None:
        self.adapters = adapters or self._build_default_adapters()

    def resolve(self, request: AcquisitionRequest) -> dict[str, Any]:
        adapter = self._require_adapter(request.source)

        candidates: list[AcquisitionCandidate] = []
        if request.external_id:
            candidates.append(
                AcquisitionCandidate(
                    external_id=request.external_id,
                    name=request.external_id,
                    source=adapter.source_name,
                )
            )
        elif request.query:
            candidates.extend(
                adapter.search_candidates(request.query, limit=request.max_candidates)
            )
        else:
            raise ValueError("either external_id or query is required")

        return {
            "status": "ok",
            "source": adapter.source_name,
            "query": request.query,
            "requested_external_id": request.external_id,
            "candidates": [asdict(candidate) for candidate in candidates],
        }

    def ingest(self, request: AcquisitionRequest) -> dict[str, Any]:
        adapter = self._require_adapter(request.source)
        selected_candidate: AcquisitionCandidate | None = None

        if request.external_id:
            selected_candidate = AcquisitionCandidate(
                external_id=request.external_id,
                name=request.external_id,
                source=adapter.source_name,
            )
        elif request.query:
            candidates = adapter.search_candidates(request.query, limit=request.max_candidates)
            selection = self._select_candidate(
                request=request,
                candidates=candidates,
            )
            if isinstance(selection, AcquisitionCandidate):
                selected_candidate = selection
            elif selection is not None:
                return selection
        else:
            raise ValueError("either external_id or query is required")

        if selected_candidate is None:
            return {
                "status": "not_found",
                "source": adapter.source_name,
                "query": request.query,
                "retention_target": request.retention_target,
                "message": "No source candidate could be resolved for ingestion.",
                "selected_candidate": None,
            }

        result = adapter.ingest_series(
            selected_candidate.external_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        normalized_status = "success" if result.get("status") == "success" else "error"
        return {
            "status": normalized_status,
            "source": adapter.source_name,
            "external_id": selected_candidate.external_id,
            "query": request.query,
            "retention_target": request.retention_target,
            "selected_candidate": asdict(selected_candidate),
            "ingestion_result": result,
            "promotion": {
                "requested": request.promote_if_valid,
                "eligible": bool(request.promote_if_valid and normalized_status == "success"),
                "target": "canonical" if request.promote_if_valid else request.retention_target,
            },
        }

    def _select_candidate(
        self,
        *,
        request: AcquisitionRequest,
        candidates: list[AcquisitionCandidate],
    ) -> AcquisitionCandidate | dict[str, Any] | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        query = (request.query or "").strip().lower()
        if not query:
            return {
                "status": "ambiguous",
                "source": request.source.upper(),
                "query": request.query,
                "retention_target": request.retention_target,
                "message": "Multiple candidates matched the request; provide an explicit external_id.",
                "candidates": [asdict(candidate) for candidate in candidates],
            }

        sector_terms = (
            "health care",
            "healthcare",
            "social assistance",
            "naics 62",
        )
        if any(term in query for term in sector_terms):
            sector_candidates = [
                candidate
                for candidate in candidates
                if "health care and social assistance"
                in f"{candidate.name} {candidate.description or ''}".lower()
            ]
            if len(sector_candidates) == 1:
                return sector_candidates[0]
            return {
                "status": "ambiguous",
                "source": request.source.upper(),
                "query": request.query,
                "retention_target": request.retention_target,
                "message": "No unambiguous sector-level candidate could be resolved for this query.",
                "candidates": [asdict(candidate) for candidate in candidates],
            }

        scored = sorted(
            (
                self._candidate_score(query, candidate),
                index,
                candidate,
            )
            for index, candidate in enumerate(candidates)
        )
        top_score, _top_index, top_candidate = scored[-1]
        next_score = scored[-2][0] if len(scored) > 1 else -1
        if top_score > next_score and top_score >= 2:
            return top_candidate
        return {
            "status": "ambiguous",
            "source": request.source.upper(),
            "query": request.query,
            "retention_target": request.retention_target,
            "message": "Multiple candidates matched the request; resolve first or provide an explicit external_id.",
            "candidates": [asdict(candidate) for candidate in candidates],
        }

    @staticmethod
    def _candidate_score(query: str, candidate: AcquisitionCandidate) -> int:
        haystack = f"{candidate.external_id} {candidate.name} {candidate.description or ''}".lower()
        query_terms = [term for term in query.replace('"', " ").split() if len(term) > 2]
        return sum(1 for term in query_terms if term in haystack)

    def _require_adapter(self, source: str) -> BaseAcquisitionAdapter:
        adapter = self.adapters.get(source.upper().strip())
        if adapter is None:
            raise ValueError(f"unsupported acquisition source '{source}'")
        return adapter

    def _build_default_adapters(self) -> dict[str, BaseAcquisitionAdapter]:
        adapters: dict[str, BaseAcquisitionAdapter] = {}
        for adapter_cls in (FredAcquisitionAdapter, BlsAcquisitionAdapter):
            try:
                adapter = adapter_cls()
            except Exception as exc:
                logger.warning("acquisition adapter unavailable: %s", exc)
                continue
            adapters[adapter.source_name.upper()] = adapter
        return adapters
