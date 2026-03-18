from __future__ import annotations

import json

import pytest

from pylon.tools.oikonomia import OikonomiaToolExecutor


class _FakeOikonomiaClient:
    async def get_latest_publication(self, model_id: str) -> dict:
        return {"model_id": model_id, "summary": {"projection": {"cpi": 2.9}}}

    async def get_latest_publication_for_slot(self, production_slot: str) -> dict:
        return {"production_slot": production_slot, "summary": {"projection": {"cpi": 2.8}}}

    async def list_publications(self) -> list[dict]:
        return [{"model_id": "bistro-v1"}, {"model_id": "bistro-v2"}]


@pytest.mark.asyncio
async def test_get_published_projection_by_model_id() -> None:
    executor = OikonomiaToolExecutor(_FakeOikonomiaClient())

    result = await executor.execute(
        "get_published_projection",
        {"model_id": "bistro-v1"},
    )

    assert result.success is True
    payload = json.loads(result.data)
    assert payload["model_id"] == "bistro-v1"


@pytest.mark.asyncio
async def test_get_published_projection_by_slot() -> None:
    executor = OikonomiaToolExecutor(_FakeOikonomiaClient())

    result = await executor.execute(
        "get_published_projection",
        {"production_slot": "macro_us_inflation"},
    )

    assert result.success is True
    payload = json.loads(result.data)
    assert payload["production_slot"] == "macro_us_inflation"


@pytest.mark.asyncio
async def test_get_published_projection_requires_selector() -> None:
    executor = OikonomiaToolExecutor(_FakeOikonomiaClient())

    result = await executor.execute("get_published_projection", {})

    assert result.success is False
    assert result.error_type is not None


@pytest.mark.asyncio
async def test_list_published_projections() -> None:
    executor = OikonomiaToolExecutor(_FakeOikonomiaClient())

    result = await executor.execute("list_published_projections", {})

    assert result.success is True
    payload = json.loads(result.data)
    assert len(payload) == 2
