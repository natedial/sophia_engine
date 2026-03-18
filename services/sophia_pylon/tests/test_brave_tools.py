from __future__ import annotations

import json

import pytest

from pylon.tools.base import ErrorType
from pylon.tools.brave import BraveToolExecutor


class _FakeBraveClient:
    def __init__(self, configured: bool = True) -> None:
        self.is_configured = configured
        self.search_calls: list[dict] = []
        self.context_calls: list[dict] = []

    async def search_web(
        self,
        *,
        query: str,
        count: int = 5,
        country: str | None = None,
        search_lang: str | None = None,
        freshness: str | None = None,
    ) -> dict:
        self.search_calls.append(
            {
                "query": query,
                "count": count,
                "country": country,
                "search_lang": search_lang,
                "freshness": freshness,
            }
        )
        return {
            "query": {"original": query},
            "web": {
                "results": [
                    {
                        "title": "Example result",
                        "url": "https://example.com",
                        "description": "Fresh context",
                    }
                ]
            },
        }

    async def get_llm_context(
        self,
        *,
        query: str,
        count: int = 5,
        country: str | None = None,
        search_lang: str | None = None,
        freshness: str | None = None,
        maximum_number_of_urls: int = 5,
        maximum_number_of_tokens: int = 4096,
        context_threshold_mode: str = "balanced",
    ) -> dict:
        self.context_calls.append(
            {
                "query": query,
                "count": count,
                "country": country,
                "search_lang": search_lang,
                "freshness": freshness,
                "maximum_number_of_urls": maximum_number_of_urls,
                "maximum_number_of_tokens": maximum_number_of_tokens,
                "context_threshold_mode": context_threshold_mode,
            }
        )
        return {
            "query": query,
            "results": [
                {
                    "title": "Example source",
                    "url": "https://example.com/doc",
                    "text": "Grounded content",
                }
            ],
        }


@pytest.mark.asyncio
async def test_search_web_sanitizes_and_returns_results() -> None:
    executor = BraveToolExecutor(_FakeBraveClient())

    result = await executor.execute(
        "search_web",
        {
            "query": "latest treasury refunding announcement",
            "count": "100",
            "country": " us ",
            "search_lang": " en ",
            "freshness": "pw",
        },
    )

    assert result.success is True
    payload = json.loads(result.data)
    assert payload["results"][0]["url"] == "https://example.com"

    call = executor.client.search_calls[0]
    assert call["count"] == 20
    assert call["country"] == "us"
    assert call["search_lang"] == "en"


@pytest.mark.asyncio
async def test_get_web_context_sanitizes_context_parameters() -> None:
    executor = BraveToolExecutor(_FakeBraveClient())

    result = await executor.execute(
        "get_web_context",
        {
            "query": "impact of tariffs on steel prices",
            "count": "0",
            "maximum_number_of_urls": "50",
            "maximum_number_of_tokens": "999999",
            "context_threshold_mode": "weird",
        },
    )

    assert result.success is True
    payload = json.loads(result.data)
    assert payload["results"][0]["url"] == "https://example.com/doc"

    call = executor.client.context_calls[0]
    assert call["count"] == 1
    assert call["maximum_number_of_urls"] == 20
    assert call["maximum_number_of_tokens"] == 32768
    assert call["context_threshold_mode"] == "balanced"


@pytest.mark.asyncio
async def test_brave_tools_fail_cleanly_without_api_key() -> None:
    executor = BraveToolExecutor(_FakeBraveClient(configured=False))

    result = await executor.execute("search_web", {"query": "cpi now"})

    assert result.success is False
    assert result.error_type == ErrorType.UNAUTHORIZED
