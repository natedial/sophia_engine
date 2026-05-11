from __future__ import annotations

import pytest

from pylon.core import PreflightResult, ServiceStatus
from pylon.mcp_bridge import (
    PREFLIGHT_TOOL_NAME,
    call_mcp_tool,
    format_preflight_result,
    list_mcp_tool_specs,
    pylon_config_from_env,
)
from pylon.tools.base import ErrorType, ToolDefinition, ToolParameter, ToolParameterType, ToolResult


def test_pylon_config_from_env_uses_gateway_compatible_names() -> None:
    config = pylon_config_from_env(
        {
            "SCRIVENER_BASE_URL": "http://scrivener:8000",
            "ARITHMOS_BASE_URL": "http://arithmos:8001",
            "CANVAS_BASE_URL": "http://canvas:8003",
            "THOLOS_BASE_URL": "http://tholos:8004",
            "FED_TRACKER_URL": "http://fed:8005",
            "OIKONOMIA_BASE_URL": "http://oikonomia:8006",
            "BRAVE_API_KEY": "brave-key",
            "BRAVE_BASE_URL": "http://brave",
            "READWISE_CLI_PATH": "/bin/readwise",
            "READWISE_CLI_CONFIG_PATH": "/tmp/readwise.json",
            "PYLON_MAX_CONCURRENCY_PER_SERVICE": "3",
            "PYLON_TOOL_TIMEOUT_SEC": "7.5",
        }
    )

    assert config.scrivener_url == "http://scrivener:8000"
    assert config.arithmos_url == "http://arithmos:8001"
    assert config.canvas_url == "http://canvas:8003"
    assert config.tholos_url == "http://tholos:8004"
    assert config.fed_tracker_url == "http://fed:8005"
    assert config.oikonomia_url == "http://oikonomia:8006"
    assert config.brave_api_key == "brave-key"
    assert config.brave_base_url == "http://brave"
    assert config.readwise_cli_path == "/bin/readwise"
    assert config.readwise_cli_config_path == "/tmp/readwise.json"
    assert config.max_concurrency_per_service == 3
    assert config.tool_timeout_sec == 7.5


def test_list_mcp_tool_specs_includes_preflight_and_pylon_tools() -> None:
    class FakePylon:
        def get_tools(self, only_healthy: bool = False):
            assert only_healthy is False
            return [
                ToolDefinition(
                    name="get_latest_value",
                    description="Get latest value",
                    parameters=[
                        ToolParameter(
                            name="series_id",
                            type=ToolParameterType.STRING,
                            description="Series identifier",
                        )
                    ],
                )
            ]

    specs = list_mcp_tool_specs(FakePylon())  # type: ignore[arg-type]

    assert [spec.name for spec in specs] == [PREFLIGHT_TOOL_NAME, "get_latest_value"]
    assert specs[1].input_schema["properties"]["series_id"]["type"] == "string"
    assert specs[1].input_schema["required"] == ["series_id"]


def test_format_preflight_result_reports_degraded_services_and_tools() -> None:
    text = format_preflight_result(
        PreflightResult(
            all_healthy=False,
            services={
                "scrivener": ServiceStatus(name="scrivener", healthy=True, latency_ms=4.0),
                "tholos": ServiceStatus(
                    name="tholos",
                    healthy=False,
                    latency_ms=5.0,
                    error="Corpus not loaded",
                ),
            },
            available_tools=["get_latest_value"],
            unavailable_tools=["search_research"],
        )
    )

    assert "scrivener: healthy" in text
    assert "tholos: unavailable - Corpus not loaded" in text
    assert "Available tools: get_latest_value" in text
    assert "Unavailable tools: search_research" in text
    assert "SERVICE STATUS:" in text


@pytest.mark.asyncio
async def test_call_mcp_tool_runs_preflight() -> None:
    class FakePylon:
        async def preflight(self):
            return PreflightResult(
                all_healthy=True,
                services={
                    "scrivener": ServiceStatus(
                        name="scrivener",
                        healthy=True,
                        latency_ms=1.0,
                    )
                },
                available_tools=["get_latest_value"],
                unavailable_tools=[],
            )

    text = await call_mcp_tool(FakePylon(), PREFLIGHT_TOOL_NAME, {})  # type: ignore[arg-type]

    assert "scrivener: healthy" in text
    assert "Available tools: get_latest_value" in text


@pytest.mark.asyncio
async def test_call_mcp_tool_returns_pylon_tool_result_text() -> None:
    class FakePylon:
        async def execute_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
            assert name == "get_latest_value"
            assert arguments == {"series_id": "GDP"}
            return ToolResult.fail("Series not found", ErrorType.NOT_FOUND)

    text = await call_mcp_tool(
        FakePylon(),  # type: ignore[arg-type]
        "get_latest_value",
        {"series_id": "GDP"},
    )

    assert "Error: Series not found" in text
    assert "Error type: not_found" in text
    assert "Recovery hint:" in text
