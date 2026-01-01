"""Personality loader - parses markdown personality files into system prompts."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Personality:
    """Parsed personality configuration."""

    raw_content: str
    name: str = "Sophia"
    sections: dict[str, str] = field(default_factory=dict)

    def to_system_prompt(self, context: dict[str, str] | None = None) -> str:
        """
        Convert the personality to a system prompt.

        Args:
            context: Optional dynamic context to inject (e.g., current date, available tools)

        Returns:
            Formatted system prompt string
        """
        prompt_parts = [self.raw_content]

        if context:
            prompt_parts.append("\n## Current Context\n")
            for key, value in context.items():
                prompt_parts.append(f"- **{key}**: {value}")

        return "\n".join(prompt_parts)


def load_personality(path: Path) -> Personality:
    """
    Load and parse a personality definition from a markdown file.

    Args:
        path: Path to the markdown personality file

    Returns:
        Parsed Personality object

    Raises:
        FileNotFoundError: If the personality file doesn't exist
    """
    if not path.exists():
        raise FileNotFoundError(f"Personality file not found: {path}")

    content = path.read_text(encoding="utf-8")
    sections = _parse_sections(content)

    # Extract name from the first H1 heading if present
    name = "Sophia"
    for line in content.split("\n"):
        if line.startswith("# "):
            name = line[2:].strip()
            break

    return Personality(
        raw_content=content,
        name=name,
        sections=sections,
    )


def _parse_sections(content: str) -> dict[str, str]:
    """
    Parse markdown content into sections by H2 headings.

    Args:
        content: Raw markdown content

    Returns:
        Dictionary mapping section names to their content
    """
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_content: list[str] = []

    for line in content.split("\n"):
        if line.startswith("## "):
            # Save previous section
            if current_section is not None:
                sections[current_section] = "\n".join(current_content).strip()

            # Start new section
            current_section = line[3:].strip()
            current_content = []
        elif current_section is not None:
            current_content.append(line)

    # Save last section
    if current_section is not None:
        sections[current_section] = "\n".join(current_content).strip()

    return sections
