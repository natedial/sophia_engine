"""Tool definitions for Scrivener service."""

import json
from typing import Any

import httpx

from pylon.clients.scrivener import ScrivenerClient
from pylon.tools.base import (
    ErrorType,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


def _classify_http_error(status_code: int, response_text: str) -> tuple[ErrorType, str]:
    """Classify an HTTP error by status code.

    Returns:
        Tuple of (ErrorType, human-readable error message)
    """
    if status_code == 404:
        return ErrorType.NOT_FOUND, f"Resource not found: {response_text}"
    elif status_code == 400:
        return ErrorType.INVALID_INPUT, f"Invalid request: {response_text}"
    elif status_code == 401:
        return ErrorType.UNAUTHORIZED, "Authentication required"
    elif status_code == 403:
        return ErrorType.UNAUTHORIZED, "Access forbidden"
    elif status_code == 429:
        return ErrorType.RATE_LIMITED, "Rate limit exceeded"
    elif status_code == 503:
        return ErrorType.SERVICE_UNAVAILABLE, "Service temporarily unavailable"
    elif status_code >= 500:
        return ErrorType.SERVICE_UNAVAILABLE, f"Server error ({status_code}): {response_text}"
    else:
        return ErrorType.UNKNOWN, f"HTTP error {status_code}: {response_text}"


def _classify_request_error(error: httpx.RequestError) -> tuple[ErrorType, str]:
    """Classify a request-level error (network issues, timeouts, etc.)."""
    if isinstance(error, httpx.TimeoutException):
        return ErrorType.TIMEOUT, f"Request timed out: {error}"
    elif isinstance(error, httpx.ConnectError):
        return ErrorType.SERVICE_UNAVAILABLE, f"Could not connect to service: {error}"
    else:
        return ErrorType.SERVICE_UNAVAILABLE, f"Request failed: {error}"


# Tool definitions for Scrivener
SCRIVENER_TOOLS = [
    ToolDefinition(
        name="list_series",
        description="List all available economic data series. Returns series IDs, names, and descriptions.",
        parameters=[],
    ),
    ToolDefinition(
        name="search_series",
        description="Search for economic data series by keyword. Use this to find relevant series before fetching data.",
        parameters=[
            ToolParameter(
                name="query",
                type=ToolParameterType.STRING,
                description="Search query (e.g., 'inflation', 'GDP', 'unemployment')",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="get_series_info",
        description="Get metadata about a specific data series including its description, frequency, and units.",
        parameters=[
            ToolParameter(
                name="series_id",
                type=ToolParameterType.STRING,
                description="The series identifier (e.g., 'GDP', 'FEDFUNDS', 'UNRATE')",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="get_latest_value",
        description="Get the most recent value for a data series. Use this for current readings.",
        parameters=[
            ToolParameter(
                name="series_id",
                type=ToolParameterType.STRING,
                description="The series identifier (e.g., 'GDP', 'FEDFUNDS', 'UNRATE')",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="get_observations",
        description="Get historical time series data for a series. Returns date-value pairs.",
        parameters=[
            ToolParameter(
                name="series_id",
                type=ToolParameterType.STRING,
                description="The series identifier",
                required=True,
            ),
            ToolParameter(
                name="days",
                type=ToolParameterType.INTEGER,
                description="Number of days of history to retrieve (default: 365)",
                required=False,
                default=365,
            ),
        ],
    ),
    ToolDefinition(
        name="get_series_change",
        description="Calculate the change in a series over a period. Useful for comparing current vs prior values.",
        parameters=[
            ToolParameter(
                name="series_id",
                type=ToolParameterType.STRING,
                description="The series identifier",
                required=True,
            ),
            ToolParameter(
                name="periods",
                type=ToolParameterType.INTEGER,
                description="Number of periods back to compare (default: 1)",
                required=False,
                default=1,
            ),
        ],
    ),
    ToolDefinition(
        name="get_auctions",
        description="Get recent Treasury auction results. Includes bills, notes, bonds, TIPS, and FRNs.",
        parameters=[
            ToolParameter(
                name="security_type",
                type=ToolParameterType.STRING,
                description="Filter by security type",
                required=False,
                enum=["Bill", "Note", "Bond", "TIPS", "FRN"],
            ),
            ToolParameter(
                name="days",
                type=ToolParameterType.INTEGER,
                description="Number of days of history (default: 30)",
                required=False,
                default=30,
            ),
        ],
    ),
    ToolDefinition(
        name="get_auction_summary",
        description="Get aggregate statistics on recent Treasury auctions including average bid-to-cover ratios and yields.",
        parameters=[],
    ),
    # -------------------------------------------------------------------------
    # Releases (Economic Calendar)
    # -------------------------------------------------------------------------
    ToolDefinition(
        name="get_releases_upcoming",
        description="Get upcoming economic data releases. Use this to see what economic reports are scheduled in the coming days.",
        parameters=[
            ToolParameter(
                name="days",
                type=ToolParameterType.INTEGER,
                description="Number of days to look ahead (default: 7)",
                required=False,
                default=7,
            ),
        ],
    ),
    ToolDefinition(
        name="get_releases_today",
        description="Get today's economic data releases. Use this to see what reports are scheduled for today.",
        parameters=[],
    ),
    ToolDefinition(
        name="get_releases_week",
        description="Get this week's economic data releases. Provides the full calendar for the current week.",
        parameters=[],
    ),
    ToolDefinition(
        name="get_releases_summary",
        description="Get summary statistics about tracked economic releases.",
        parameters=[],
    ),
    # -------------------------------------------------------------------------
    # Speeches (Fed Communications)
    # -------------------------------------------------------------------------
    ToolDefinition(
        name="get_speeches",
        description="Get recent Fed speeches and communications. Can filter by speaker name.",
        parameters=[
            ToolParameter(
                name="speaker",
                type=ToolParameterType.STRING,
                description="Filter by speaker name (e.g., 'Powell', 'Waller')",
                required=False,
            ),
            ToolParameter(
                name="days",
                type=ToolParameterType.INTEGER,
                description="Number of days of history (default: 30)",
                required=False,
                default=30,
            ),
        ],
    ),
    ToolDefinition(
        name="get_speech",
        description="Get a specific Fed speech with full text by ID.",
        parameters=[
            ToolParameter(
                name="speech_id",
                type=ToolParameterType.INTEGER,
                description="The speech ID",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="get_speakers",
        description="Get list of Fed speakers being tracked (Board of Governors, etc.).",
        parameters=[],
    ),
]


class ScrivenerToolExecutor:
    """Executes tools against the Scrivener client."""

    def __init__(self, client: ScrivenerClient) -> None:
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        """Get all tool definitions for Scrivener."""
        return SCRIVENER_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any], on_update=None) -> ToolResult:
        """Execute a Scrivener tool."""
        try:
            match tool_name:
                case "list_series":
                    data = await self.client.list_series()
                case "search_series":
                    data = await self.client.search_series(parameters["query"])
                case "get_series_info":
                    data = await self.client.get_series_info(parameters["series_id"])
                case "get_latest_value":
                    data = await self.client.get_latest_value(parameters["series_id"])
                case "get_observations":
                    data = await self.client.get_observations(
                        parameters["series_id"],
                        parameters.get("days", 365),
                    )
                case "get_series_change":
                    data = await self.client.get_series_change(
                        parameters["series_id"],
                        parameters.get("periods", 1),
                    )
                case "get_auctions":
                    data = await self.client.get_auctions(
                        parameters.get("security_type"),
                        parameters.get("days", 30),
                    )
                case "get_auction_summary":
                    data = await self.client.get_auction_summary()
                # Releases
                case "get_releases_upcoming":
                    data = await self.client.get_releases_upcoming(
                        parameters.get("days", 7)
                    )
                case "get_releases_today":
                    data = await self.client.get_releases_today()
                case "get_releases_week":
                    data = await self.client.get_releases_week()
                case "get_releases_summary":
                    data = await self.client.get_releases_summary()
                # Speeches
                case "get_speeches":
                    data = await self.client.get_speeches(
                        speaker=parameters.get("speaker"),
                        days=parameters.get("days", 30),
                    )
                case "get_speech":
                    data = await self.client.get_speech(parameters["speech_id"])
                case "get_speakers":
                    data = await self.client.get_speakers()
                case _:
                    return ToolResult.fail(
                        f"Unknown tool: {tool_name}",
                        ErrorType.INVALID_INPUT,
                    )

            return ToolResult.ok(json.dumps(data, indent=2))

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

        except Exception as e:
            return ToolResult.fail(str(e), ErrorType.UNKNOWN)
