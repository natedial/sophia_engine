"""Engine-owned promotion and permitted-use rules.

An agent proposal is recorded as authored judgment. Schema-valid prose does
not become a verified causal fact.
"""

from __future__ import annotations

from sophia_episto.research.contracts import (
    PROTOCOL_VERSION,
    AllowedUse,
    EmpiricalResult,
    EvidenceAssessment,
    HypothesisAssessment,
    HypothesisRecordStatus,
    ProvenanceStatus,
    QuestionType,
    ResultStatus,
)


CAUSAL_USES = {AllowedUse.INTERVENE, AllowedUse.COUNTERFACTUAL}


def apply_assessment_policy(
    *,
    hypothesis_id: str,
    case_id: str,
    current: HypothesisAssessment | None,
    cited_evidence: list[EvidenceAssessment],
    cited_results: list[EmpiricalResult],
    requested_uses: list[AllowedUse],
    missing_evidence_ids: list[str],
    missing_result_ids: list[str],
    alternatives: list[str],
) -> HypothesisAssessment:
    unmet: list[str] = []
    limitations: list[str] = []
    allowed: list[AllowedUse] = []

    if missing_evidence_ids or missing_result_ids:
        unmet.append("cited_records_not_found")
        return _build(
            hypothesis_id,
            case_id,
            current,
            HypothesisRecordStatus.UNMET_REQUIREMENTS,
            cited_evidence,
            cited_results,
            allowed,
            unmet,
            limitations,
            alternatives,
        )

    bound_evidence = [
        item for item in cited_evidence if _evidence_bound(item, case_id, hypothesis_id)
    ]
    bound_results = [
        item for item in cited_results if _result_bound(item, case_id, hypothesis_id)
    ]
    if len(bound_evidence) != len(cited_evidence) or len(bound_results) != len(
        cited_results
    ):
        unmet.append("cited_records_not_bound")
        return _build(
            hypothesis_id,
            case_id,
            current,
            HypothesisRecordStatus.UNMET_REQUIREMENTS,
            bound_evidence,
            bound_results,
            allowed,
            unmet,
            limitations,
            alternatives,
        )

    cited_evidence = bound_evidence
    cited_results = bound_results

    if not cited_evidence and not cited_results:
        unmet.append("evidence_or_result_required")
        return _build(
            hypothesis_id,
            case_id,
            current,
            HypothesisRecordStatus.UNMET_REQUIREMENTS,
            cited_evidence,
            cited_results,
            allowed,
            unmet,
            limitations,
            alternatives,
        )

    verified = [
        item
        for item in cited_evidence
        if item.provenance_status == ProvenanceStatus.VERIFIED
    ]
    unverified = [
        item
        for item in cited_evidence
        if item.provenance_status != ProvenanceStatus.VERIFIED
    ]
    if unverified:
        limitations.append("unverified_or_invalid_source_provenance")

    succeeded = [item for item in cited_results if item.status == ResultStatus.SUCCEEDED]
    failed = [
        item
        for item in cited_results
        if item.status in {ResultStatus.FAILED, ResultStatus.UNAVAILABLE}
    ]
    if failed:
        limitations.append("cited_run_failed_or_unavailable")

    identified = [
        item
        for item in succeeded
        if item.identification_resolved
        or item.question_type == QuestionType.IDENTIFIED_CAUSAL
    ]
    predictive = [
        item
        for item in succeeded
        if item.question_type in {QuestionType.PREDICTIVE, QuestionType.ASSOCIATION}
        and not item.identification_resolved
    ]

    if verified:
        allowed.append(AllowedUse.EXPLAIN)
    if predictive or identified:
        if AllowedUse.EXPLAIN not in allowed:
            allowed.append(AllowedUse.EXPLAIN)
        allowed.append(AllowedUse.PREDICT)
    if identified:
        allowed.extend([AllowedUse.INTERVENE, AllowedUse.COUNTERFACTUAL])

    requested_causal = [use for use in requested_uses if use in CAUSAL_USES]
    if requested_causal and not identified:
        unmet.append("causal_identification_unresolved")
        limitations.append("predictive_or_qualitative_result_is_not_an_intervention")

    if not allowed and unverified and not succeeded:
        unmet.append("verified_source_or_result_required")

    status = HypothesisRecordStatus.USEFUL_BOUNDED if allowed else (
        HypothesisRecordStatus.UNMET_REQUIREMENTS
    )
    if failed and not succeeded and not verified:
        status = HypothesisRecordStatus.FAILED
        if ResultStatus.UNAVAILABLE in {item.status for item in failed}:
            status = HypothesisRecordStatus.UNAVAILABLE

    return _build(
        hypothesis_id,
        case_id,
        current,
        status,
        cited_evidence,
        cited_results,
        allowed,
        unmet,
        limitations,
        alternatives,
    )


def _evidence_bound(
    item: EvidenceAssessment, case_id: str, hypothesis_id: str
) -> bool:
    if item.case_id != case_id:
        return False
    return item.hypothesis_id in {None, hypothesis_id}


def _result_bound(item: EmpiricalResult, case_id: str, hypothesis_id: str) -> bool:
    return item.case_id == case_id and item.hypothesis_id == hypothesis_id


def _build(
    hypothesis_id: str,
    case_id: str,
    current: HypothesisAssessment | None,
    status: HypothesisRecordStatus,
    cited_evidence: list[EvidenceAssessment],
    cited_results: list[EmpiricalResult],
    allowed: list[AllowedUse],
    unmet: list[str],
    limitations: list[str],
    alternatives: list[str],
) -> HypothesisAssessment:
    revision = (current.revision + 1) if current else 1
    unique_allowed = list(dict.fromkeys(allowed))
    return HypothesisAssessment(
        hypothesis_id=hypothesis_id,
        case_id=case_id,
        status=status,
        contributing_evidence_ids=[item.contribution_id for item in cited_evidence],
        contributing_result_ids=[item.run_id for item in cited_results],
        contributing_proposal_ids=list(current.contributing_proposal_ids) if current else [],
        unresolved_alternatives=alternatives,
        allowed_uses=unique_allowed,
        unmet_requirements=unmet,
        limitations=limitations,
        policy_version=PROTOCOL_VERSION,
        revision=revision,
    )
