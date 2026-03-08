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
    elif status_code in {400, 422}:
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
            "topics, themes, or data points across all indexed research documents. "
            "For broad questions, run multiple focused queries (different angles) "
            "and synthesize only from cited chunks."
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
            ToolParameter(
                name="keyword_weight",
                type=ToolParameterType.NUMBER,
                description=(
                    "Lexical relevance weight from 0.0 to 1.0. Higher values tighten "
                    "exact-term matching (default: 0.65)."
                ),
                required=False,
                default=0.65,
            ),
            ToolParameter(
                name="semantic_weight",
                type=ToolParameterType.NUMBER,
                description=(
                    "Semantic relevance weight from 0.0 to 1.0. Higher values broaden "
                    "conceptual matching (default: 0.35)."
                ),
                required=False,
                default=0.35,
            ),
            ToolParameter(
                name="min_lexical_score",
                type=ToolParameterType.NUMBER,
                description=(
                    "Minimum lexical score floor from 0.0 to 1.0. Higher values reduce "
                    "semantic drift (default: 0.08)."
                ),
                required=False,
                default=0.08,
            ),
            ToolParameter(
                name="semantic_tail_mode",
                type=ToolParameterType.STRING,
                description=(
                    "How to handle semantic matches with weak lexical support: "
                    "'filter', 'demote', or 'allow' (default: 'demote')."
                ),
                required=False,
                default="demote",
                enum=["filter", "demote", "allow"],
            ),
            ToolParameter(
                name="run_id",
                type=ToolParameterType.STRING,
                description=(
                    "Optional corpus run scope. Restricts results to a single ingest run."
                ),
                required=False,
            ),
            ToolParameter(
                name="run_ids",
                type=ToolParameterType.ARRAY,
                description=(
                    "Optional corpus run scope list. Restricts results to specific ingest runs."
                ),
                required=False,
                items={"type": "string"},
            ),
            ToolParameter(
                name="source_paths",
                type=ToolParameterType.ARRAY,
                description=(
                    "Optional exact source_path allowlist. Restricts results to these sources."
                ),
                required=False,
                items={"type": "string"},
            ),
            ToolParameter(
                name="exclude_source_paths",
                type=ToolParameterType.ARRAY,
                description=(
                    "Optional source_path denylist. Excludes these sources from retrieval."
                ),
                required=False,
                items={"type": "string"},
            ),
            ToolParameter(
                name="source_path_prefix",
                type=ToolParameterType.STRING,
                description=(
                    "Optional source path prefix filter (case-insensitive)."
                ),
                required=False,
            ),
            ToolParameter(
                name="source_path_contains",
                type=ToolParameterType.STRING,
                description=(
                    "Optional source path substring filter (case-insensitive)."
                ),
                required=False,
            ),
            ToolParameter(
                name="min_page_number",
                type=ToolParameterType.INTEGER,
                description=(
                    "Optional minimum page number (inclusive) for matched chunks."
                ),
                required=False,
            ),
            ToolParameter(
                name="max_page_number",
                type=ToolParameterType.INTEGER,
                description=(
                    "Optional maximum page number (inclusive) for matched chunks."
                ),
                required=False,
            ),
            ToolParameter(
                name="max_per_source",
                type=ToolParameterType.INTEGER,
                description=(
                    "Optional cap on number of returned chunks per source_path (1-20)."
                ),
                required=False,
            ),
            ToolParameter(
                name="date_from",
                type=ToolParameterType.STRING,
                description=(
                    "Optional inclusive lower timestamp bound for chunk created_at "
                    "(ISO date or datetime, e.g. '2026-02-19')."
                ),
                required=False,
            ),
            ToolParameter(
                name="date_to",
                type=ToolParameterType.STRING,
                description=(
                    "Optional inclusive upper timestamp bound for chunk created_at "
                    "(ISO date or datetime, e.g. '2026-02-24')."
                ),
                required=False,
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
                    limit = _coerce_int(parameters.get("limit"), default=10, minimum=1, maximum=100)
                    data = await self.client.search(
                        query=parameters["query"],
                        limit=limit,
                        keyword_weight=_coerce_float(
                            parameters.get("keyword_weight"),
                            default=0.65,
                            minimum=0.0,
                            maximum=1.0,
                        ),
                        semantic_weight=_coerce_float(
                            parameters.get("semantic_weight"),
                            default=0.35,
                            minimum=0.0,
                            maximum=1.0,
                        ),
                        min_lexical_score=_coerce_float(
                            parameters.get("min_lexical_score"),
                            default=0.08,
                            minimum=0.0,
                            maximum=1.0,
                        ),
                        semantic_tail_mode=_coerce_tail_mode(
                            parameters.get("semantic_tail_mode"),
                            default="demote",
                        ),
                        run_id=_coerce_optional_str(parameters.get("run_id")),
                        run_ids=_coerce_string_list(
                            parameters.get("run_ids"),
                            max_items=50,
                        ),
                        source_paths=_coerce_string_list(
                            parameters.get("source_paths"),
                            max_items=100,
                        ),
                        exclude_source_paths=_coerce_string_list(
                            parameters.get("exclude_source_paths"),
                            max_items=100,
                        ),
                        source_path_prefix=_coerce_optional_str(
                            parameters.get("source_path_prefix")
                        ),
                        source_path_contains=_coerce_optional_str(
                            parameters.get("source_path_contains")
                        ),
                        min_page_number=_coerce_optional_int(
                            parameters.get("min_page_number"),
                            minimum=1,
                            maximum=100000,
                        ),
                        max_page_number=_coerce_optional_int(
                            parameters.get("max_page_number"),
                            minimum=1,
                            maximum=100000,
                        ),
                        max_per_source=_coerce_optional_int(
                            parameters.get("max_per_source"),
                            minimum=1,
                            maximum=20,
                        ),
                        date_from=_coerce_optional_str(parameters.get("date_from")),
                        date_to=_coerce_optional_str(parameters.get("date_to")),
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


def _coerce_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _coerce_optional_int(
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def _coerce_float(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _coerce_optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _coerce_string_list(value: Any, *, max_items: int) -> list[str] | None:
    if not isinstance(value, list):
        return None
    items: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        cleaned = raw.strip()
        if cleaned and cleaned not in items:
            items.append(cleaned)
        if len(items) >= max_items:
            break
    return items or None


def _coerce_tail_mode(value: Any, *, default: str) -> str:
    if not isinstance(value, str):
        return default
    mode = value.strip().lower()
    if mode in {"filter", "demote", "allow"}:
        return mode
    return default
