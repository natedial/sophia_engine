"""Import legacy graph.json edges as unassessed mechanism candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sophia_episto.research.contracts import (
    HypothesisAssessment,
    HypothesisRecordStatus,
    MechanismHypothesis,
    Sign,
    VariableSpec,
)


def import_legacy_graph(
    engine: Any,
    graph: dict[str, Any],
    *,
    actor: str = "legacy-import",
    question: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Load old (source, target) edges without promoting their scores."""
    if case_id:
        case = engine.ledger.require_case(case_id)
    else:
        opened = engine.open_case(
            {
                "protocol_version": "1",
                "actor": actor,
                "question": question
                or "Legacy causal graph import; scores are metadata only",
            }
        )
        case_id = opened["case_id"]
        case = engine.ledger.require_case(case_id)

    imported: list[str] = []
    for edge in graph.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if not source or not target:
            continue
        cause = VariableSpec(variable_id=source, definition=f"Legacy node label {source}")
        effect = VariableSpec(variable_id=target, definition=f"Legacy node label {target}")
        hypothesis = MechanismHypothesis(
            hypothesis_id=f"hyp-legacy-{uuid4().hex[:12]}",
            revision=1,
            case_id=case_id,
            cause_variable_id=source,
            effect_variable_id=target,
            channel=edge.get("mechanism") or "legacy_unassessed",
            sign=Sign.UNKNOWN,
            conditions=edge.get("conditions") or {},
            submitting_actor=actor,
            rationale="Imported from graph.json; not an assessed mechanism.",
        )
        assessment = HypothesisAssessment(
            hypothesis_id=hypothesis.hypothesis_id,
            case_id=case_id,
            status=HypothesisRecordStatus.LEGACY_UNASSESSED,
            limitations=[
                "legacy_graph_import",
                "scores_are_metadata_not_support",
            ],
            applicability="not_promoted",
        )
        case = engine.ledger.require_case(case_id)
        engine.ledger.transact_hypothesis(
            case,
            idempotency_key=f"legacy-{hypothesis.hypothesis_id}",
            hypothesis=hypothesis,
            assessment=assessment,
            variables=[cause, effect],
        )
        case = engine.ledger.require_case(case_id)
        extra = dict(case.scope.extra)
        scores = list(extra.get("legacy_scores", []))
        scores.append(
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "legacy_source": source,
                "legacy_target": target,
                "legacy_probability": edge.get("probability"),
                "legacy_confidence": edge.get("confidence"),
                "legacy_strength": edge.get("strength"),
                "imported_at": datetime.now(UTC).isoformat(),
            }
        )
        extra["legacy_scores"] = scores
        engine.ledger.save_case(
            case.model_copy(
                update={
                    "scope": case.scope.model_copy(update={"extra": extra}),
                    "unresolved_questions": [
                        *case.unresolved_questions,
                        f"Assess imported {source}→{target} ({hypothesis.hypothesis_id})",
                    ],
                    "artifact_ids": [
                        *case.artifact_ids,
                        f"legacy:{hypothesis.hypothesis_id}",
                    ],
                }
            )
        )
        imported.append(hypothesis.hypothesis_id)

    case = engine.ledger.require_case(case_id)
    return {
        "case_id": case.case_id,
        "revision": case.revision,
        "hypothesis_ids": imported,
        "status": "legacy_unassessed",
        "promoted": False,
    }
