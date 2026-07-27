from pathlib import Path

from sophia.skills.matcher import select_best_skill
from sophia.skills.models import SkillManifest


def _skill(name: str, description: str) -> SkillManifest:
    return SkillManifest(
        name=name,
        description=description,
        body="instructions",
        path=Path(f"/tmp/{name}/SKILL.md"),
    )


def test_matcher_prefers_explicit_skill_token() -> None:
    release_skill = _skill(
        "release-calendar-query-formatting",
        "economic release schedules and output formatting",
    )
    generic_skill = _skill("portfolio-summary", "portfolio metrics formatting")

    match = select_best_skill(
        "please run $release-calendar-query-formatting for this week's releases",
        [generic_skill, release_skill],
        min_overlap=2,
    )

    assert match is not None
    assert match.skill.name == "release-calendar-query-formatting"
    assert match.score >= 100.0


def test_matcher_uses_implicit_description_overlap() -> None:
    release_skill = _skill(
        "release-calendar-query-formatting",
        "economic release schedule for today week and upcoming dates",
    )

    match = select_best_skill(
        "check the economic release schedule for this week",
        [release_skill],
        min_overlap=2,
    )

    assert match is not None
    assert match.skill.name == "release-calendar-query-formatting"
    assert "implicit description overlap" in match.reason


def test_matcher_returns_none_when_overlap_below_threshold() -> None:
    release_skill = _skill(
        "release-calendar-query-formatting",
        "economic releases schedule",
    )

    match = select_best_skill(
        "calendar",
        [release_skill],
        min_overlap=2,
    )

    assert match is None
