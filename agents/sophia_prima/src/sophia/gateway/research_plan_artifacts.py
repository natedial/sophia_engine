"""Helpers for working with persisted research-plan artifacts."""

from __future__ import annotations

from typing import Any

from sophia.events import EventType


def resolve_research_plan_event(
    record: dict[str, object],
    *,
    indicator_family: str,
) -> dict[str, object]:
    events = record.get("events")
    if not isinstance(events, list):
        raise ValueError("run does not contain any persisted events")

    for event in reversed(events):
        if not isinstance(event, dict) or event.get("event_type") != EventType.RESEARCH_PLAN_CREATED.value:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        if research_plan_mentions_indicator(data, indicator_family=indicator_family):
            return data

    raise ValueError(
        f"run does not contain a research plan for indicator_family '{indicator_family}'"
    )


def research_plan_mentions_indicator(
    plan_data: dict[str, object],
    *,
    indicator_family: str,
) -> bool:
    families = plan_data.get("indicator_families")
    if isinstance(families, (list, tuple)) and indicator_family in families:
        return True

    decisions = plan_data.get("acquisition_decisions")
    if isinstance(decisions, (list, tuple)):
        for item in decisions:
            if isinstance(item, dict) and item.get("indicator_family") == indicator_family:
                return True

    queries = plan_data.get("indicator_queries")
    if isinstance(queries, (list, tuple)):
        for item in queries:
            if isinstance(item, dict) and item.get("indicator_family") == indicator_family:
                return True
    return False


def resolve_acquisition_decision(
    plan_data: dict[str, object],
    *,
    indicator_family: str,
) -> dict[str, object] | None:
    decisions = plan_data.get("acquisition_decisions")
    if not isinstance(decisions, (list, tuple)):
        return None
    for item in decisions:
        if isinstance(item, dict) and item.get("indicator_family") == indicator_family:
            return item
    return None


def resolve_indicator_query_spec(
    plan_data: dict[str, object],
    *,
    indicator_family: str,
) -> dict[str, object] | None:
    queries = plan_data.get("indicator_queries")
    if not isinstance(queries, (list, tuple)):
        return None
    for item in queries:
        if isinstance(item, dict) and item.get("indicator_family") == indicator_family:
            return item
    return None
