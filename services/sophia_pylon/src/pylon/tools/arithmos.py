"""Tool definitions for Arithmos computation service."""

import json
from typing import Any

import httpx

from pylon.clients.arithmos import ArithmosClient
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


# Tool definitions for Arithmos
ARITHMOS_TOOLS = [
    ToolDefinition(
        name="list_computation_types",
        description=(
            "List all available statistical and econometric computation types with their parameters. "
            "Use this to discover what computations are available before calling compute."
        ),
        parameters=[],
    ),
    ToolDefinition(
        name="compute",
        description=(
            "Execute statistical computations on time series data. Supports multiple computations "
            "in a single call. Available computation categories:\n"
            "- Descriptive stats: mean, median, std_dev, percentile, min_max\n"
            "- Annualization: annualize_mom, annualize_qoq, compound_daily_rate\n"
            "- Period comparisons: yoy_change, yoy_percent, mom_change, mom_percent\n"
            "- Regression: linear_regression, multi_regression, rolling_regression\n"
            "- Transformations: percent_change, difference, log_transform, normalize, moving_average"
        ),
        parameters=[
            ToolParameter(
                name="data",
                type=ToolParameterType.ARRAY,
                description=(
                    "Time series data as array of observations. "
                    "Each observation should have 'date' (ISO format) and 'value' (number). "
                    "Example: [{\"date\": \"2024-01-01\", \"value\": 100}, ...]"
                ),
                required=True,
            ),
            ToolParameter(
                name="computations",
                type=ToolParameterType.ARRAY,
                description=(
                    "Array of computations to perform. Each computation should have 'type' and "
                    "optional parameters. Example: [{\"type\": \"mean\"}, {\"type\": \"linear_regression\"}]"
                ),
                required=True,
            ),
            ToolParameter(
                name="output",
                type=ToolParameterType.STRING,
                description="Output mode: 'latest' (most recent result), 'all' (full series), or 'summary' (statistics only)",
                required=False,
                enum=["latest", "all", "summary"],
                default="latest",
            ),
        ],
    ),
]


class ArithmosToolExecutor:
    """Executes tools against the Arithmos client."""

    def __init__(self, client: ArithmosClient) -> None:
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        """Get all tool definitions for Arithmos."""
        return ARITHMOS_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any], on_update=None) -> ToolResult:
        """Execute an Arithmos tool."""
        try:
            match tool_name:
                case "list_computation_types":
                    data = await self.client.get_computation_types()
                case "compute":
                    data = await self.client.compute(
                        data=parameters["data"],
                        computations=parameters["computations"],
                        output=parameters.get("output", "latest"),
                    )
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
