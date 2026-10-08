"""Outside-agent research protocol handlers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from sophia_episto.research.contracts import (
    PROTOCOL_VERSION,
    AgentProposal,
    AllowedUse,
    Capabilities,
    CaseScope,
    EmpiricalResult,
    EvidenceAssessment,
    EvidenceKind,
    HypothesisAssessment,
    HypothesisRecordStatus,
    InputSnapshot,
    MechanismHypothesis,
    QuestionType,
    ResearchCase,
    Sign,
    SourceClaimRef,
    Stance,
    VariableSpec,
)
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode
from sophia_episto.research.ledger import ResearchLedger
from sophia_episto.research.policy import apply_assessment_policy
from sophia_episto.research.runners import (
    GRANGER_METHOD,
    MethodRunner,
    default_runner,
)


class ResearchEngine:
    def __init__(
        self,
        db_path: Path,
        *,
        runner: MethodRunner | None = None,
    ) -> None:
        self.ledger = ResearchLedger(db_path)
        self.runner = runner or default_runner()

    def dispatch(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "capabilities": self.capabilities,
            "open_case": self.open_case,
            "get_case": self.get_case,
            "submit_evidence": self.submit_evidence,
            "propose_hypothesis": self.propose_hypothesis,
            "request_test": self.request_test,
            "get_run": self.get_run,
            "propose_assessment": self.propose_assessment,
            "explain_case": self.explain_case,
        }
        handler = handlers.get(operation)
        if handler is None:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                f"Unknown operation: {operation}",
            )
        try:
            return handler(payload)
        except ProtocolError:
            raise
        except ValidationError as exc:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "Payload failed contract validation",
                details={"errors": exc.errors()},
            ) from exc

    def capabilities(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        methods = self.runner.capabilities()
        optional_missing = [
            "dowhy_refutation",
            "pc_discovery",
            "identified_causal_estimator",
        ]
        permitted = [
            QuestionType.PREDICTIVE,
            QuestionType.ASSOCIATION,
        ]
        return Capabilities(
            methods=methods,
            unavailable_optional=optional_missing,
            permitted_question_types=permitted,
        ).model_dump(mode="json")

    def open_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_protocol(payload)
        actor = self._require_actor(payload)
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "question is required",
            )
        idempotency_key = payload.get("idempotency_key")
        if idempotency_key:
            existing = self.ledger.get_idempotent("global", str(idempotency_key))
            if existing is not None:
                return existing
        now = datetime.now(UTC)
        scope = payload.get("scope") or {}
        case = ResearchCase(
            case_id=f"case-{uuid4().hex[:12]}",
            revision=1,
            question=question,
            scope=CaseScope.model_validate(scope) if scope else CaseScope(),
            submitting_actor=actor,
            created_at=now,
            updated_at=now,
            unresolved_questions=list(payload.get("unresolved_questions") or []),
        )
        self.ledger.save_case(case)
        response = {
            "case_id": case.case_id,
            "revision": case.revision,
            "question": case.question,
            "scope": case.scope.model_dump(mode="json"),
        }
        if idempotency_key:
            with self.ledger._connect() as conn:
                self.ledger.put_idempotent(
                    conn, "global", str(idempotency_key), "open_case", response
                )
        return response

    def get_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_id = str(payload.get("case_id") or "")
        case = self.ledger.require_case(case_id)
        return self._case_snapshot(case, as_of_vintage=payload.get("as_of_vintage"))

    def submit_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_protocol(payload)
        actor = self._require_actor(payload)
        case, idempotency_key, replay = self._mutation_prelude(payload)
        if replay is not None:
            return replay

        claims_raw = payload.get("claims")
        if not isinstance(claims_raw, list) or not claims_raw:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "claims must be a non-empty list",
            )

        new_items: list[EvidenceAssessment] = []
        existing_ids: list[str] = []
        groups: list[str] = []
        now = datetime.now(UTC)
        for raw in claims_raw:
            claim = SourceClaimRef.model_validate(raw)
            contribution_id = _contribution_id(claim)
            status = claim.provenance_status()
            group = claim.independence_group or claim.snapshot_hash or claim.document_revision or contribution_id
            groups.append(group)
            existing = self.ledger.get_contribution(contribution_id)
            if existing is not None:
                existing_ids.append(contribution_id)
                continue
            new_items.append(
                EvidenceAssessment(
                    contribution_id=contribution_id,
                    case_id=case.case_id,
                    evidence_kind=EvidenceKind.SOURCE_CLAIM,
                    stance=Stance.NON_DIAGNOSTIC,
                    independence_group=group,
                    provenance_status=status,
                    justification=f"Submitted by {actor}",
                    provenance=claim,
                    assessed_at=now,
                    event_time=claim.published_at,
                    known_as_of=claim.captured_at or now,
                )
            )
        return self.ledger.transact_evidence(
            case,
            idempotency_key=idempotency_key,
            new_contributions=new_items,
            existing_ids=existing_ids,
            independence_groups=groups,
        )

    def propose_hypothesis(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_protocol(payload)
        actor = self._require_actor(payload)
        case, idempotency_key, replay = self._mutation_prelude(payload)
        if replay is not None:
            return replay

        cause = _variable_from_payload(payload.get("cause") or payload.get("cause_variable"))
        effect = _variable_from_payload(payload.get("effect") or payload.get("effect_variable"))
        if cause is None or effect is None:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "cause and effect variable specs are required",
            )
        sign_raw = payload.get("sign", Sign.UNKNOWN.value)
        hypothesis = MechanismHypothesis(
            hypothesis_id=f"hyp-{uuid4().hex[:12]}",
            revision=1,
            case_id=case.case_id,
            cause_variable_id=cause.variable_id,
            effect_variable_id=effect.variable_id,
            channel=str(payload.get("channel") or "unspecified"),
            sign=Sign(sign_raw),
            lag=payload.get("lag"),
            conditions=payload.get("conditions") or {},
            alternatives=list(payload.get("alternatives") or []),
            source_claim_ids=list(payload.get("evidence_ids") or []),
            expected_observations=list(payload.get("expected_observations") or []),
            falsifiers=list(payload.get("falsifiers") or []),
            submitting_actor=actor,
            rationale=str(payload.get("rationale") or ""),
        )
        assessment = HypothesisAssessment(
            hypothesis_id=hypothesis.hypothesis_id,
            case_id=case.case_id,
            status=HypothesisRecordStatus.CANDIDATE,
            contributing_evidence_ids=hypothesis.source_claim_ids,
            unresolved_alternatives=hypothesis.alternatives,
            allowed_uses=[],
            unmet_requirements=["engine_assessment_not_requested"],
            limitations=["agent_authored_candidate_not_a_causal_fact"],
        )
        return self.ledger.transact_hypothesis(
            case,
            idempotency_key=idempotency_key,
            hypothesis=hypothesis,
            assessment=assessment,
            variables=[cause, effect],
        )

    def request_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_protocol(payload)
        self._require_actor(payload)
        case, idempotency_key, replay = self._mutation_prelude(payload)
        if replay is not None:
            return replay

        method = str(payload.get("method") or GRANGER_METHOD)
        question_type = QuestionType(payload.get("question_type") or QuestionType.PREDICTIVE)
        snapshot = InputSnapshot.model_validate(payload.get("input") or {})
        hypothesis_id = payload.get("hypothesis_id")
        if hypothesis_id and self.ledger.get_hypothesis(str(hypothesis_id)) is None:
            raise ProtocolError(
                ProtocolErrorCode.NOT_FOUND,
                f"Unknown hypothesis: {hypothesis_id}",
            )

        available = {item.name: item for item in self.runner.capabilities()}
        capability = available.get(method)
        if capability is None or not capability.available:
            raise ProtocolError(
                ProtocolErrorCode.METHOD_UNAVAILABLE,
                f"Method is not available: {method}",
                details={"method": method},
            )

        fingerprint = _run_fingerprint(method, snapshot, hypothesis_id)
        existing = self.ledger.get_result_by_fingerprint(fingerprint)
        if existing is not None:
            response = {
                "case_id": case.case_id,
                "revision": case.revision,
                "result": existing.model_dump(mode="json"),
                "replayed": True,
            }
            with self.ledger._lock, self.ledger._connect() as conn:
                self.ledger.put_idempotent(
                    conn, case.case_id, idempotency_key, "request_test", response
                )
            return response

        run_id = f"run-{uuid4().hex[:12]}"
        result = self.runner.run(
            run_id=run_id,
            case_id=case.case_id,
            hypothesis_id=str(hypothesis_id) if hypothesis_id else None,
            fingerprint=fingerprint,
            method=method,
            question_type=question_type,
            snapshot=snapshot,
        )
        return self.ledger.transact_result(
            case,
            idempotency_key=idempotency_key,
            result=result,
        )

    def get_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = str(payload.get("run_id") or "")
        result = self.ledger.get_result(run_id)
        if result is None:
            raise ProtocolError(ProtocolErrorCode.NOT_FOUND, f"Unknown run: {run_id}")
        return {"result": result.model_dump(mode="json")}

    def propose_assessment(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_protocol(payload)
        actor = self._require_actor(payload)
        case, idempotency_key, replay = self._mutation_prelude(payload)
        if replay is not None:
            return replay

        hypothesis_id = str(payload.get("hypothesis_id") or "")
        hypothesis = self.ledger.get_hypothesis(hypothesis_id)
        if hypothesis is None:
            raise ProtocolError(
                ProtocolErrorCode.NOT_FOUND,
                f"Unknown hypothesis: {hypothesis_id}",
            )

        cited_evidence_ids = [str(item) for item in payload.get("cited_evidence_ids") or []]
        cited_result_ids = [str(item) for item in payload.get("cited_result_ids") or []]
        requested_uses = [
            AllowedUse(item) for item in payload.get("requested_uses") or []
        ]
        cited_evidence: list[EvidenceAssessment] = []
        missing_evidence: list[str] = []
        for contribution_id in cited_evidence_ids:
            item = self.ledger.get_contribution(contribution_id)
            if item is None:
                missing_evidence.append(contribution_id)
            else:
                cited_evidence.append(item)
        cited_results: list[EmpiricalResult] = []
        missing_results: list[str] = []
        for run_id in cited_result_ids:
            item = self.ledger.get_result(run_id)
            if item is None:
                missing_results.append(run_id)
            else:
                cited_results.append(item)

        current = self.ledger.get_assessment(hypothesis_id)
        assessment = apply_assessment_policy(
            hypothesis_id=hypothesis_id,
            case_id=case.case_id,
            current=current,
            cited_evidence=cited_evidence,
            cited_results=cited_results,
            requested_uses=requested_uses,
            missing_evidence_ids=missing_evidence,
            missing_result_ids=missing_results,
            alternatives=hypothesis.alternatives,
        )
        proposal = AgentProposal(
            proposal_id=f"prop-{uuid4().hex[:12]}",
            case_id=case.case_id,
            hypothesis_id=hypothesis_id,
            case_revision=case.revision,
            submitting_actor=actor,
            kind="interpretation",
            cited_evidence_ids=cited_evidence_ids,
            cited_result_ids=cited_result_ids,
            requested_uses=requested_uses,
            assumptions=list(payload.get("assumptions") or []),
            rationale=str(payload.get("rationale") or ""),
        )
        return self.ledger.transact_assessment(
            case,
            idempotency_key=idempotency_key,
            proposal=proposal,
            assessment=assessment,
        )

    def explain_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_id = str(payload.get("case_id") or "")
        case = self.ledger.require_case(case_id)
        return self._case_snapshot(case, as_of_vintage=payload.get("as_of_vintage"))

    def _case_snapshot(
        self, case: ResearchCase, *, as_of_vintage: str | None
    ) -> dict[str, Any]:
        hypotheses = self.ledger.list_hypotheses(case.case_id)
        assessments = {
            item.hypothesis_id: item
            for item in self.ledger.list_assessments(case.case_id)
        }
        results = self.ledger.list_results(case.case_id)
        if as_of_vintage:
            results = [
                item
                for item in results
                if item.input_snapshot.vintage == as_of_vintage
            ]
        evidence = self.ledger.list_contributions(case.case_id)
        proposals = self.ledger.list_proposals(case.case_id)
        return {
            "case_id": case.case_id,
            "revision": case.revision,
            "question": case.question,
            "scope": case.scope.model_dump(mode="json"),
            "submitting_actor": case.submitting_actor,
            "decisions": case.decisions,
            "unresolved_questions": case.unresolved_questions,
            "source_claims": [
                {
                    "contribution_id": item.contribution_id,
                    "independence_group": item.independence_group,
                    "provenance_status": item.provenance_status.value,
                    "kind": "source_statement",
                    "claim": item.provenance.model_dump(mode="json")
                    if item.provenance
                    else None,
                }
                for item in evidence
            ],
            "hypotheses": [
                {
                    **item.model_dump(mode="json"),
                    "assessment": assessments[item.hypothesis_id].model_dump(mode="json")
                    if item.hypothesis_id in assessments
                    else None,
                }
                for item in hypotheses
            ],
            "computed_results": [
                {
                    "kind": "computed_result",
                    **item.model_dump(mode="json"),
                }
                for item in results
            ],
            "agent_interpretations": [
                {
                    "kind": "agent_interpretation",
                    **item.model_dump(mode="json"),
                }
                for item in proposals
            ],
            "open_questions": case.unresolved_questions,
            "pending_runs": [],
            "as_of_vintage": as_of_vintage,
        }

    def _mutation_prelude(
        self, payload: dict[str, Any]
    ) -> tuple[ResearchCase, str, dict[str, Any] | None]:
        case_id = str(payload.get("case_id") or "")
        case = self.ledger.require_case(case_id)
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "idempotency_key is required for mutations",
            )
        replay = self.ledger.get_idempotent(case.case_id, idempotency_key)
        if replay is not None:
            return case, idempotency_key, replay
        if "expected_revision" not in payload:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "expected_revision is required for mutations",
            )
        self.ledger.require_revision(case, int(payload["expected_revision"]))
        return case, idempotency_key, None

    def _require_protocol(self, payload: dict[str, Any]) -> None:
        version = str(payload.get("protocol_version") or "")
        if version != PROTOCOL_VERSION:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                f"Unsupported protocol_version: {version or 'missing'}",
                details={"supported": PROTOCOL_VERSION},
            )

    def _require_actor(self, payload: dict[str, Any]) -> str:
        actor = str(payload.get("actor") or "").strip()
        if not actor:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "actor is required",
            )
        return actor


def _variable_from_payload(raw: Any) -> VariableSpec | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return VariableSpec(variable_id=raw, definition=raw)
    if isinstance(raw, dict):
        if "variable_id" not in raw:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "variable_id is required; a concept label is not a measurement definition",
            )
        if not raw.get("definition"):
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "variable definition, not only a label, is required",
            )
        return VariableSpec.model_validate(raw)
    return None


def _contribution_id(claim: SourceClaimRef) -> str:
    material = "|".join(
        [
            claim.namespace,
            claim.occurrence_id,
            claim.snapshot_hash or "",
            claim.content_hash or "",
            claim.document_revision or "",
            ",".join(claim.locations),
        ]
    )
    return "ev-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _run_fingerprint(
    method: str, snapshot: InputSnapshot, hypothesis_id: str | None
) -> str:
    payload = {
        "method": method,
        "hypothesis_id": hypothesis_id,
        "snapshot": snapshot.model_dump(mode="json"),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return "fp-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]
