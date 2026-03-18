"""Runtime logic for Sophia Sentry watch evaluation."""

from datetime import UTC, datetime
from uuid import uuid4

from .store import SentryStore
from .types import (
    EventSeverity,
    ModelRevisionSpec,
    NumericThresholdSpec,
    PublicationUpdatePayload,
    WatchDefinition,
    WatchEvaluationRequest,
    WatchEvaluationResult,
    WatchEvent,
    WatchKind,
    WatchRuntimeState,
    WatchState,
)


class SentryRuntime:
    """Coordinates watch persistence and evaluation."""

    def __init__(self, store: SentryStore) -> None:
        self.store = store

    def register_watch(self, watch: WatchDefinition) -> WatchDefinition:
        """Persist a watch definition."""
        return self.store.upsert_watch(watch)

    def get_watch(self, watch_id: str) -> WatchDefinition | None:
        """Load a single watch definition."""
        return self.store.get_watch(watch_id)

    def list_watches(self) -> list[WatchDefinition]:
        """List registered watches."""
        return self.store.list_watches()

    def list_events(self, watch_id: str | None = None) -> list[WatchEvent]:
        """List materialized watch events."""
        return self.store.list_events(watch_id=watch_id)

    def evaluate_watch(
        self,
        watch_id: str,
        request: WatchEvaluationRequest,
    ) -> WatchEvaluationResult:
        """Evaluate one watch against the provided payload."""
        watch = self.store.get_watch(watch_id)
        if watch is None:
            raise KeyError(f"Unknown watch: {watch_id}")
        return self._evaluate(watch, request)

    def evaluate(self, request: WatchEvaluationRequest) -> list[WatchEvaluationResult]:
        """Evaluate a set of watches."""
        requested_ids = set(request.watch_ids)
        watches = self.store.list_watches()
        if requested_ids:
            watches = [watch for watch in watches if watch.id in requested_ids]
        else:
            watches = [watch for watch in watches if watch.state == WatchState.ENABLED]
        return [self._evaluate(watch, request) for watch in watches]

    def handle_publication_update(
        self,
        payload: PublicationUpdatePayload,
    ) -> list[WatchEvaluationResult]:
        """Evaluate all matching model revision watches for an Oikonomia publication."""
        matching_watch_ids: list[str] = []
        for watch in self.store.list_watches():
            if watch.state != WatchState.ENABLED or watch.kind != WatchKind.MODEL_REVISION:
                continue
            spec = ModelRevisionSpec.model_validate(watch.spec)
            if spec.production_slot == payload.production_slot:
                matching_watch_ids.append(watch.id)

        request = WatchEvaluationRequest(
            as_of=payload.published_at,
            source="model_trigger",
            watch_ids=matching_watch_ids,
            observations={
                "current_projection": payload.current_summary,
                "prior_projection": payload.prior_summary,
            },
            context={
                "model_id": payload.model_id,
                "production_slot": payload.production_slot,
                "as_of": payload.as_of.isoformat(),
                "insights": payload.insights,
            },
        )
        return self.evaluate(request)

    def _evaluate(
        self,
        watch: WatchDefinition,
        request: WatchEvaluationRequest,
    ) -> WatchEvaluationResult:
        if watch.state != WatchState.ENABLED:
            return WatchEvaluationResult(
                watch_id=watch.id,
                triggered=False,
                reason="watch_disabled",
            )

        state = self.store.get_state(watch.id) or WatchRuntimeState(watch_id=watch.id)

        if watch.kind == WatchKind.NUMERIC_THRESHOLD:
            result, next_state = self._evaluate_numeric_threshold(watch, state, request)
        elif watch.kind == WatchKind.MODEL_REVISION:
            result, next_state = self._evaluate_model_revision(watch, state, request)
        else:
            result = WatchEvaluationResult(
                watch_id=watch.id,
                triggered=False,
                reason=f"watch_kind_not_implemented:{watch.kind.value}",
            )
            next_state = state.model_copy(update={"last_evaluated_at": request.as_of})

        self.store.upsert_state(next_state)
        return result

    def _evaluate_numeric_threshold(
        self,
        watch: WatchDefinition,
        state: WatchRuntimeState,
        request: WatchEvaluationRequest,
    ) -> tuple[WatchEvaluationResult, WatchRuntimeState]:
        spec = NumericThresholdSpec.model_validate(watch.spec)
        current_value = request.observations.get(spec.signal_key)
        if current_value is None:
            next_state = state.model_copy(update={"last_evaluated_at": request.as_of})
            return (
                WatchEvaluationResult(
                    watch_id=watch.id,
                    triggered=False,
                    reason=f"missing_signal:{spec.signal_key}",
                ),
                next_state,
            )

        current = float(current_value)
        prior = state.last_value
        threshold_hit = False
        delta_hit = False

        if spec.threshold is not None:
            if spec.direction == "below":
                threshold_hit = current <= spec.threshold
            else:
                threshold_hit = current >= spec.threshold

        if spec.delta_threshold is not None and prior is not None:
            delta_hit = abs(current - prior) >= spec.delta_threshold

        triggered = threshold_hit or delta_hit
        severity = EventSeverity.WARNING if triggered else None
        summary = ""
        if threshold_hit and spec.threshold is not None:
            comparison = "below" if spec.direction == "below" else "above"
            summary = (
                f"{watch.name}: {spec.signal_key} moved {comparison} {spec.threshold:.4g} "
                f"(current {current:.4g})"
            )
        elif delta_hit and prior is not None and spec.delta_threshold is not None:
            summary = (
                f"{watch.name}: {spec.signal_key} changed by {current - prior:+.4g}, "
                f"breaching delta threshold {spec.delta_threshold:.4g}"
            )

        event_id = None
        if triggered:
            event_id = self._create_event(
                watch=watch,
                severity=severity or EventSeverity.WARNING,
                summary=summary,
                payload={
                    "signal_key": spec.signal_key,
                    "current_value": current,
                    "prior_value": prior,
                    "threshold": spec.threshold,
                    "delta_threshold": spec.delta_threshold,
                    "source": request.source.value,
                },
                created_at=request.as_of,
            ).id

        next_state = state.model_copy(
            update={
                "last_value": current,
                "last_evaluated_at": request.as_of,
                "last_triggered_at": request.as_of if triggered else state.last_triggered_at,
            }
        )
        reason = (
            "threshold_triggered"
            if threshold_hit
            else "delta_triggered"
            if delta_hit
            else "not_material"
        )
        return (
            WatchEvaluationResult(
                watch_id=watch.id,
                triggered=triggered,
                reason=reason,
                severity=severity,
                event_id=event_id,
                metrics={
                    "current_value": current,
                    "prior_value": prior,
                    "threshold_hit": threshold_hit,
                    "delta_hit": delta_hit,
                },
            ),
            next_state,
        )

    def _evaluate_model_revision(
        self,
        watch: WatchDefinition,
        state: WatchRuntimeState,
        request: WatchEvaluationRequest,
    ) -> tuple[WatchEvaluationResult, WatchRuntimeState]:
        spec = ModelRevisionSpec.model_validate(watch.spec)
        current_projection = request.observations.get("current_projection", {})
        prior_projection = request.observations.get("prior_projection", {})

        current_value = current_projection.get(spec.metric_key)
        prior_value = prior_projection.get(spec.metric_key)
        if current_value is None or prior_value is None:
            next_state = state.model_copy(update={"last_evaluated_at": request.as_of})
            return (
                WatchEvaluationResult(
                    watch_id=watch.id,
                    triggered=False,
                    reason=f"missing_projection_metric:{spec.metric_key}",
                ),
                next_state,
            )

        current = float(current_value)
        prior = float(prior_value)
        delta = current - prior
        triggered = abs(delta) >= spec.minimum_absolute_delta
        severity = EventSeverity.WARNING if triggered else None
        summary = (
            f"{watch.name}: {spec.metric_key} revised by {delta:+.4g} "
            f"for slot {spec.production_slot}"
        )

        event_id = None
        if triggered:
            event_id = self._create_event(
                watch=watch,
                severity=severity or EventSeverity.WARNING,
                summary=summary,
                payload={
                    "production_slot": spec.production_slot,
                    "metric_key": spec.metric_key,
                    "current_value": current,
                    "prior_value": prior,
                    "absolute_delta": delta,
                    "minimum_absolute_delta": spec.minimum_absolute_delta,
                    "source": request.source.value,
                },
                created_at=request.as_of,
            ).id

        next_state = state.model_copy(
            update={
                "last_value": current,
                "last_evaluated_at": request.as_of,
                "last_triggered_at": request.as_of if triggered else state.last_triggered_at,
                "metadata": {
                    **state.metadata,
                    "production_slot": spec.production_slot,
                    "metric_key": spec.metric_key,
                },
            }
        )
        return (
            WatchEvaluationResult(
                watch_id=watch.id,
                triggered=triggered,
                reason="revision_triggered" if triggered else "not_material",
                severity=severity,
                event_id=event_id,
                metrics={
                    "current_value": current,
                    "prior_value": prior,
                    "absolute_delta": delta,
                },
            ),
            next_state,
        )

    def _create_event(
        self,
        *,
        watch: WatchDefinition,
        severity: EventSeverity,
        summary: str,
        payload: dict[str, object],
        created_at: datetime,
    ) -> WatchEvent:
        event = WatchEvent(
            id=f"event-{uuid4().hex[:12]}",
            watch_id=watch.id,
            watch_name=watch.name,
            kind=watch.kind,
            severity=severity,
            summary=summary,
            payload=payload,
            delivery_channels=watch.delivery_channels,
            created_at=created_at.astimezone(UTC),
        )
        return self.store.create_event(event)
