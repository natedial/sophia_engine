from pathlib import Path

import pytest

from sophia.security.filesystem import ReadPolicy, WritePolicy, parse_allowlist


def test_parse_allowlist_supports_project_relative_paths(tmp_path: Path) -> None:
    roots = parse_allowlist(".sophia, /tmp", project_root=tmp_path)

    assert roots[0] == (tmp_path / ".sophia").resolve(strict=False)
    assert roots[1] == Path("/tmp").resolve(strict=False)


def test_write_policy_denies_paths_outside_allowlist(tmp_path: Path) -> None:
    allowed = (tmp_path / ".sophia").resolve(strict=False)
    policy = WritePolicy(enabled=True, allowed_roots=(allowed,))

    policy.ensure_allowed(allowed / "memory.db", purpose="test")
    with pytest.raises(PermissionError):
        policy.ensure_allowed(tmp_path / "README.md", purpose="test")


def test_read_policy_denies_paths_outside_allowlist(tmp_path: Path) -> None:
    allowed = (tmp_path / "config").resolve(strict=False)
    policy = ReadPolicy(enabled=True, allowed_roots=(allowed,))

    policy.ensure_allowed(allowed / "personality.md", purpose="test")
    with pytest.raises(PermissionError):
        policy.ensure_allowed(tmp_path / "skills" / "SKILL.md", purpose="test")
