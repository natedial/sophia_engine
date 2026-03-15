"""Capability resolver interfaces."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Awaitable, Callable

from sophia_episto.plan_models import CapabilityCheck, ResearchPlan


class CapabilityResolver(ABC):
    @abstractmethod
    def resolve(self, plan: ResearchPlan) -> tuple[CapabilityCheck, ...]: ...


class StaticCapabilityResolver(CapabilityResolver):
    """Simple resolver backed by static local-family and source mappings."""

    def __init__(
        self,
        *,
        available_indicator_families: tuple[str, ...] = (),
        source_map: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.available_indicator_families = set(available_indicator_families)
        self.source_map = source_map or {}

    def resolve(self, plan: ResearchPlan) -> tuple[CapabilityCheck, ...]:
        checks: list[CapabilityCheck] = []
        existing = {
            check.indicator_family: check
            for check in plan.evidence_plan.capability_checks
        }
        for family in plan.indicator_families:
            base = existing.get(
                family,
                CapabilityCheck(
                    concept=plan.playbook_id,
                    indicator_family=family,
                    available_locally=False,
                ),
            )
            checks.append(
                replace(
                    base,
                    available_locally=family in self.available_indicator_families,
                    candidate_sources=self.source_map.get(family, base.candidate_sources),
                )
            )
        return tuple(checks)


SearchCallable = Callable[[str], Awaitable[list[dict]]]


class SearchBackedCapabilityResolver:
    """Resolve indicator families by searching a backing series catalog."""

    def __init__(self, search: SearchCallable) -> None:
        self.search = search

    async def resolve(self, plan: ResearchPlan) -> tuple[CapabilityCheck, ...]:
        query_specs = {
            spec.indicator_family: spec
            for spec in plan.indicator_queries
        }
        checks: list[CapabilityCheck] = []
        existing = {
            check.indicator_family: check
            for check in plan.evidence_plan.capability_checks
        }

        async def _search_one(family: str, queries: tuple[str, ...]) -> tuple[str, list[dict]]:
            results: list[dict] = []
            for query in queries:
                results = await self.search(query)
                if results:
                    break
            return family, results

        tasks = []
        for family in plan.indicator_families:
            spec = query_specs.get(family)
            queries = spec.queries if spec is not None else (family.replace("_", " "),)
            tasks.append(_search_one(family, queries))
        resolved = await asyncio.gather(*tasks)

        for family, results in resolved:
            base = existing.get(
                family,
                CapabilityCheck(
                    concept=plan.playbook_id,
                    indicator_family=family,
                    available_locally=False,
                ),
            )
            spec = query_specs.get(family)
            candidate_sources = tuple(
                sorted(
                    {
                        str(item.get("source") or "").strip()
                        for item in results
                        if str(item.get("source") or "").strip()
                    }
                )
            )
            if not candidate_sources and spec is not None:
                candidate_sources = tuple(spec.preferred_sources)
            notes = ()
            if results:
                ids = [
                    str(item.get("external_id") or "").strip()
                    for item in results[:3]
                    if str(item.get("external_id") or "").strip()
                ]
                if ids:
                    notes = ("matched series: " + ", ".join(ids),)
            checks.append(
                replace(
                    base,
                    available_locally=bool(results),
                    candidate_sources=candidate_sources or base.candidate_sources,
                    notes=notes or base.notes,
                )
            )
        return tuple(checks)
