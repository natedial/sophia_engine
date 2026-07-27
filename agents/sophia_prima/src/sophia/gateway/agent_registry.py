"""Registry helpers for gateway-level specialist agents."""

from __future__ import annotations

import json

from sophia.agent_profiles import AgentProfile


def load_agent_profiles(
    *,
    default_agent_id: str,
    raw_profiles_json: str,
) -> dict[str, AgentProfile]:
    """Load built-in profiles, optionally overridden by JSON config."""
    profiles = {
        profile.agent_id: profile
        for profile in _default_profiles(default_agent_id=default_agent_id)
    }
    if not raw_profiles_json.strip():
        return profiles

    parsed = json.loads(raw_profiles_json)
    if not isinstance(parsed, list):
        raise ValueError("gateway agents JSON must be a list")

    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"gateway agent at index {i} must be an object")
        agent_id = str(item.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError(f"gateway agent at index {i} is missing agent_id")
        allowlist = item.get("tool_allowlist")
        profiles[agent_id] = AgentProfile(
            agent_id=agent_id,
            label=str(item.get("label") or agent_id),
            description=str(item.get("description") or ""),
            prompt=str(item.get("prompt") or ""),
            tool_allowlist=_parse_allowlist(allowlist),
            skills_enabled=_optional_bool(item.get("skills_enabled")),
            subagents_enabled=_optional_bool(item.get("subagents_enabled")),
        )
    return profiles


def _default_profiles(*, default_agent_id: str) -> list[AgentProfile]:
    default_prompt = (
        "You are the general-purpose gateway agent. Route broad user requests, use the "
        "full tool surface when needed, and preserve Sophia's default conversational style."
    )
    return [
        AgentProfile(
            agent_id=default_agent_id,
            label="Sophia Prima",
            description="General-purpose primary agent.",
            prompt=default_prompt,
        ),
        AgentProfile(
            agent_id="macro_research",
            label="Macro Research",
            description="Evidence-first analyst for macro, rates, and research questions.",
            prompt=(
                "Prioritize sourced evidence, explicitly separate facts from interpretation, "
                "and bias toward research retrieval and Fed-text analysis tools."
            ),
            tool_allowlist=(
                "search_web",
                "get_web_context",
                "search_research",
                "get_research_chunk",
                "list_research_sources",
                "get_latest_value",
                "get_observations",
                "get_series_change",
                "get_releases_upcoming",
                "get_releases_today",
                "get_releases_week",
                "get_releases_summary",
                "get_speeches",
                "get_speech",
                "get_speakers",
                "fed_speaker_brief",
                "fed_speaker_question",
                "fed_speaker_timeline",
                "fed_speaker_comparisons",
                "fed_speaker_orphaned_concepts",
                "fed_speaker_theme_drift",
            ),
            subagents_enabled=True,
        ),
        AgentProfile(
            agent_id="trader_workbench",
            label="Trader Workbench",
            description="Deterministic market workflow agent for catalysts, ideas, and risk.",
            prompt=(
                "Use deterministic calculations first, then synthesize compact trading output "
                "with explicit risk framing and scenario language."
            ),
            tool_allowlist=(
                "get_latest_value",
                "get_observations",
                "get_series_change",
                "get_releases_upcoming",
                "get_releases_today",
                "get_releases_week",
                "get_releases_summary",
                "get_auctions",
                "get_auction_summary",
                "get_speeches",
                "get_speech",
                "compute",
                "list_computation_types",
                "create_canvas",
                "get_canvas",
                "create_timeseries_chart",
                "create_comparison_chart",
                "create_scatter_chart",
                "create_yield_curve_chart",
                "update_canvas_layout",
                "fed_speaker_brief",
                "fed_speaker_question",
            ),
            subagents_enabled=True,
            skills_enabled=False,
        ),
        AgentProfile(
            agent_id="canvas_analyst",
            label="Canvas Analyst",
            description="Visualization specialist for dashboard and chart assembly.",
            prompt=(
                "Focus on chart selection, dashboard layout, and concise chart commentary. "
                "Prefer creating or updating canvas artifacts over long narrative answers."
            ),
            tool_allowlist=(
                "create_canvas",
                "get_canvas",
                "create_timeseries_chart",
                "create_comparison_chart",
                "create_scatter_chart",
                "create_yield_curve_chart",
                "create_custom_chart",
                "update_canvas_layout",
                "delete_chart",
                "get_latest_value",
                "get_observations",
                "get_series_change",
            ),
            subagents_enabled=True,
            skills_enabled=False,
        ),
    ]


def _parse_allowlist(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("tool_allowlist must be a list when provided")
    items = [str(item).strip() for item in value if str(item).strip()]
    return tuple(items)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("expected boolean value")
