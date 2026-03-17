from __future__ import annotations

from pylon.core import Pylon
from pylon.tools.base import ToolDefinition


class _FakeExecutor:
    def __init__(self, tool_names: list[str]) -> None:
        self._tool_names = tool_names

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(name=name, description=f"Tool {name}", parameters=[])
            for name in self._tool_names
        ]


def test_refresh_tools_rebuilds_live_tool_registry(monkeypatch) -> None:
    pylon = Pylon()
    states = iter(
        [
            {"scrivener": _FakeExecutor(["tool_one"])},
            {
                "scrivener": _FakeExecutor(["tool_two"]),
                "canvas": _FakeExecutor(["chart_tool"]),
            },
        ]
    )

    def _fake_build_tool_executors(*, reload_modules: bool = False) -> None:
        executors = next(states)
        pylon._service_executors = executors
        for service_name, executor in executors.items():
            setattr(pylon, f"_{service_name}_executor", executor)

    monkeypatch.setattr(pylon, "_build_tool_executors", _fake_build_tool_executors)

    first = pylon.refresh_tools(reload_modules=False)
    assert first == ["tool_one"]
    assert [tool.name for tool in pylon.get_tools()] == ["tool_one"]

    second = pylon.refresh_tools(reload_modules=False)
    assert second == ["chart_tool", "tool_two"]
    assert [tool.name for tool in pylon.get_tools()] == ["tool_two", "chart_tool"]
    assert set(pylon._service_semaphores.keys()) == {"scrivener", "canvas"}
