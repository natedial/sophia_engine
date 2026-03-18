"""Tool definitions for Brave-backed live web retrieval."""

import json
from typing import Any

import httpx

from pylon.clients.brave import BraveClient
from pylon.tools.base import (
    ErrorType,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


def _classify_http_error(status_code: int, response_text: str) -> tuple[ErrorType, str]:
    """Classify an HTTP error by status code."""
    if status_code in {400, 422}:
        return ErrorType.INVALID_INPUT, f"Invalid Brave request: {response_text}"
    if status_code in {401, 403}:
        return ErrorType.UNAUTHORIZED, "Brave API authentication failed"
    if status_code == 429:
        return ErrorType.RATE_LIMITED, "Brave API rate limit exceeded"
    if status_code == 404:
        return ErrorType.NOT_FOUND, f"Brave resource not found: {response_text}"
    if status_code >= 500:
        return ErrorType.SERVICE_UNAVAILABLE, f"Brave service error ({status_code}): {response_text}"
    return ErrorType.UNKNOWN, f"HTTP error {status_code}: {response_text}"


def _classify_request_error(error: httpx.RequestError) -> tuple[ErrorType, str]:
    """Classify request-level errors."""
    if isinstance(error, httpx.TimeoutException):
        return ErrorType.TIMEOUT, f"Request timed out: {error}"
    if isinstance(error, httpx.ConnectError):
        return ErrorType.SERVICE_UNAVAILABLE, f"Could not connect to Brave: {error}"
    return ErrorType.SERVICE_UNAVAILABLE, f"Request failed: {error}"


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    """Parse an int and clamp it into a valid range."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _coerce_optional_str(value: Any) -> str | None:
    """Return a trimmed string or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_web_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the web search payload compact and citation-friendly."""
    web = payload.get("web", {}) if isinstance(payload, dict) else {}
    results = web.get("results", []) if isinstance(web, dict) else []
    normalized_results: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized_results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "description": item.get("description"),
                "age": item.get("age"),
                "language": item.get("language"),
                "extra_snippets": item.get("extra_snippets"),
            }
        )
    return {
        "query": payload.get("query"),
        "results": normalized_results,
        "total_results": len(normalized_results),
    }


BRAVE_TOOLS = [
    ToolDefinition(
        name="search_web",
        description=(
            "Search the live web through Brave Search and return ranked results with URLs and "
            "snippets. Use this for current events, recent changes, or when you need fresh sources."
        ),
        parameters=[
            ToolParameter(
                name="query",
                type=ToolParameterType.STRING,
                description="The web search query.",
                required=True,
            ),
            ToolParameter(
                name="count",
                type=ToolParameterType.INTEGER,
                description="Maximum number of results to return (default: 5, max: 20).",
                required=False,
                default=5,
            ),
            ToolParameter(
                name="country",
                type=ToolParameterType.STRING,
                description="Optional two-letter country code, such as 'us'.",
                required=False,
            ),
            ToolParameter(
                name="search_lang",
                type=ToolParameterType.STRING,
                description="Optional language preference, such as 'en'.",
                required=False,
            ),
            ToolParameter(
                name="freshness",
                type=ToolParameterType.STRING,
                description="Optional freshness filter such as 'pd', 'pw', 'pm', or 'py'.",
                required=False,
            ),
        ],
    ),
    ToolDefinition(
        name="get_web_context",
        description=(
            "Retrieve Brave LLM Context for a query: extracted page content optimized for agent "
            "grounding, with URLs and source-backed text chunks. Use this when search results alone "
            "are not enough and you need readable source content."
        ),
        parameters=[
            ToolParameter(
                name="query",
                type=ToolParameterType.STRING,
                description="The web query to ground against live sources.",
                required=True,
            ),
            ToolParameter(
                name="count",
                type=ToolParameterType.INTEGER,
                description="Maximum search results Brave should consider (default: 5, max: 20).",
                required=False,
                default=5,
            ),
            ToolParameter(
                name="maximum_number_of_urls",
                type=ToolParameterType.INTEGER,
                description="Maximum URLs to include in the context response (default: 5, max: 20).",
                required=False,
                default=5,
            ),
            ToolParameter(
                name="maximum_number_of_tokens",
                type=ToolParameterType.INTEGER,
                description="Approximate maximum context tokens to return (default: 4096).",
                required=False,
                default=4096,
            ),
            ToolParameter(
                name="context_threshold_mode",
                type=ToolParameterType.STRING,
                description="Relevance threshold mode for context selection.",
                required=False,
                default="balanced",
                enum=["strict", "balanced", "lenient", "disabled"],
            ),
            ToolParameter(
                name="country",
                type=ToolParameterType.STRING,
                description="Optional two-letter country code, such as 'us'.",
                required=False,
            ),
            ToolParameter(
                name="search_lang",
                type=ToolParameterType.STRING,
                description="Optional language preference, such as 'en'.",
                required=False,
            ),
            ToolParameter(
                name="freshness",
                type=ToolParameterType.STRING,
                description="Optional freshness filter such as 'pd', 'pw', 'pm', or 'py'.",
                required=False,
            ),
        ],
    ),
]


class BraveToolExecutor:
    """Executes Brave-backed web tools."""

    def __init__(self, client: BraveClient) -> None:
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        return BRAVE_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any], on_update=None) -> ToolResult:
        _ = on_update
        if not self.client.is_configured:
            return ToolResult.fail(
                "Brave API key is not configured",
                ErrorType.UNAUTHORIZED,
            )

        try:
            match tool_name:
                case "search_web":
                    data = await self.client.search_web(
                        query=str(parameters.get("query", "")).strip(),
                        count=_coerce_int(parameters.get("count"), default=5, minimum=1, maximum=20),
                        country=_coerce_optional_str(parameters.get("country")),
                        search_lang=_coerce_optional_str(parameters.get("search_lang")),
                        freshness=_coerce_optional_str(parameters.get("freshness")),
                    )
                    return ToolResult.ok(json.dumps(_normalize_web_results(data), indent=2))

                case "get_web_context":
                    context_threshold_mode = str(
                        parameters.get("context_threshold_mode", "balanced")
                    ).strip() or "balanced"
                    if context_threshold_mode not in {"strict", "balanced", "lenient", "disabled"}:
                        context_threshold_mode = "balanced"

                    data = await self.client.get_llm_context(
                        query=str(parameters.get("query", "")).strip(),
                        count=_coerce_int(parameters.get("count"), default=5, minimum=1, maximum=20),
                        country=_coerce_optional_str(parameters.get("country")),
                        search_lang=_coerce_optional_str(parameters.get("search_lang")),
                        freshness=_coerce_optional_str(parameters.get("freshness")),
                        maximum_number_of_urls=_coerce_int(
                            parameters.get("maximum_number_of_urls"),
                            default=5,
                            minimum=1,
                            maximum=20,
                        ),
                        maximum_number_of_tokens=_coerce_int(
                            parameters.get("maximum_number_of_tokens"),
                            default=4096,
                            minimum=1024,
                            maximum=32768,
                        ),
                        context_threshold_mode=context_threshold_mode,
                    )
                    return ToolResult.ok(json.dumps(data, indent=2))

                case _:
                    return ToolResult.fail(f"Unknown tool: {tool_name}", ErrorType.INVALID_INPUT)

        except httpx.HTTPStatusError as error:
            error_type, message = _classify_http_error(
                error.response.status_code,
                error.response.text,
            )
            return ToolResult.fail(message, error_type)
        except httpx.RequestError as error:
            error_type, message = _classify_request_error(error)
            return ToolResult.fail(message, error_type)
