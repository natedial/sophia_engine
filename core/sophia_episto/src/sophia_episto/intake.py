"""Question intake helpers for Episto."""

from __future__ import annotations

import re

from sophia_episto.plan_models import QuestionBrief


def build_question_brief(question: str) -> QuestionBrief:
    """Normalize a raw user question into a planning-friendly brief."""
    normalized = re.sub(r"\s+", " ", question.strip()).lower()
    tags = []
    for tag in ("labor", "growth", "gdp", "inflation", "fed", "supply", "rates"):
        if tag in normalized:
            tags.append(tag)
    return QuestionBrief(
        question=question,
        normalized_question=normalized,
        intent=_infer_intent(normalized),
        tags=tuple(tags),
    )


def _infer_intent(normalized_question: str) -> str:
    if any(
        token in normalized_question
        for token in ("how is", "why is", "what is driving", "align", "diverg", "compare")
    ):
        return "econ_research"
    return "general"
