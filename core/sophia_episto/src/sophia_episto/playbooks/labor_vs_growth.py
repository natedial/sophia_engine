"""Initial labor-vs-growth playbook."""

from __future__ import annotations

from sophia_episto.plan_models import (
    EvidencePlan,
    IndicatorQuerySpec,
    QuestionBrief,
    ResearchPlan,
)
from sophia_episto.playbooks.base import Playbook


class LaborVsGrowthPlaybook(Playbook):
    playbook_id = "labor_vs_growth"
    name = "Labor vs Growth"
    description = "Assess how labor-market conditions align with recent growth strength."

    def match(self, brief: QuestionBrief) -> float:
        text = brief.normalized_question.lower()
        score = 0.0
        if "labor" in text:
            score += 2.0
        if "gdp" in text or "growth" in text:
            score += 2.0
        if "align" in text or "diverg" in text:
            score += 1.0
        return score

    def draft_plan(self, brief: QuestionBrief) -> ResearchPlan:
        return ResearchPlan(
            plan_id=f"{self.playbook_id}:draft",
            playbook_id=self.playbook_id,
            question_brief=brief,
            subquestions=(
                "Is labor confirming or diverging from recent GDP strength?",
                "Which labor indicators are broad versus narrow confirmations?",
                "Are timing and frequency mismatches affecting interpretation?",
            ),
            hypotheses=(
                "Payrolls alone may overstate labor breadth.",
                "Quarterly GDP strength may not align cleanly with monthly labor signals.",
            ),
            indicator_families=(
                "real_gdp",
                "payrolls",
                "unemployment",
                "claims",
                "job_openings",
                "participation",
                "wages",
            ),
            indicator_queries=(
                IndicatorQuerySpec(
                    "real_gdp",
                    ("real gdp", "gross domestic product real"),
                    preferred_sources=("FRED",),
                ),
                IndicatorQuerySpec(
                    "payrolls",
                    ("nonfarm payrolls", "payroll employment"),
                    preferred_sources=("FRED", "BLS"),
                ),
                IndicatorQuerySpec(
                    "unemployment",
                    ("unemployment rate", "jobless rate"),
                    preferred_sources=("FRED", "BLS"),
                ),
                IndicatorQuerySpec(
                    "claims",
                    ("initial claims", "jobless claims"),
                    preferred_sources=("FRED",),
                ),
                IndicatorQuerySpec(
                    "job_openings",
                    ("job openings", "jolts openings"),
                    preferred_sources=("BLS", "FRED"),
                ),
                IndicatorQuerySpec(
                    "participation",
                    ("labor force participation rate",),
                    preferred_sources=("FRED", "BLS"),
                ),
                IndicatorQuerySpec(
                    "wages",
                    ("average hourly earnings", "wage growth"),
                    preferred_sources=("FRED", "BLS"),
                ),
            ),
            transforms=(
                "harmonize_monthly_to_quarterly",
                "compare_recent_trend_to_prior_window",
                "flag_revisions_and_frequency_mismatch",
            ),
            comparison_windows=("last_4_quarters", "last_3_months", "prior_baseline"),
            success_criteria=(
                "Include at least one breadth indicator beyond payrolls.",
                "Explicitly note any monthly-to-quarterly harmonization.",
            ),
            evidence_plan=EvidencePlan(
                required_citations=True,
                validation_rules=(
                    "Do not infer labor strength from payrolls alone.",
                    "Document revisions or provisional releases where relevant.",
                ),
            ),
        )
