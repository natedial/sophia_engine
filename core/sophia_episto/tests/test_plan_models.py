import pytest

from sophia_episto.capability import SearchBackedCapabilityResolver, StaticCapabilityResolver
from sophia_episto.plan_models import (
    AcquisitionMode,
    CapabilityCheck,
    DataHandlingMode,
    IndicatorQuerySpec,
    QuestionBrief,
    ResearchPlan,
    ReuseExpectation,
)
from sophia_episto.playbooks.labor_vs_growth import LaborVsGrowthPlaybook
from sophia_episto.planner import PlaybookPlanner
from sophia_episto.policy import RuleBasedAcquisitionPolicy


def test_labor_vs_growth_playbook_builds_expected_plan() -> None:
    brief = QuestionBrief(
        question="How is the labor market aligning with GDP strength?",
        normalized_question="how is the labor market aligning with gdp strength",
        intent="econ_research",
        tags=("labor", "growth"),
    )
    plan = LaborVsGrowthPlaybook().draft_plan(brief)

    assert plan.playbook_id == "labor_vs_growth"
    assert "real_gdp" in plan.indicator_families
    assert "payrolls" in plan.indicator_families


def test_playbook_planner_selects_registered_playbook() -> None:
    brief = QuestionBrief(
        question="Is labor diverging from GDP?",
        normalized_question="is labor diverging from gdp",
        intent="econ_research",
    )
    planner = PlaybookPlanner([LaborVsGrowthPlaybook()])

    plan = planner.build_plan(brief)

    assert plan.playbook_id == "labor_vs_growth"


def test_static_capability_resolver_marks_local_and_candidate_sources() -> None:
    brief = QuestionBrief(
        question="How is labor aligning with GDP?",
        normalized_question="how is labor aligning with gdp",
        intent="econ_research",
    )
    plan = LaborVsGrowthPlaybook().draft_plan(brief)
    resolver = StaticCapabilityResolver(
        available_indicator_families=("real_gdp", "payrolls", "unemployment"),
        source_map={
            "real_gdp": ("scrivener",),
            "job_openings": ("fred_api", "bls_api"),
        },
    )

    checks = resolver.resolve(plan)
    by_family = {check.indicator_family: check for check in checks}

    assert by_family["real_gdp"].available_locally is True
    assert by_family["real_gdp"].candidate_sources == ("scrivener",)
    assert by_family["job_openings"].available_locally is False
    assert by_family["job_openings"].candidate_sources == ("fred_api", "bls_api")


@pytest.mark.asyncio
async def test_search_backed_capability_resolver_uses_query_specs() -> None:
    brief = QuestionBrief(
        question="How is labor aligning with GDP?",
        normalized_question="how is labor aligning with gdp",
        intent="econ_research",
    )
    plan = LaborVsGrowthPlaybook().draft_plan(brief)

    async def _search(query: str) -> list[dict]:
        if "gdp" in query.lower():
            return [{"external_id": "GDPC1", "source": "FRED"}]
        return []

    resolver = SearchBackedCapabilityResolver(_search)
    checks = await resolver.resolve(plan)
    by_family = {check.indicator_family: check for check in checks}

    assert by_family["real_gdp"].available_locally is True
    assert by_family["real_gdp"].candidate_sources == ("FRED",)
    assert "GDPC1" in by_family["real_gdp"].notes[0]
    assert by_family["payrolls"].available_locally is False


def test_rule_based_acquisition_policy_marks_fetchable_and_local_series() -> None:
    brief = QuestionBrief(
        question="How is labor aligning with GDP?",
        normalized_question="how is labor aligning with gdp",
        intent="econ_research",
    )
    plan = LaborVsGrowthPlaybook().draft_plan(brief)
    checks = (
        StaticCapabilityResolver(
            available_indicator_families=("real_gdp",),
            source_map={
                "job_openings": ("FRED",),
                "claims": ("THIRD_PARTY",),
            },
        ).resolve(plan)
    )
    policy = RuleBasedAcquisitionPolicy(approved_sources=("FRED", "BLS"))

    decisions = policy.decide(plan, checks)
    by_family = {decision.indicator_family: decision for decision in decisions}

    assert by_family["real_gdp"].mode == AcquisitionMode.NONE
    assert by_family["real_gdp"].handling_mode == DataHandlingMode.SOURCE_LOCAL
    assert by_family["job_openings"].mode == AcquisitionMode.FETCH_NOW
    assert by_family["job_openings"].handling_mode == DataHandlingMode.ACQUIRE_AND_STORE
    assert by_family["job_openings"].source == "FRED"
    assert by_family["claims"].mode == AcquisitionMode.REJECT
    assert by_family["claims"].handling_mode == DataHandlingMode.REJECT_OR_ESCALATE
    assert by_family["claims"].requires_human_review is True


def test_rule_based_acquisition_policy_can_mark_ephemeral_fetches() -> None:
    brief = QuestionBrief(
        question="Find one-off supporting data for a custom lens",
        normalized_question="find one-off supporting data for a custom lens",
        intent="econ_research",
    )
    plan = ResearchPlan(
        plan_id="custom:draft",
        playbook_id="custom",
        question_brief=brief,
        subquestions=("What supporting series could help?",),
        indicator_families=("custom_support",),
        indicator_queries=(
            IndicatorQuerySpec(
                indicator_family="custom_support",
                queries=("custom support series",),
                preferred_sources=("FRED",),
                structured_data=False,
                reuse_expectation=ReuseExpectation.LOW,
            ),
        ),
    )
    checks = (
        CapabilityCheck(
            concept="custom",
            indicator_family="custom_support",
            available_locally=False,
            candidate_sources=("FRED",),
        ),
    )

    decisions = RuleBasedAcquisitionPolicy().decide(plan, checks)

    assert decisions[0].mode == AcquisitionMode.FETCH_NOW
    assert decisions[0].handling_mode == DataHandlingMode.ACQUIRE_EPHEMERAL
    assert decisions[0].retention_target == "ephemeral"
