from pathlib import Path

from sophia.skills.registry import SkillRegistry


def _write_skill(path: Path, *, name: str, description: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_registry_returns_none_when_disabled(tmp_path: Path) -> None:
    _write_skill(
        tmp_path / "release" / "SKILL.md",
        name="release-calendar-query-formatting",
        description="economic release schedule workflow",
        body="instructions",
    )
    registry = SkillRegistry(
        skills_root=tmp_path,
        enabled=False,
        max_loaded_chars=2000,
        implicit_min_overlap=2,
    )

    assert registry.match("check this week release schedule") is None


def test_registry_matches_single_best_skill(tmp_path: Path) -> None:
    _write_skill(
        tmp_path / "release" / "SKILL.md",
        name="release-calendar-query-formatting",
        description="economic release schedule workflow this week upcoming days",
        body="instructions",
    )
    _write_skill(
        tmp_path / "other" / "SKILL.md",
        name="chart-styling",
        description="chart colors legends axes",
        body="instructions",
    )
    registry = SkillRegistry(
        skills_root=tmp_path,
        enabled=True,
        max_loaded_chars=2000,
        implicit_min_overlap=2,
    )

    match = registry.match("show this week economic release schedule")

    assert match is not None
    assert match.skill.name == "release-calendar-query-formatting"
    assert match.skill.body == "instructions"


def test_registry_lazy_loads_body_without_mutating_frozen_manifest(tmp_path: Path) -> None:
    _write_skill(
        tmp_path / "release" / "SKILL.md",
        name="release-calendar-query-formatting",
        description="economic release schedule workflow this week upcoming days",
        body="use deterministic formatting",
    )
    registry = SkillRegistry(
        skills_root=tmp_path,
        enabled=True,
        max_loaded_chars=2000,
        implicit_min_overlap=2,
    )

    loaded = registry.list_skills()

    assert loaded
    assert loaded[0].body == ""

    match = registry.match("show this week economic release schedule")

    assert match is not None
    assert match.skill.body == "use deterministic formatting"
