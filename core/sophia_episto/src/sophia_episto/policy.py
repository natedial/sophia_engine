"""Policy interfaces for capability, acquisition, and retention decisions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sophia_episto.plan_models import (
    AcquisitionDecision,
    AcquisitionMode,
    CapabilityCheck,
    DataHandlingMode,
    IndicatorQuerySpec,
    ResearchPlan,
    ReuseExpectation,
)


class AcquisitionPolicy(ABC):
    @abstractmethod
    def decide(
        self,
        plan: ResearchPlan,
        capability_checks: tuple[CapabilityCheck, ...],
    ) -> tuple[AcquisitionDecision, ...]: ...


class RetentionPolicy(ABC):
    @abstractmethod
    def retention_target(self, *, confidence: float, reuse_score: float) -> str: ...


class RuleBasedAcquisitionPolicy(AcquisitionPolicy):
    """Acquisition policy that encodes source/store/ephemeral/escalation choices."""

    def __init__(
        self,
        *,
        approved_sources: tuple[str, ...] = ("FRED", "BLS"),
        fetch_on_miss: bool = True,
        default_retention_target: str = "staging",
    ) -> None:
        self.approved_sources = {source.upper() for source in approved_sources}
        self.fetch_on_miss = fetch_on_miss
        self.default_retention_target = default_retention_target

    def decide(
        self,
        plan: ResearchPlan,
        capability_checks: tuple[CapabilityCheck, ...],
    ) -> tuple[AcquisitionDecision, ...]:
        specs = {
            spec.indicator_family: spec
            for spec in plan.indicator_queries
        }
        decisions: list[AcquisitionDecision] = []
        for check in capability_checks:
            spec = specs.get(check.indicator_family)
            preferred_retention = (
                spec.retention_target_on_acquire
                if spec is not None
                else self.default_retention_target
            )
            if check.available_locally:
                if check.freshness_ok:
                    decisions.append(
                        AcquisitionDecision(
                            concept=plan.playbook_id,
                            indicator_family=check.indicator_family,
                            mode=AcquisitionMode.NONE,
                            handling_mode=DataHandlingMode.SOURCE_LOCAL,
                            rationale="Local series already available and fresh enough to answer directly.",
                            retention_target="canonical",
                            reason_tags=("known_domain", "local_available", "fresh_enough"),
                        )
                    )
                    continue

            approved = [
                source for source in check.candidate_sources
                if source.upper() in self.approved_sources
            ]
            if approved:
                handling_mode = self._handling_mode(spec)
                retention_target = (
                    preferred_retention
                    if handling_mode == DataHandlingMode.ACQUIRE_AND_STORE
                    else "ephemeral"
                )
                rationale = self._approved_source_rationale(
                    check=check,
                    spec=spec,
                    handling_mode=handling_mode,
                )
                reason_tags = self._reason_tags(
                    check=check,
                    spec=spec,
                    handling_mode=handling_mode,
                    approved=True,
                )
                if self.fetch_on_miss:
                    decisions.append(
                        AcquisitionDecision(
                            concept=plan.playbook_id,
                            indicator_family=check.indicator_family,
                            mode=AcquisitionMode.FETCH_NOW,
                            handling_mode=handling_mode,
                            source=approved[0],
                            rationale=rationale,
                            retention_target=retention_target,
                            freshness_required=spec.freshness_sensitive if spec is not None else False,
                            reason_tags=reason_tags,
                        )
                    )
                    continue
                decisions.append(
                    AcquisitionDecision(
                        concept=plan.playbook_id,
                        indicator_family=check.indicator_family,
                        mode=AcquisitionMode.DEFER,
                        handling_mode=handling_mode,
                        source=approved[0],
                        rationale="Approved source exists but policy is not set to fetch immediately.",
                        retention_target=retention_target,
                        freshness_required=spec.freshness_sensitive if spec is not None else False,
                        reason_tags=reason_tags,
                    )
                )
                continue
            if check.candidate_sources:
                decisions.append(
                    AcquisitionDecision(
                        concept=plan.playbook_id,
                        indicator_family=check.indicator_family,
                        mode=AcquisitionMode.REJECT,
                        handling_mode=DataHandlingMode.REJECT_OR_ESCALATE,
                        rationale="Only non-approved sources were identified.",
                        retention_target="ephemeral",
                        requires_human_review=True,
                        reason_tags=("unapproved_source", "human_review_required"),
                    )
                )
                continue
            decisions.append(
                AcquisitionDecision(
                    concept=plan.playbook_id,
                    indicator_family=check.indicator_family,
                    mode=AcquisitionMode.DEFER,
                    handling_mode=self._deferred_handling_mode(spec),
                    rationale=self._missing_source_rationale(spec),
                    retention_target=self._missing_source_retention_target(spec),
                    freshness_required=spec.freshness_sensitive if spec is not None else False,
                    requires_human_review=self._missing_source_requires_review(spec),
                    reason_tags=self._missing_source_reason_tags(spec),
                )
            )
        return tuple(decisions)

    def _handling_mode(self, spec: IndicatorQuerySpec | None) -> DataHandlingMode:
        if spec is None:
            return DataHandlingMode.ACQUIRE_EPHEMERAL
        if spec.structured_data and spec.reuse_expectation in {
            ReuseExpectation.HIGH,
            ReuseExpectation.MEDIUM,
        }:
            return DataHandlingMode.ACQUIRE_AND_STORE
        return DataHandlingMode.ACQUIRE_EPHEMERAL

    def _deferred_handling_mode(self, spec: IndicatorQuerySpec | None) -> DataHandlingMode:
        if spec is None:
            return DataHandlingMode.ACQUIRE_EPHEMERAL
        if spec.structured_data and spec.reuse_expectation != ReuseExpectation.LOW:
            return DataHandlingMode.ACQUIRE_AND_STORE
        return DataHandlingMode.ACQUIRE_EPHEMERAL

    def _approved_source_rationale(
        self,
        *,
        check: CapabilityCheck,
        spec: IndicatorQuerySpec | None,
        handling_mode: DataHandlingMode,
    ) -> str:
        if check.available_locally and not check.freshness_ok:
            if spec is not None and spec.freshness_sensitive:
                return "Local series exists but is stale for a freshness-sensitive query; reacquire from an approved source."
            return "Local series exists but failed freshness policy; reacquire from an approved source."
        if handling_mode == DataHandlingMode.ACQUIRE_AND_STORE:
            return "Missing locally but maps to an approved structured dataset that should be retained for reuse."
        return "Missing locally; fetch from an approved source as run-scoped supporting evidence."

    def _reason_tags(
        self,
        *,
        check: CapabilityCheck,
        spec: IndicatorQuerySpec | None,
        handling_mode: DataHandlingMode,
        approved: bool,
    ) -> tuple[str, ...]:
        tags = ["approved_source" if approved else "unapproved_source"]
        if check.available_locally:
            tags.append("local_available")
        else:
            tags.append("local_missing")
        if not check.freshness_ok:
            tags.append("stale_local_data")
        if spec is not None:
            if spec.structured_data:
                tags.append("structured_dataset")
            tags.append(f"reuse_{spec.reuse_expectation.value}")
            if spec.freshness_sensitive:
                tags.append("freshness_sensitive")
        tags.append(handling_mode.value)
        return tuple(tags)

    def _missing_source_rationale(self, spec: IndicatorQuerySpec | None) -> str:
        if spec is not None and spec.structured_data and spec.reuse_expectation != ReuseExpectation.LOW:
            return "Known reusable dataset, but no approved source has been mapped yet."
        return "No candidate source identified yet for this run-scoped data need."

    def _missing_source_retention_target(self, spec: IndicatorQuerySpec | None) -> str:
        if spec is not None and spec.structured_data and spec.reuse_expectation != ReuseExpectation.LOW:
            return spec.retention_target_on_acquire
        return "ephemeral"

    def _missing_source_requires_review(self, spec: IndicatorQuerySpec | None) -> bool:
        return bool(
            spec is not None
            and spec.structured_data
            and spec.reuse_expectation != ReuseExpectation.LOW
        )

    def _missing_source_reason_tags(self, spec: IndicatorQuerySpec | None) -> tuple[str, ...]:
        handling_mode = self._deferred_handling_mode(spec)
        tags = ["no_source_mapping", handling_mode.value]
        if spec is not None:
            if spec.structured_data:
                tags.append("structured_dataset")
            tags.append(f"reuse_{spec.reuse_expectation.value}")
            if spec.freshness_sensitive:
                tags.append("freshness_sensitive")
        if handling_mode == DataHandlingMode.ACQUIRE_AND_STORE:
            tags.append("human_review_required")
        return tuple(tags)
