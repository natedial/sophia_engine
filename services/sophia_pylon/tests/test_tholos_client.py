from __future__ import annotations

import pytest

from pylon.clients.tholos import TholosClient


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> object:
        return self._payload


class _FakeHttpClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    async def get(self, path: str) -> _FakeResponse:
        assert path == "/ready"
        return self.response


@pytest.mark.asyncio
async def test_tholos_health_check_requires_loaded_corpus(monkeypatch) -> None:
    client = TholosClient(base_url="http://example.test")

    async def _fake_get_client():
        return _FakeHttpClient(
            _FakeResponse(status_code=503, payload={"detail": "Corpus not loaded"})
        )

    monkeypatch.setattr(client, "_get_client", _fake_get_client)

    with pytest.raises(RuntimeError, match="Corpus not loaded"):
        await client.health_check()


@pytest.mark.asyncio
async def test_tholos_health_check_accepts_loaded_corpus(monkeypatch) -> None:
    client = TholosClient(base_url="http://example.test")

    async def _fake_get_client():
        return _FakeHttpClient(
            _FakeResponse(status_code=200, payload={"status": "ok", "corpus_available": True})
        )

    monkeypatch.setattr(client, "_get_client", _fake_get_client)

    assert await client.health_check() is True
