from __future__ import annotations

import re
from datetime import UTC, datetime

from sophia.agent import SophiaAgent
from sophia.personality.loader import Personality


def _make_agent_stub() -> SophiaAgent:
    agent = object.__new__(SophiaAgent)
    agent.personality = Personality(raw_content="# Sophia\n\nTest persona.")
    agent.soul = None
    agent.runtime_component_inventory = None
    agent.preflight_result = None
    agent.canvas_id = None
    agent.profile = type(
        "StubProfile",
        (),
        {
            "agent_id": "sophia_prima",
            "label": "Sophia Prima",
            "description": None,
            "prompt": None,
            "tool_allowlist": None,
        },
    )()
    return agent


def test_system_prompt_contains_current_date() -> None:
    agent = _make_agent_stub()
    prompt = agent._build_system_prompt()
    expected_date = datetime.now(UTC).strftime("%Y-%m-%d")
    assert expected_date in prompt
    assert "Current date" in prompt


def test_system_prompt_date_format_includes_weekday() -> None:
    agent = _make_agent_stub()
    prompt = agent._build_system_prompt()
    # Format: "YYYY-MM-DD (Weekday)"
    assert re.search(
        r"\d{4}-\d{2}-\d{2} \((Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\)",
        prompt,
    )
