"""MCP adaptation helpers for exposing Pylon tools."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pylon.core import PreflightResult, Pylon, PylonConfig
from pylon.tools.base import ToolResult

PREFLIGHT_TOOL_NAME = "sophia_pylon_preflight"


@dataclass(frozen=True)
class McpToolSpec:
    """Tool metadata in the shape needed by MCP server registration."""

    name: str
    description: str
    input_schema: dict[str, Any]


PREFLIGHT_TOOL_SPEC = McpToolSpec(
    name=PREFLIGHT_TOOL_NAME,
    description=(
        "Run a Sophia Pylon preflight check and report backend service health, "
        "available tools, unavailable tools, and degraded-service guidance."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
)


def pylon_config_from_env(env: Mapping[str, str] | None = None) -> PylonConfig:
    """Build a PylonConfig from gateway-compatible environment variables."""
    source = env or os.environ
    return PylonConfig(
        scrivener_url=source.get("SCRIVENER_BASE_URL", PylonConfig.scrivener_url),
        arithmos_url=source.get("ARITHMOS_BASE_URL", PylonConfig.arithmos_url),
        canvas_url=source.get("CANVAS_BASE_URL", PylonConfig.canvas_url),
        tholos_url=source.get("THOLOS_BASE_URL", PylonConfig.tholos_url),
        fed_tracker_url=source.get("FED_TRACKER_URL", PylonConfig.fed_tracker_url),
        oikonomia_url=source.get("OIKONOMIA_BASE_URL", PylonConfig.oikonomia_url),
        readwise_cli_path=source.get("READWISE_CLI_PATH", PylonConfig.readwise_cli_path),
        readwise_cli_config_path=source.get(
            "READWISE_CLI_CONFIG_PATH",
            PylonConfig.readwise_cli_config_path,
        ),
        brave_base_url=source.get("BRAVE_BASE_URL", PylonConfig.brave_base_url),
        brave_api_key=source.get("BRAVE_API_KEY", PylonConfig.brave_api_key),
        max_concurrency_per_service=_env_int(
            source,
            "PYLON_MAX_CONCURRENCY_PER_SERVICE",
            PylonConfig.max_concurrency_per_service,
        ),
        tool_timeout_sec=_env_float(
            source,
            "PYLON_TOOL_TIMEOUT_SEC",
            PylonConfig.tool_timeout_sec,
        ),
    )


def list_mcp_tool_specs(pylon: Pylon, *, only_healthy: bool = False) -> list[McpToolSpec]:
    """Return MCP-facing tool specs for all Pylon tools plus preflight."""
    specs = [PREFLIGHT_TOOL_SPEC]
    for tool in pylon.get_tools(only_healthy=only_healthy):
        generic = tool.to_generic_schema()
        specs.append(
            McpToolSpec(
                name=str(generic["name"]),
                description=str(generic["description"]),
                input_schema=dict(generic["input_schema"]),
            )
        )
    return specs


async def call_mcp_tool(pylon: Pylon, name: str, arguments: dict[str, Any] | None) -> str:
    """Execute one MCP tool call through Pylon and return model-facing text."""
    if name == PREFLIGHT_TOOL_NAME:
        preflight = await pylon.preflight()
        return format_preflight_result(preflight)

    result = await pylon.execute_tool(name, arguments or {})
    return result.to_content()


def format_preflight_result(preflight: PreflightResult) -> str:
    """Format preflight output as compact, model-readable text."""
    lines = [preflight.summary()]
    lines.append("")
    lines.append("Available tools: " + _join_or_none(sorted(preflight.available_tools)))
    lines.append("Unavailable tools: " + _join_or_none(sorted(preflight.unavailable_tools)))
    prompt_context = preflight.for_system_prompt()
    if prompt_context:
        lines.append("")
        lines.append(prompt_context)
    return "\n".join(lines).strip()


def tool_result_to_text(result: ToolResult) -> str:
    """Convert a Pylon tool result into MCP text content."""
    return result.to_content()


def _join_or_none(values: list[str]) -> str:
    return ", ".join(values) if values else "(none)"


def _env_int(source: Mapping[str, str], name: str, default: int) -> int:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _env_float(source: Mapping[str, str], name: str, default: float) -> float:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)
