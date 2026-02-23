"""Skill matching logic."""

from __future__ import annotations

import re

from sophia.skills.models import SkillManifest, SkillMatch

_STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "how",
    "i", "if", "in", "is", "it", "me", "of", "on", "or", "our",
    "that", "the", "this", "to", "use", "we", "what", "with", "you",
}


def select_best_skill(
    user_message: str,
    skills: list[SkillManifest],
    *,
    min_overlap: int,
) -> SkillMatch | None:
    """Return a single best-matching skill, or None."""
    if not user_message.strip() or not skills:
        return None

    message = user_message.lower()
    message_tokens = _tokens(message)
    best: SkillMatch | None = None

    for skill in skills:
        skill_name = skill.name.lower()
        explicit_score, explicit_reason = _explicit_score(message, skill_name)
        if explicit_score > 0:
            candidate = SkillMatch(skill=skill, score=explicit_score, reason=explicit_reason)
        else:
            implicit_score, implicit_reason = _implicit_score(
                message_tokens,
                skill,
                min_overlap=min_overlap,
            )
            if implicit_score <= 0:
                continue
            candidate = SkillMatch(skill=skill, score=implicit_score, reason=implicit_reason)

        if best is None or candidate.score > best.score:
            best = candidate

    return best


def _explicit_score(message: str, skill_name: str) -> tuple[float, str]:
    token = f"${skill_name}"
    if token in message:
        return 100.0, f"explicit token '{token}'"
    if skill_name in message:
        return 90.0, f"explicit name '{skill_name}'"
    return 0.0, ""


def _implicit_score(
    message_tokens: set[str],
    skill: SkillManifest,
    *,
    min_overlap: int,
) -> tuple[float, str]:
    description_tokens = _tokens(f"{skill.name} {skill.description}")
    overlap = len(message_tokens & description_tokens)
    if overlap < min_overlap:
        return 0.0, ""
    return float(overlap), f"implicit description overlap={overlap}"


def _tokens(text: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-z0-9]+", text.lower())
        if len(tok) > 2 and tok not in _STOPWORDS
    }
