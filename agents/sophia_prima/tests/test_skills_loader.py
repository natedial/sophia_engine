from pathlib import Path

from sophia.skills.loader import discover_skill_files, load_skill


def test_discover_skill_files_finds_nested_skill_files(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "SKILL.md").write_text("# A", encoding="utf-8")
    (tmp_path / "b" / "nested").mkdir(parents=True)
    (tmp_path / "b" / "nested" / "SKILL.md").write_text("# B", encoding="utf-8")

    files = discover_skill_files(tmp_path)

    assert files == sorted(files)
    assert len(files) == 2


def test_load_skill_parses_frontmatter_and_truncates_body(tmp_path: Path) -> None:
    skill_dir = tmp_path / "release-calendar"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: release-calendar-query-formatting\n"
        "description: deterministic release schedule workflow\n"
        "tool_allowlist: get_releases_week, get_releases_upcoming\n"
        "read_allowlist: config, skills\n"
        "write_allowlist: .sophia\n"
        "---\n\n"
        "0123456789abcdefghijklmnopqrstuvwxyz",
        encoding="utf-8",
    )

    manifest = load_skill(skill_file, max_body_chars=20)

    assert manifest.name == "release-calendar-query-formatting"
    assert manifest.description == "deterministic release schedule workflow"
    assert manifest.allowed_tools == ("get_releases_week", "get_releases_upcoming")
    assert manifest.read_allowlist == ("config", "skills")
    assert manifest.write_allowlist == (".sophia",)
    assert manifest.body.endswith("... [truncated]")


def test_load_skill_defaults_name_to_parent_folder(tmp_path: Path) -> None:
    skill_dir = tmp_path / "calendar-helper"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("No frontmatter body", encoding="utf-8")

    manifest = load_skill(skill_file, max_body_chars=0)

    assert manifest.name == "calendar-helper"
    assert manifest.description == ""
    assert manifest.body == "No frontmatter body"


def test_discover_skill_files_ignores_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-skill"
    outside.mkdir(exist_ok=True)
    (outside / "SKILL.md").write_text("outside", encoding="utf-8")

    link_dir = tmp_path / "linked"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        # Some environments disallow symlink creation for unprivileged users.
        return

    files = discover_skill_files(tmp_path)

    assert files == []
