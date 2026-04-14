from __future__ import annotations

import asyncio

import pytest

from pylon.core import Pylon, ServiceStatus
from pylon.tools.base import ErrorType, ToolResult


@pytest.mark.asyncio
async def test_preflight_disables_tholos_tools_when_corpus_is_missing(monkeypatch) -> None:
    pylon = Pylon()

    async def _healthy() -> bool:
        return True

    async def _tholos_missing() -> bool:
        raise RuntimeError("Corpus not loaded")

    monkeypatch.setattr(pylon._scrivener_client, "health_check", _healthy)
    monkeypatch.setattr(pylon._arithmos_client, "health_check", _healthy)
    monkeypatch.setattr(pylon._canvas_client, "health_check", _healthy)
    monkeypatch.setattr(pylon._tholos_client, "health_check", _tholos_missing)
    monkeypatch.setattr(pylon._fed_tracker_client, "health_check", _healthy)
    monkeypatch.setattr(pylon._oikonomia_client, "health_check", _healthy)
    monkeypatch.setattr(pylon._readwise_client, "health_check", _healthy)
    monkeypatch.setattr(pylon._brave_client, "health_check", _healthy)

    result = await pylon.preflight()

    assert result.services["tholos"].healthy is False
    assert result.services["tholos"].error == "Corpus not loaded"
    assert "search_research" in result.unavailable_tools
    assert "get_research_chunk" in result.unavailable_tools
    assert "list_research_sources" in result.unavailable_tools
    assert "search_research" not in result.available_tools


@pytest.mark.asyncio
async def test_execute_tool_marks_service_unhealthy_after_runtime_unavailable() -> None:
    pylon = Pylon()

    class _Executor:
        async def execute(self, tool_name: str, parameters: dict[str, object]) -> ToolResult:
            assert tool_name == "search_research"
            return ToolResult.fail("Corpus not loaded", ErrorType.SERVICE_UNAVAILABLE)

    pylon._tool_executors = {"search_research": (_Executor(), "tholos")}
    pylon._service_semaphores = {"tholos": asyncio.Semaphore(1)}
    pylon._service_status = {"tholos": ServiceStatus(name="tholos", healthy=True, latency_ms=1.0)}

    result = await pylon.execute_tool("search_research", {"query": "nfp"})

    assert result.success is False
    assert pylon._service_status["tholos"].healthy is False
    assert pylon._service_status["tholos"].error == "Corpus not loaded"


@pytest.mark.asyncio
async def test_execute_tool_keeps_service_healthy_after_application_error() -> None:
    pylon = Pylon()

    class _Executor:
        async def execute(self, tool_name: str, parameters: dict[str, object]) -> ToolResult:
            assert tool_name == "search_research"
            return ToolResult.fail("Server error (500): Internal Server Error", ErrorType.UNKNOWN)

    pylon._tool_executors = {"search_research": (_Executor(), "tholos")}
    pylon._service_semaphores = {"tholos": asyncio.Semaphore(1)}
    pylon._service_status = {"tholos": ServiceStatus(name="tholos", healthy=True, latency_ms=1.0)}

    result = await pylon.execute_tool("search_research", {"query": "nfp"})

    assert result.success is False
    assert pylon._service_status["tholos"].healthy is True
