"""MethodRunner that coordinates tests through Oikonomia.

Episto does not import Arithmos here. Oikonomia owns run records and
adapter execution. Deployment/publication state is never treated as
epistemic support.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sophia_episto.research.contracts import (
    EmpiricalResult,
    InputSnapshot,
    MethodCapability,
    QuestionType,
    ResultStatus,
)
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode
from sophia_episto.research.runners import GRANGER_METHOD, GRANGER_VERSION

GRANGER_MODEL_ID = "episto-granger-predictive"


class OikonomiaMethodRunner:
    def __init__(self, db_path: Path) -> None:
        from sophia_oikonomia.adapters import (
            HYPOTHESIS_TEST_ADAPTER_ID,
            AdapterRegistry,
            HypothesisTestAdapter,
        )
        from sophia_oikonomia.core.runtime import OikonomiaRuntime
        from sophia_oikonomia.core.store import OikonomiaStore
        from sophia_oikonomia.core.types import (
            ExecutionSpec,
            ModelDefinition,
            ModelFamily,
            ModelState,
        )

        adapters = AdapterRegistry()
        adapters.register(HYPOTHESIS_TEST_ADAPTER_ID, HypothesisTestAdapter())
        self.runtime = OikonomiaRuntime(
            store=OikonomiaStore(Path(db_path)),
            adapters=adapters,
        )
        if self.runtime.get_model(GRANGER_MODEL_ID) is None:
            self.runtime.register_model(
                ModelDefinition(
                    id=GRANGER_MODEL_ID,
                    name="Episto Granger predictive test",
                    family=ModelFamily.MACRO,
                    owner="episto",
                    description=(
                        "Coordinates predictive Granger tests for research cases. "
                        "Success is not publication eligibility or causal identification."
                    ),
                    state=ModelState.RESEARCH,
                    execution=ExecutionSpec(adapter_id=HYPOTHESIS_TEST_ADAPTER_ID),
                    metadata={"epistemic_support": False},
                )
            )

    def capabilities(self) -> list[MethodCapability]:
        arithmos_ok = _arithmos_importable()
        return [
            MethodCapability(
                name=GRANGER_METHOD,
                available=arithmos_ok,
                question_types=[QuestionType.PREDICTIVE, QuestionType.ASSOCIATION],
                required_inputs=[
                    "source_observations",
                    "target_observations",
                    "vintage",
                    "dated_window",
                ],
                notes=(
                    "Executed through Oikonomia. Predictive only; not an "
                    "intervention or identified causal effect."
                ),
            )
        ]

    def run(
        self,
        *,
        run_id: str,
        case_id: str,
        hypothesis_id: str | None,
        fingerprint: str,
        method: str,
        question_type: QuestionType,
        snapshot: InputSnapshot,
    ) -> EmpiricalResult:
        from sophia_oikonomia.core.types import ModelTrigger, TriggerType

        if question_type in {
            QuestionType.INTERVENTION,
            QuestionType.COUNTERFACTUAL,
            QuestionType.IDENTIFIED_CAUSAL,
        }:
            raise ProtocolError(
                ProtocolErrorCode.UNSUPPORTED_QUESTION,
                "Oikonomia hypothesis-test coordination cannot answer "
                "intervention or counterfactual questions",
                details={
                    "method": method,
                    "question_type": question_type.value,
                    "missing": [
                        "identified_causal_model",
                        "intervention_mechanism",
                        "confounder_adjustment",
                    ],
                },
            )

        as_of = datetime.now(UTC)
        if snapshot.as_of:
            as_of = datetime.fromisoformat(snapshot.as_of.replace("Z", "+00:00"))
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=UTC)

        trigger = ModelTrigger(
            trigger_type=TriggerType.HYPOTHESIS,
            as_of=as_of,
            reason=f"{method}:{case_id}",
            model_ids=[GRANGER_MODEL_ID],
            payload={
                "fingerprint": fingerprint,
                "method": method,
                "question_type": question_type.value,
                "case_id": case_id,
                "hypothesis_id": hypothesis_id,
                "episto_run_id": run_id,
                "as_of": as_of.isoformat(),
                "input": snapshot.model_dump(mode="json"),
            },
        )
        coordinated = self.runtime.create_run(
            GRANGER_MODEL_ID,
            trigger,
            requested_by=f"case:{case_id}",
            fingerprint=fingerprint,
        )
        executed = self.runtime.execute_run(coordinated.id)
        return _empirical_from_oikonomia(
            executed,
            run_id=run_id,
            case_id=case_id,
            hypothesis_id=hypothesis_id,
            fingerprint=fingerprint,
            snapshot=snapshot,
            method=method,
        )


def _empirical_from_oikonomia(
    run: object,
    *,
    run_id: str,
    case_id: str,
    hypothesis_id: str | None,
    fingerprint: str,
    snapshot: InputSnapshot,
    method: str,
) -> EmpiricalResult:
    from sophia_oikonomia.core.types import ModelRun, RunStatus

    assert isinstance(run, ModelRun)
    summary = dict(run.output_summary or {})
    status_raw = str(summary.get("status") or run.status.value)
    if run.status == RunStatus.SUCCEEDED:
        status = ResultStatus.SUCCEEDED
    elif status_raw == "unavailable":
        status = ResultStatus.UNAVAILABLE
    else:
        status = ResultStatus.FAILED
    diagnostics = dict(summary.get("diagnostics") or {})
    diagnostics["oikonomia_run_id"] = run.id
    diagnostics["oikonomia_model_state"] = "research"
    return EmpiricalResult(
        run_id=run_id,
        case_id=case_id,
        hypothesis_id=hypothesis_id,
        fingerprint=fingerprint,
        method=str(summary.get("method") or method),
        method_version=str(summary.get("method_version") or GRANGER_VERSION),
        question_type=QuestionType(
            summary.get("question_type") or QuestionType.PREDICTIVE.value
        ),
        estimand=str(summary.get("estimand") or "predictive_granger"),
        status=status,
        input_snapshot=snapshot,
        estimate=summary.get("estimate"),
        diagnostics=diagnostics,
        assumptions=list(summary.get("assumptions") or []),
        failures=list(summary.get("failures") or ([run.error] if run.error else [])),
        scope_limitations=list(summary.get("scope_limitations") or []),
        identification_resolved=bool(summary.get("identification_resolved", False)),
    )


def _arithmos_importable() -> bool:
    try:
        from sophia_arithmos.computations.causality import GrangerCausality  # noqa: F401
    except ImportError:
        return False
    return True
