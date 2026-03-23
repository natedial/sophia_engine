from __future__ import annotations

import json

import pytest

from pylon.clients.readwise import ReadwiseCommandResult
from pylon.tools.base import ErrorType
from pylon.tools.readwise import ReadwiseToolExecutor


class _FakeReadwiseClient:
    def __init__(self, *, installed: bool = True, configured: bool = True) -> None:
        self.is_installed = installed
        self.is_configured = configured
        self.refresh_calls = 0
        self.raw_calls: list[dict] = []
        self._cached_tools = [
            {
                "tool_name": "reader_search_documents",
                "command": "reader-search-documents",
                "description": "Search Reader documents",
                "read_only": True,
                "input_schema": {},
            },
            {
                "tool_name": "reader_create_document",
                "command": "reader-create-document",
                "description": "Save a Reader document",
                "read_only": False,
                "input_schema": {},
            },
        ]

    async def refresh_tools_cache(self) -> ReadwiseCommandResult:
        self.refresh_calls += 1
        return ReadwiseCommandResult(
            returncode=0,
            stdout="",
            stderr="",
            argv=["readwise", "--refresh", "help"],
        )

    def list_cached_tools(self) -> list[dict]:
        return list(self._cached_tools)

    def config_summary(self) -> dict:
        return {
            "cli_path": "/usr/local/bin/readwise",
            "config_path": "/root/.readwise-cli.json",
            "installed": self.is_installed,
            "configured": self.is_configured,
            "readonly": False,
            "cached_tool_count": len(self._cached_tools),
        }

    async def run_raw(self, args: list[str], *, json_output: bool = False) -> ReadwiseCommandResult:
        self.raw_calls.append({"args": args, "json_output": json_output})
        if args and args[-1] == "boom":
            return ReadwiseCommandResult(
                returncode=1,
                stdout="",
                stderr="Unknown command: boom",
                argv=["readwise", *args],
            )
        return ReadwiseCommandResult(
            returncode=0,
            stdout=json.dumps({"ok": True, "args": args}) if json_output else "ok",
            stderr="",
            argv=["readwise", *args],
        )


@pytest.mark.asyncio
async def test_readwise_list_commands_returns_cached_commands() -> None:
    executor = ReadwiseToolExecutor(_FakeReadwiseClient())

    result = await executor.execute("readwise_list_commands", {"refresh": True})

    assert result.success is True
    payload = json.loads(result.data)
    assert payload["config"]["cached_tool_count"] == 2
    assert payload["commands"][0]["command"] == "reader-search-documents"
    assert payload["commands"][1]["command"] == "reader-create-document"


@pytest.mark.asyncio
async def test_readwise_run_command_passes_through_cli_args() -> None:
    client = _FakeReadwiseClient()
    executor = ReadwiseToolExecutor(client)

    result = await executor.execute(
        "readwise_run_command",
        {
            "command": "reader-search-documents",
            "args": ["--query", "aggregation theory"],
            "json_output": True,
            "refresh": True,
        },
    )

    assert result.success is True
    payload = json.loads(result.data)
    assert payload["stdout"]["ok"] is True

    call = client.raw_calls[0]
    assert call["args"] == ["--refresh", "reader-search-documents", "--query", "aggregation theory"]
    assert call["json_output"] is True


@pytest.mark.asyncio
async def test_readwise_run_command_classifies_cli_errors() -> None:
    executor = ReadwiseToolExecutor(_FakeReadwiseClient())

    result = await executor.execute(
        "readwise_run_command",
        {
            "command": "boom",
        },
    )

    assert result.success is False
    assert result.error_type == ErrorType.INVALID_INPUT


@pytest.mark.asyncio
async def test_readwise_tools_fail_cleanly_without_cli() -> None:
    executor = ReadwiseToolExecutor(_FakeReadwiseClient(installed=False))

    result = await executor.execute("readwise_list_commands", {})

    assert result.success is False
    assert result.error_type == ErrorType.NOT_FOUND


@pytest.mark.asyncio
async def test_readwise_tools_fail_cleanly_without_login() -> None:
    executor = ReadwiseToolExecutor(_FakeReadwiseClient(configured=False))

    result = await executor.execute("readwise_run_command", {"command": "reader-search-documents"})

    assert result.success is False
    assert result.error_type == ErrorType.UNAUTHORIZED
