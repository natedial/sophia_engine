"""Skill discovery and file parsing."""

from __future__ import annotations

from pathlib import Path

from sophia.security.filesystem import ReadPolicy
from sophia.skills.models import SkillManifest


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def discover_skill_files(skills_root: Path) -> list[Path]:
    """Find SKILL.md files under the given root."""
    if not skills_root.exists() or not skills_root.is_dir():
        return []
    root = skills_root.resolve(strict=False)
    files: list[Path] = []
    for path in skills_root.rglob("SKILL.md"):
        if not path.is_file():
            continue
        resolved = path.resolve(strict=False)
        if _is_within(resolved, root):
            files.append(path)
    return sorted(files)


def load_skill(
    path: Path,
    *,
    max_body_chars: int,
    read_policy: ReadPolicy | None = None,
    metadata_only: bool = False,
) -> SkillManifest:
    """Load one SKILL.md file into a manifest.

    Args:
        path: Path to the SKILL.md file.
        max_body_chars: Maximum characters to load for the body.
        read_policy: Optional read policy for security checks.
        metadata_only: If True, only parse frontmatter, don't load body.
    """
    if read_policy is not None:
        read_policy.ensure_allowed(path, purpose="skill_file")
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)
    metadata = _parse_frontmatter(frontmatter)

    name = (metadata.get("name") or path.parent.name).strip()
    description = (metadata.get("description") or "").strip()
    allowed_tools = _parse_csv_list(metadata.get("tool_allowlist") or metadata.get("allowed_tools"))
    read_allowlist = _parse_csv_list(metadata.get("read_allowlist"))
    write_allowlist = _parse_csv_list(metadata.get("write_allowlist"))

    if metadata_only:
        body = ""
    else:
        body = body.strip()
        if max_body_chars > 0 and len(body) > max_body_chars:
            body = body[:max_body_chars] + "\n... [truncated]"

    return SkillManifest(
        name=name,
        description=description,
        body=body,
        path=path,
        allowed_tools=allowed_tools,
        read_allowlist=read_allowlist or (),
        write_allowlist=write_allowlist or (),
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter, body). Frontmatter can be empty."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx is None:
        return "", text

    frontmatter = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    return frontmatter, body


def _parse_frontmatter(frontmatter: str) -> dict[str, str]:
    """Parse a minimal key:value frontmatter block."""
    metadata: dict[str, str] = {}
    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            metadata[key] = value
    return metadata


def _parse_csv_list(raw: str | None) -> tuple[str, ...] | None:
    """Parse comma-separated values into a normalized tuple."""
    if raw is None:
        return None
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        return ()
    return tuple(dict.fromkeys(items))
