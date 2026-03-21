"""Safety validation for memory content."""

from __future__ import annotations

import re

INJECTION_PATTERNS = [
    re.compile(r"(?i)\b(system|assistant|user)\s*:"),
    re.compile(r"(?i)ignore\s+(previous|above|all)\s+instructions"),
    re.compile(r"(?i)you\s+are\s+now\b"),
    re.compile(r"(?i)new\s+instructions?\s*:"),
    re.compile(r"(?i)forget\s+(everything|what|all)\s+(you|previous)"),
    re.compile(r"(?i)override\s+(system|security|safety)"),
]

EXFILTRATION_PATTERNS = [
    re.compile(r"(?i)(curl|wget|fetch)\s+.*\$"),
    re.compile(r"(?i)cat\s+.*\.(env|key|pem|secret|credentials)"),
    re.compile(r"(?i)(API_KEY|SECRET|PASSWORD|TOKEN|ACCESS_KEY)\s*[=:]"),
    re.compile(r"(?i)--header\s+['\"]Authorization"),
]

INVISIBLE_UNICODE = {"\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"}

MAX_MEMORY_CHARS = 500


def validate_memory_content(content: str) -> str | None:
    """Validate memory content for safety issues.

    Returns:
        None if content is safe, or an error message describing the issue.
    """
    if not content or not content.strip():
        return "Memory content cannot be empty."

    if len(content) > MAX_MEMORY_CHARS:
        return f"Memory content exceeds maximum length of {MAX_MEMORY_CHARS} characters."

    has_invisible = any(c in INVISIBLE_UNICODE for c in content)
    if has_invisible:
        return "Memory content contains invisible Unicode characters."

    for pattern in INJECTION_PATTERNS:
        if pattern.search(content):
            return "Memory content contains potential instruction injection."

    for pattern in EXFILTRATION_PATTERNS:
        if pattern.search(content):
            return "Memory content contains potential credential exfiltration pattern."

    return None


def normalize_for_comparison(text: str) -> str:
    """Normalize text for duplicate comparison."""
    return " ".join(text.lower().split())
