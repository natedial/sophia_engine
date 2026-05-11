"""Optional integration boundary from Prima into Episto."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class EpistoPlanContext:
    """Compact context derived from an Episto research plan."""

    playbook_id: str
    summary: str
    indicator_families: tuple[str, ...] = ()
    indicator_queries: tuple[dict[str, object], ...] = ()
    capability_checks: tuple[dict[str, object], ...] = ()
    acquisition_decisions: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class CausalQueryResult:
    """Result of a causal query."""

    source: str
    target: str
    direct_strength: float
    path_influence: float
    confidence: float
    explanation: str
    n_mediators: int
    n_confounders: int


class EpistoPlannerAdapter:
    """Graceful Episto adapter that becomes a no-op when the package is unavailable."""

    def __init__(self, pylon=None) -> None:
        self._pylon = pylon
        self._causal_service = None
        try:
            from sophia_episto.capability import SearchBackedCapabilityResolver
            from sophia_episto.intake import build_question_brief
            from sophia_episto.policy import RuleBasedAcquisitionPolicy
            from sophia_episto.playbooks.registry import default_playbooks
            from sophia_episto.planner import PlaybookPlanner
        except ImportError:
            self._build_question_brief = None
            self._planner = None
            self._capability_resolver_cls = None
            self._acquisition_policy = None
            return

        self._build_question_brief = build_question_brief
        self._planner = PlaybookPlanner(default_playbooks())
        self._capability_resolver_cls = SearchBackedCapabilityResolver
        self._acquisition_policy = RuleBasedAcquisitionPolicy()

    @property
    def available(self) -> bool:
        return self._planner is not None and self._build_question_brief is not None

    @property
    def causal_available(self) -> bool:
        if self._causal_service is None:
            try:
                from sophia_episto.causal_service import CausalWorldModelService

                self._causal_service = CausalWorldModelService.from_default_path()
            except ImportError:
                return False
        return True

    async def plan(self, question: str) -> EpistoPlanContext | None:
        if not self.available or self._planner is None or self._build_question_brief is None:
            return None

        brief = self._build_question_brief(question)
        if brief.intent != "econ_research":
            return None

        plan = self._planner.build_plan(brief)
        if not plan.playbook_id:
            return None

        indicator_queries = tuple(
            {
                "indicator_family": spec.indicator_family,
                "queries": spec.queries,
                "preferred_sources": spec.preferred_sources,
                "structured_data": spec.structured_data,
                "freshness_sensitive": spec.freshness_sensitive,
                "reuse_expectation": spec.reuse_expectation.value,
                "retention_target_on_acquire": spec.retention_target_on_acquire,
            }
            for spec in plan.indicator_queries
        )
        capability_checks: tuple[dict[str, object], ...] = ()
        acquisition_decisions: tuple[dict[str, object], ...] = ()
        if self._capability_resolver_cls is not None and self._pylon is not None:
            resolver = self._capability_resolver_cls(self._search_local_series)
            resolved = await resolver.resolve(plan)
            capability_checks = tuple(
                {
                    "indicator_family": check.indicator_family,
                    "available_locally": check.available_locally,
                    "candidate_sources": check.candidate_sources,
                    "notes": check.notes,
                }
                for check in resolved
            )
            if self._acquisition_policy is not None:
                decisions = self._acquisition_policy.decide(plan, resolved)
                acquisition_decisions = tuple(
                    {
                        "indicator_family": decision.indicator_family,
                        "mode": decision.mode.value,
                        "handling_mode": decision.handling_mode.value,
                        "source": decision.source,
                        "rationale": decision.rationale,
                        "retention_target": decision.retention_target,
                        "freshness_required": decision.freshness_required,
                        "requires_human_review": decision.requires_human_review,
                        "reason_tags": decision.reason_tags,
                    }
                    for decision in decisions
                )

        lines = [
            f"Playbook: {plan.playbook_id}",
            "Subquestions:",
            *[f"- {item}" for item in plan.subquestions],
        ]
        if plan.indicator_families:
            lines.append("Indicator families: " + ", ".join(plan.indicator_families))
        if capability_checks:
            lines.append("Capability status:")
            for item in capability_checks:
                status = "local" if item["available_locally"] else "missing"
                line = f"- {item['indicator_family']}: {status}"
                sources = item["candidate_sources"]
                if isinstance(sources, tuple) and sources:
                    line += " via " + ", ".join(str(source) for source in sources)
                notes = item["notes"]
                if isinstance(notes, tuple) and notes:
                    line += f" ({notes[0]})"
                lines.append(line)
        if acquisition_decisions:
            lines.append("Acquisition decisions:")
            for item in acquisition_decisions:
                line = f"- {item['indicator_family']}: {item['mode']} [{item['handling_mode']}]"
                if item["source"]:
                    line += f" via {item['source']}"
                if item["retention_target"]:
                    line += f" -> {item['retention_target']}"
                if item["requires_human_review"]:
                    line += " (review)"
                lines.append(line)
        if plan.transforms:
            lines.append("Transforms: " + ", ".join(plan.transforms))
        if plan.success_criteria:
            lines.append("Success criteria:")
            lines.extend(f"- {item}" for item in plan.success_criteria)

        return EpistoPlanContext(
            playbook_id=plan.playbook_id,
            summary="\n".join(lines),
            indicator_families=plan.indicator_families,
            indicator_queries=indicator_queries,
            capability_checks=capability_checks,
            acquisition_decisions=acquisition_decisions,
        )

    async def query_causal(self, source: str, target: str) -> CausalQueryResult | None:
        """Query causal effect from source to target."""
        if not self.causal_available:
            return None

        try:
            result = self._causal_service.query(source, target)
            return CausalQueryResult(
                source=result["source"],
                target=result["target"],
                direct_strength=result["direct_strength"],
                path_influence=result["path_influence"],
                confidence=result["confidence"],
                explanation=result["explanation"],
                n_mediators=result["n_mediators"],
                n_confounders=result["n_confounders"],
            )
        except Exception:
            return None

    async def explain_causal(self, node: str) -> dict | None:
        """Explain causal relationships for a node."""
        if not self.causal_available:
            return None

        try:
            return self._causal_service.explain(node)
        except Exception:
            return None

    async def get_causal_graph_state(self) -> dict | None:
        """Get current causal graph state for dashboard."""
        if not self.causal_available:
            return None

        try:
            return self._causal_service.get_graph_state()
        except Exception:
            return None

    async def _search_local_series(self, query: str) -> list[dict]:
        if self._pylon is None:
            return []
        try:
            result = await self._pylon.execute_tool("search_series", {"query": query})
        except Exception:
            return []
        if not getattr(result, "success", False):
            return []
        try:
            parsed = json.loads(result.to_content())
        except json.JSONDecodeError:
            return []
        return (
            [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
        )
