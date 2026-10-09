"""Scripted research agenda owned by the outside agent.

Sophia records the case. This module chooses the question, maps claims,
proposes competing mechanisms, and requests a supported test. It does not
store a transcript; a second client resumes from case and run IDs.
"""

from __future__ import annotations

from typing import Any

from outside_research_agent.sophia import SophiaCli, SophiaProtocolError


PROTOCOL_VERSION = "1"
QUESTION = (
    "Does an inflation surprise change the expected US policy path "
    "over the next four quarters?"
)
SCOPE = {
    "jurisdiction": "US",
    "measure": "core CPI surprise vs Bloomberg consensus",
    "surprise_baseline": "Bloomberg survey median",
    "horizon": "4 quarters",
    "competing_explanations": ["weaker growth lowering yields"],
}
INFLATION = {
    "variable_id": "inflation_surprise",
    "definition": "Core CPI monthly surprise versus survey median",
    "units": "percentage_points",
    "geography": "US",
    "frequency": "monthly",
}
POLICY = {
    "variable_id": "policy_path",
    "definition": "Four-quarter expected policy rate implied by OIS",
    "units": "percentage_points",
    "geography": "US",
    "frequency": "monthly",
}


def run_case(
    sophia: SophiaCli,
    *,
    actor: str,
    claims: list[dict[str, Any]],
    observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capabilities = sophia.invoke("capabilities", {})
    opened = sophia.invoke(
        "open_case",
        {
            "protocol_version": PROTOCOL_VERSION,
            "actor": actor,
            "question": QUESTION,
            "scope": SCOPE,
            "idempotency_key": f"{actor}:open",
        },
    )
    evidence = sophia.invoke(
        "submit_evidence",
        {
            "protocol_version": PROTOCOL_VERSION,
            "actor": actor,
            "case_id": opened["case_id"],
            "expected_revision": opened["revision"],
            "idempotency_key": f"{actor}:evidence",
            "claims": claims,
        },
    )
    reaction = _propose(
        sophia,
        actor=actor,
        case_id=opened["case_id"],
        revision=evidence["revision"],
        channel="reaction_function",
        sign="positive",
        key=f"{actor}:hyp-reaction",
        rationale="Inflation surprise raises the expected policy path via the reaction function.",
    )
    growth = _propose(
        sophia,
        actor=actor,
        case_id=opened["case_id"],
        revision=reaction["revision"],
        channel="growth_channel",
        sign="negative",
        key=f"{actor}:hyp-growth",
        rationale="The same surprise can be a growth shock that lowers yields.",
    )
    test = _request_test(
        sophia,
        capabilities=capabilities,
        actor=actor,
        case_id=opened["case_id"],
        revision=growth["revision"],
        hypothesis_id=reaction["hypothesis"]["hypothesis_id"],
        observations=observations,
    )
    cited_results = []
    revision = growth["revision"]
    result = test.get("result") or {}
    result_status = str(result.get("status") or "")
    pending = bool(test.get("pending")) or result_status in {"queued", "running"}
    if result and not pending:
        cited_results = [result["run_id"]]
        revision = test.get("revision", revision)
    assessment = sophia.invoke(
        "propose_assessment",
        {
            "protocol_version": PROTOCOL_VERSION,
            "actor": actor,
            "case_id": opened["case_id"],
            "expected_revision": revision,
            "idempotency_key": f"{actor}:assess-reaction",
            "hypothesis_id": reaction["hypothesis"]["hypothesis_id"],
            "cited_evidence_ids": evidence.get("contribution_ids") or [],
            "cited_result_ids": cited_results,
            "requested_uses": ["explain", "predict", "intervene"],
            "rationale": (
                "Predictive association may be useful; identification is unresolved "
                "so intervention remains disallowed."
            ),
        },
    )
    explanation = sophia.invoke("explain_case", {"case_id": opened["case_id"]})
    return {
        "case_id": opened["case_id"],
        "capabilities": capabilities,
        "evidence": evidence,
        "hypotheses": [reaction, growth],
        "test": test,
        "assessment": assessment,
        "explanation": explanation,
    }


def resume_case(sophia: SophiaCli, *, case_id: str) -> dict[str, Any]:
    case = sophia.invoke("get_case", {"case_id": case_id})
    explanation = sophia.invoke("explain_case", {"case_id": case_id})
    runs = []
    for item in explanation.get("computed_results") or []:
        run_id = item.get("run_id")
        if run_id:
            runs.append(sophia.invoke("get_run", {"run_id": run_id}))
    return {"case": case, "explanation": explanation, "runs": runs}


def _propose(
    sophia: SophiaCli,
    *,
    actor: str,
    case_id: str,
    revision: int,
    channel: str,
    sign: str,
    key: str,
    rationale: str,
) -> dict[str, Any]:
    return sophia.invoke(
        "propose_hypothesis",
        {
            "protocol_version": PROTOCOL_VERSION,
            "actor": actor,
            "case_id": case_id,
            "expected_revision": revision,
            "idempotency_key": key,
            "cause": INFLATION,
            "effect": POLICY,
            "channel": channel,
            "sign": sign,
            "lag": "0-2 meetings",
            "alternatives": ["growth_channel", "reaction_function"],
            "falsifiers": ["surprise with no path move after two meetings"],
            "rationale": rationale,
        },
    )


def _request_test(
    sophia: SophiaCli,
    *,
    capabilities: dict[str, Any],
    actor: str,
    case_id: str,
    revision: int,
    hypothesis_id: str,
    observations: dict[str, Any] | None,
) -> dict[str, Any]:
    methods = {item.get("name"): item for item in capabilities.get("methods") or []}
    granger = methods.get("granger_predictive") or {}
    if not granger.get("available"):
        return {
            "skipped": True,
            "reason": "method_unavailable",
            "result": None,
        }
    if not observations:
        return {
            "skipped": True,
            "reason": "observations_not_provided",
            "result": None,
        }
    try:
        return sophia.invoke(
            "request_test",
            {
                "protocol_version": PROTOCOL_VERSION,
                "actor": actor,
                "case_id": case_id,
                "expected_revision": revision,
                "idempotency_key": f"{actor}:test-v1",
                "hypothesis_id": hypothesis_id,
                "method": "granger_predictive",
                "question_type": "predictive",
                "input": observations,
            },
        )
    except SophiaProtocolError as exc:
        if exc.code == "method_unavailable":
            return {
                "skipped": True,
                "reason": "method_unavailable",
                "error": exc.payload,
                "result": None,
            }
        raise
