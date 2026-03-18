"""Tool definitions for Oikonomia published projection access."""

import json
from typing import Any

import httpx

from pylon.clients.oikonomia import OikonomiaClient
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
        return ErrorType.NOT_FOUND, f"Projection not found: {response_text}"
    if status_code in {400, 422}:
        return ErrorType.INVALID_INPUT, f"Invalid request: {response_text}"
    if status_code == 503:
        return ErrorType.SERVICE_UNAVAILABLE, f"Oikonomia unavailable: {response_text}"
    if status_code >= 500:
        return ErrorType.SERVICE_UNAVAILABLE, f"Server error ({status_code}): {response_text}"
    return ErrorType.UNKNOWN, f"HTTP error {status_code}: {response_text}"


def _classify_request_error(error: httpx.RequestError) -> tuple[ErrorType, str]:
    """Classify request-level errors."""
    if isinstance(error, httpx.TimeoutException):
        return ErrorType.TIMEOUT, f"Request timed out: {error}"
    if isinstance(error, httpx.ConnectError):
        return ErrorType.SERVICE_UNAVAILABLE, f"Could not connect to oikonomia: {error}"
    return ErrorType.SERVICE_UNAVAILABLE, f"Request failed: {error}"


OIKONOMIA_TOOLS = [
    ToolDefinition(
        name="get_published_projection",
        description=(
            "Fetch the latest published model projection from Oikonomia. "
            "Use either an explicit model_id or a production_slot. "
            "This returns the production-approved published projection, not research output."
        ),
        parameters=[
            ToolParameter(
                name="model_id",
                type=ToolParameterType.STRING,
                description="Explicit model identifier, if known.",
                required=False,
            ),
            ToolParameter(
                name="production_slot",
                type=ToolParameterType.STRING,
                description="Logical production slot such as 'macro_us_inflation'.",
                required=False,
            ),
        ],
    ),
    ToolDefinition(
        name="list_published_projections",
        description=(
            "List published projections currently available from Oikonomia. "
            "Useful for discovering what production-approved model outputs exist."
        ),
        parameters=[],
    ),
]


class OikonomiaToolExecutor:
    """Executes tools against the Oikonomia client."""

    def __init__(self, client: OikonomiaClient) -> None:
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        return OIKONOMIA_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any], on_update=None) -> ToolResult:
        _ = on_update
        try:
            match tool_name:
                case "get_published_projection":
                    model_id = parameters.get("model_id")
                    production_slot = parameters.get("production_slot")
                    if not model_id and not production_slot:
                        return ToolResult.fail(
                            "Either model_id or production_slot is required",
                            ErrorType.INVALID_INPUT,
                        )
                    if model_id:
                        data = await self.client.get_latest_publication(str(model_id))
                    else:
                        data = await self.client.get_latest_publication_for_slot(str(production_slot))
                    return ToolResult.ok(json.dumps(data, indent=2))

                case "list_published_projections":
                    data = await self.client.list_publications()
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
