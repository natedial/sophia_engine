"""Tool definitions for the Fed Textual Change Tracker service."""

import json
from typing import Any

import httpx

from pylon.clients.fed_tracker import FedTrackerClient
from pylon.tools.base import (
    ErrorType,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


def _classify_http_error(status_code: int, response_text: str) -> tuple[ErrorType, str]:
    """Classify an HTTP error by status code."""
    if status_code == 404:
        return ErrorType.NOT_FOUND, f"Speaker or resource not found: {response_text}"
    elif status_code in {400, 422}:
        return ErrorType.INVALID_INPUT, f"Invalid request: {response_text}"
    elif status_code == 503:
        return ErrorType.SERVICE_UNAVAILABLE, f"Fed Tracker unavailable: {response_text}"
    elif status_code >= 500:
        return ErrorType.SERVICE_UNAVAILABLE, f"Server error ({status_code}): {response_text}"
    else:
        return ErrorType.UNKNOWN, f"HTTP error {status_code}: {response_text}"


def _classify_request_error(error: httpx.RequestError) -> tuple[ErrorType, str]:
    """Classify a request-level error."""
    if isinstance(error, httpx.TimeoutException):
        return ErrorType.TIMEOUT, f"Request timed out: {error}"
    elif isinstance(error, httpx.ConnectError):
        return ErrorType.SERVICE_UNAVAILABLE, f"Could not connect to fed_tracker: {error}"
    else:
        return ErrorType.SERVICE_UNAVAILABLE, f"Request failed: {error}"


FED_TRACKER_TOOLS = [
    ToolDefinition(
        name="fed_speaker_brief",
        description=(
            "Get a high-level analytical brief for a Federal Reserve speaker. "
            "Returns a structured summary of the speaker's recent positions, themes, "
            "and rhetorical patterns. Optionally filter by theme (e.g. INFLATION, "
            "EMPLOYMENT, FINANCIAL_STABILITY). Best default tool for understanding "
            "a speaker's current state."
        ),
        parameters=[
            ToolParameter(
                name="speaker_name",
                type=ToolParameterType.STRING,
                description=(
                    "Full name of the Fed speaker (e.g. 'Jerome H. Powell', "
                    "'Lisa D. Cook')"
                ),
                required=True,
            ),
            ToolParameter(
                name="theme",
                type=ToolParameterType.STRING,
                description=(
                    "Optional theme filter (e.g. INFLATION, EMPLOYMENT, "
                    "FINANCIAL_STABILITY, MONETARY_POLICY)"
                ),
                required=False,
            ),
        ],
    ),
    ToolDefinition(
        name="fed_speaker_question",
        description=(
            "Ask a natural-language question about a Federal Reserve speaker's "
            "communications. Queries structured textual-analysis artifacts including "
            "semantic fingerprints, comparisons, theme drift, and phrase anomalies "
            "to produce an evidence-based answer. Best for analytical questions like "
            "'How has Powell's inflation rhetoric shifted over the last two years?'"
        ),
        parameters=[
            ToolParameter(
                name="speaker_name",
                type=ToolParameterType.STRING,
                description="Full name of the Fed speaker",
                required=True,
            ),
            ToolParameter(
                name="question",
                type=ToolParameterType.STRING,
                description="Natural-language question about the speaker's communications",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="fed_speaker_timeline",
        description=(
            "Get a chronological timeline of a Federal Reserve speaker's "
            "communications with key metadata."
        ),
        parameters=[
            ToolParameter(
                name="speaker_name",
                type=ToolParameterType.STRING,
                description="Full name of the Fed speaker",
                required=True,
            ),
            ToolParameter(
                name="limit",
                type=ToolParameterType.INTEGER,
                description="Maximum number of timeline entries to return",
                required=False,
            ),
        ],
    ),
    ToolDefinition(
        name="fed_speaker_comparisons",
        description=(
            "Get t-1 (consecutive speech) comparisons for a speaker, showing "
            "what changed between successive communications. Useful for tracking "
            "rhetorical shifts between appearances."
        ),
        parameters=[
            ToolParameter(
                name="speaker_name",
                type=ToolParameterType.STRING,
                description="Full name of the Fed speaker",
                required=True,
            ),
            ToolParameter(
                name="comparison_type",
                type=ToolParameterType.STRING,
                description="Type of comparison (default: t_minus_1)",
                required=False,
                default="t_minus_1",
            ),
            ToolParameter(
                name="limit",
                type=ToolParameterType.INTEGER,
                description="Maximum number of comparisons to return",
                required=False,
            ),
        ],
    ),
    ToolDefinition(
        name="fed_speaker_orphaned_concepts",
        description=(
            "Find concepts that a speaker emphasized but then dropped from "
            "subsequent communications within a given time window. Useful for "
            "detecting abandoned policy themes or trial balloons."
        ),
        parameters=[
            ToolParameter(
                name="speaker_name",
                type=ToolParameterType.STRING,
                description="Full name of the Fed speaker",
                required=True,
            ),
            ToolParameter(
                name="window_days",
                type=ToolParameterType.INTEGER,
                description="Lookback window in days (default: 75)",
                required=False,
                default=75,
            ),
            ToolParameter(
                name="min_emphasis",
                type=ToolParameterType.INTEGER,
                description="Minimum emphasis score to include (default: 3)",
                required=False,
                default=3,
            ),
        ],
    ),
    ToolDefinition(
        name="fed_speaker_theme_drift",
        description=(
            "Analyze how a speaker's treatment of a specific theme has evolved "
            "over time. Tracks rhetorical drift across a configurable window. "
            "Useful for understanding long-term shifts in policy messaging."
        ),
        parameters=[
            ToolParameter(
                name="speaker_name",
                type=ToolParameterType.STRING,
                description="Full name of the Fed speaker",
                required=True,
            ),
            ToolParameter(
                name="theme",
                type=ToolParameterType.STRING,
                description="Theme to track (e.g. INFLATION, EMPLOYMENT)",
                required=True,
            ),
            ToolParameter(
                name="window_days",
                type=ToolParameterType.INTEGER,
                description="Lookback window in days (default: 730, i.e. ~24 months)",
                required=False,
                default=730,
            ),
        ],
    ),
    ToolDefinition(
        name="fed_ingest_url",
        description=(
            "Ingest a Federal Reserve communication by URL into the tracker. "
            "The service will fetch, parse, and extract structured artifacts. "
            "Use this before querying a speaker if the document may not yet be stored. "
            "Best for Board, New York Fed, and Dallas Fed sources."
        ),
        parameters=[
            ToolParameter(
                name="url",
                type=ToolParameterType.STRING,
                description="URL of the Fed communication to ingest",
                required=True,
            ),
            ToolParameter(
                name="skip_existing",
                type=ToolParameterType.BOOLEAN,
                description="Skip if already ingested (default: true)",
                required=False,
                default=True,
            ),
        ],
    ),
    ToolDefinition(
        name="fed_ingest_urls",
        description=(
            "Batch-ingest multiple Federal Reserve communication URLs into the "
            "tracker. Use this for bulk ingestion of speeches or testimony."
        ),
        parameters=[
            ToolParameter(
                name="urls",
                type=ToolParameterType.ARRAY,
                description="List of URLs to ingest",
                required=True,
                items={"type": "string"},
            ),
            ToolParameter(
                name="skip_existing",
                type=ToolParameterType.BOOLEAN,
                description="Skip already-ingested URLs (default: true)",
                required=False,
                default=True,
            ),
        ],
    ),
]


class FedTrackerToolExecutor:
    """Executes tools against the Fed Tracker client."""

    def __init__(self, client: FedTrackerClient) -> None:
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        """Get all tool definitions for Fed Tracker."""
        return FED_TRACKER_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any], on_update=None) -> ToolResult:
        """Execute a Fed Tracker tool."""
        try:
            match tool_name:
                case "fed_speaker_brief":
                    data = await self.client.speaker_brief(
                        speaker_name=parameters["speaker_name"],
                        theme=parameters.get("theme"),
                    )
                case "fed_speaker_question":
                    data = await self.client.speaker_question(
                        speaker_name=parameters["speaker_name"],
                        question=parameters["question"],
                    )
                case "fed_speaker_timeline":
                    data = await self.client.speaker_timeline(
                        speaker_name=parameters["speaker_name"],
                        limit=_coerce_optional_int(parameters.get("limit")),
                    )
                case "fed_speaker_comparisons":
                    data = await self.client.speaker_comparisons(
                        speaker_name=parameters["speaker_name"],
                        comparison_type=parameters.get("comparison_type", "t_minus_1"),
                        limit=_coerce_optional_int(parameters.get("limit")),
                    )
                case "fed_speaker_orphaned_concepts":
                    data = await self.client.speaker_orphaned(
                        speaker_name=parameters["speaker_name"],
                        window_days=_coerce_int(parameters.get("window_days"), default=75),
                        min_emphasis=_coerce_int(parameters.get("min_emphasis"), default=3),
                    )
                case "fed_speaker_theme_drift":
                    data = await self.client.speaker_drift(
                        speaker_name=parameters["speaker_name"],
                        theme=parameters["theme"],
                        window_days=_coerce_int(parameters.get("window_days"), default=730),
                    )
                case "fed_ingest_url":
                    data = await self.client.ingest_url(
                        url=parameters["url"],
                        skip_existing=parameters.get("skip_existing", True),
                    )
                case "fed_ingest_urls":
                    data = await self.client.ingest_urls(
                        urls=parameters["urls"],
                        skip_existing=parameters.get("skip_existing", True),
                    )
                case _:
                    return ToolResult.fail(
                        f"Unknown tool: {tool_name}",
                        ErrorType.INVALID_INPUT,
                    )

            return ToolResult.ok(json.dumps(data, indent=2) if data is not None else "{}")

        except httpx.HTTPStatusError as e:
            error_type, message = _classify_http_error(
                e.response.status_code, e.response.text
            )
            return ToolResult.fail(message, error_type)

        except httpx.RequestError as e:
            error_type, message = _classify_request_error(e)
            return ToolResult.fail(message, error_type)

        except KeyError as e:
            return ToolResult.fail(
                f"Missing required parameter: {e}",
                ErrorType.INVALID_INPUT,
            )

        except ValueError as e:
            return ToolResult.fail(str(e), ErrorType.UNKNOWN)

        except Exception as e:
            return ToolResult.fail(str(e), ErrorType.UNKNOWN)


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
