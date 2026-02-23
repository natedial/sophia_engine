from __future__ import annotations

from dataclasses import dataclass

import pytest

from sophia.config import Settings
from sophia.gateway.runtime import GatewayRuntime


@dataclass
class _ServiceStatus:
    healthy: bool
    status_summary: str


@dataclass
class _Preflight:
    services: dict[str, _ServiceStatus]
    unavailable_tools: list[str]


@pytest.mark.asyncio
async def test_gateway_runtime_create_pylon_uses_tholos_base_url(monkeypatch) -> None:
    captured_config = None

    class FakePylon:
        def __init__(self, config) -> None:
            nonlocal captured_config
            captured_config = config

        async def preflight(self):
            return _Preflight(
                services={"tholos": _ServiceStatus(healthy=True, status_summary="tholos: healthy")},
                unavailable_tools=[],
            )

    import sophia.gateway.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "Pylon", FakePylon)
    settings = Settings(tholos_base_url="http://sophia_tholos:8004")
    runtime = GatewayRuntime(settings=settings)

    await runtime._create_pylon()

    assert captured_config is not None
    assert captured_config.tholos_url == "http://sophia_tholos:8004"
