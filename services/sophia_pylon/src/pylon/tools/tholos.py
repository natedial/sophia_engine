"""Tool definitions for Tholos research search service."""

import json
from typing import Any

import httpx

from pylon.clients.tholos import TholosClient
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
    elif status_code == 503:
        return ErrorType.SERVICE_UNAVAILABLE, f"Corpus not available: {response_text}"
    elif status_code >= 500:
        return ErrorType.SERVICE_UNAVAILABLE, f"Server error ({status_code}): {response_text}"
    else:
        return ErrorType.UNKNOWN, f"HTTP error {status_code}: {response_text}"


def _classify_request_error(error: httpx.RequestError) -> tuple[ErrorType, str]:
    """Classify a request-level error."""
    if isinstance(error, httpx.TimeoutException):
        return ErrorType.TIMEOUT, f"Request timed out: {error}"
    elif isinstance(error, httpx.ConnectError):
        return ErrorType.SERVICE_UNAVAILABLE, f"Could not connect to tholos: {error}"
    else:
        return ErrorType.SERVICE_UNAVAILABLE, f"Request failed: {error}"


THOLOS_TOOLS = [
    ToolDefinition(
        name="search_research",
        description=(
            "Search the research corpus using hybrid lexical + semantic search. "
            "Returns matching document chunks with text, source file, page number, "
            "and relevance scores. Use this to find research content about specific "
            "topics, themes, or data points across all indexed research documents."
        ),
        parameters=[
            ToolParameter(
                name="query",
                type=ToolParameterType.STRING,
                description="Search query — can be natural language or keyword-based",
                required=True,
            ),
            ToolParameter(
                name="limit",
                type=ToolParameterType.INTEGER,
                description="Maximum number of results to return (default: 10, max: 100)",
                required=False,
                default=10,
            ),
        ],
    ),
    ToolDefinition(
        name="get_research_chunk",
        description=(
            "Retrieve a specific research chunk by its ID. Use this after search_research "
            "to get full details of a particular chunk, or when referencing a previously "
            "seen chunk_id."
        ),
        parameters=[
            ToolParameter(
                name="chunk_id",
                type=ToolParameterType.STRING,
                description="The unique identifier of the chunk to retrieve",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="list_research_sources",
        description=(
            "List all indexed research sources with chunk counts. Use this to understand "
            "what documents are available in the research corpus before searching."
        ),
        parameters=[],
    ),
]


class TholosToolExecutor:
    """Executes tools against the Tholos client."""

    def __init__(self, client: TholosClient) -> None:
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        """Get all tool definitions for Tholos."""
        return THOLOS_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any], on_update=None) -> ToolResult:
        """Execute a Tholos tool."""
        try:
            match tool_name:
                case "search_research":
                    data = await self.client.search(
                        query=parameters["query"],
                        limit=parameters.get("limit", 10),
                    )
                case "get_research_chunk":
                    data = await self.client.get_chunk(
                        chunk_id=parameters["chunk_id"],
                    )
                case "list_research_sources":
                    data = await self.client.list_sources()
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
