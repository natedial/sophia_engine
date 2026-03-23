"""Tool definitions for Readwise CLI access."""

from __future__ import annotations

import json
from typing import Any

from pylon.clients.readwise import ReadwiseClient, ReadwiseCommandResult
from pylon.tools.base import (
    ErrorType,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _coerce_str_list(value: Any, *, maximum: int = 40) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = [value]
    out: list[str] = []
    for item in raw_values:
        text = str(item)
        if not text:
            continue
        out.append(text)
        if len(out) >= maximum:
            break
    return out


def _classify_cli_failure(result: ReadwiseCommandResult) -> tuple[ErrorType, str]:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    text = stderr or stdout or "Readwise CLI command failed"
    lowered = text.lower()
    if "not logged in" in lowered or "authenticate" in lowered:
        return ErrorType.UNAUTHORIZED, text
    if "could not fetch tools" in lowered or "fetch failed" in lowered:
        return ErrorType.SERVICE_UNAVAILABLE, text
    if "unknown command" in lowered or "no such command" in lowered:
        return ErrorType.INVALID_INPUT, text
    if "readonly mode" in lowered:
        return ErrorType.UNAUTHORIZED, text
    return ErrorType.UNKNOWN, text


def _normalize_command_output(result: ReadwiseCommandResult, *, json_output: bool) -> dict[str, Any]:
    stdout = result.stdout.strip()
    parsed: Any = None
    if json_output and stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = stdout
    elif stdout:
        parsed = stdout

    return {
        "command": " ".join(result.argv[1:]),
        "stdout": parsed,
        "stderr": result.stderr.strip() or None,
        "returncode": result.returncode,
    }


READWISE_TOOLS = [
    ToolDefinition(
        name="readwise_list_commands",
        description=(
            "List cached Readwise CLI commands available to the authenticated user. "
            "Use this if you need to inspect the command surface before invoking a specific command."
        ),
        parameters=[
            ToolParameter(
                name="refresh",
                type=ToolParameterType.BOOLEAN,
                description="Refresh the CLI tool cache before listing commands.",
                required=False,
                default=False,
            ),
        ],
    ),
    ToolDefinition(
        name="readwise_run_command",
        description=(
            "Run an official Readwise CLI command through the installed `readwise` binary. "
            "Pass the exact subcommand name such as `reader-search-documents` and any flags/values "
            "as a flat args array."
        ),
        parameters=[
            ToolParameter(
                name="command",
                type=ToolParameterType.STRING,
                description="Exact Readwise CLI subcommand, for example `reader-search-documents`.",
                required=True,
            ),
            ToolParameter(
                name="args",
                type=ToolParameterType.ARRAY,
                description="Flat argument list, for example [`--query`, `aggregation theory`].",
                required=False,
                items={"type": "string"},
            ),
            ToolParameter(
                name="json_output",
                type=ToolParameterType.BOOLEAN,
                description="Request machine-readable JSON from the CLI when supported.",
                required=False,
                default=True,
            ),
            ToolParameter(
                name="refresh",
                type=ToolParameterType.BOOLEAN,
                description="Refresh the CLI tool cache before running the command.",
                required=False,
                default=False,
            ),
        ],
    ),
]


class ReadwiseToolExecutor:
    """Executes Readwise CLI tools."""

    def __init__(self, client: ReadwiseClient) -> None:
        self.client = client

    def get_tools(self) -> list[ToolDefinition]:
        return READWISE_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any], on_update=None) -> ToolResult:
        _ = on_update
        if not self.client.is_installed:
            return ToolResult.fail("Readwise CLI is not installed", ErrorType.NOT_FOUND)
        if not self.client.is_configured:
            return ToolResult.fail(
                "Readwise CLI is not authenticated",
                ErrorType.UNAUTHORIZED,
            )

        try:
            match tool_name:
                case "readwise_list_commands":
                    refresh = _coerce_bool(parameters.get("refresh"), default=False)
                    if refresh:
                        refresh_result = await self.client.refresh_tools_cache()
                        if refresh_result.returncode != 0:
                            error_type, message = _classify_cli_failure(refresh_result)
                            return ToolResult.fail(message, error_type)
                    payload = {
                        "config": self.client.config_summary(),
                        "commands": self.client.list_cached_tools(),
                    }
                    return ToolResult.ok(json.dumps(payload, indent=2))

                case "readwise_run_command":
                    command = _coerce_optional_str(parameters.get("command"))
                    if not command:
                        return ToolResult.fail("command is required", ErrorType.INVALID_INPUT)
                    json_output = _coerce_bool(parameters.get("json_output"), default=True)
                    refresh = _coerce_bool(parameters.get("refresh"), default=False)
                    args = _coerce_str_list(parameters.get("args"))

                    raw_args: list[str] = []
                    if refresh:
                        raw_args.append("--refresh")
                    raw_args.append(command)
                    raw_args.extend(args)
                    result = await self.client.run_raw(raw_args, json_output=json_output)
                    if result.returncode != 0:
                        error_type, message = _classify_cli_failure(result)
                        return ToolResult.fail(message, error_type)
                    return ToolResult.ok(json.dumps(_normalize_command_output(result, json_output=json_output), indent=2))

                case _:
                    return ToolResult.fail(
                        f"Unknown Readwise tool: {tool_name}",
                        ErrorType.INVALID_INPUT,
                    )
        except TimeoutError:
            return ToolResult.fail("Readwise CLI command timed out", ErrorType.TIMEOUT)
        except Exception as exc:
            return ToolResult.fail(f"Readwise CLI tool failed: {exc}", ErrorType.UNKNOWN)
