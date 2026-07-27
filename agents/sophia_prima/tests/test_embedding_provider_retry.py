import io
import urllib.error
from http.client import HTTPMessage

import pytest

from sophia.memory.embeddings import OpenAIEmbeddingProvider


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _http_error(code: int, body: str, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = HTTPMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="https://api.openai.com/v1/embeddings",
        code=code,
        msg="error",
        hdrs=headers,
        fp=io.BytesIO(body.encode("utf-8")),
    )


def test_openai_provider_retries_transient_http_and_succeeds() -> None:
    events: list[object] = [
        _http_error(429, '{"error":"rate_limited"}'),
        _FakeResponse(b'{"data":[{"embedding":[1.0,0.0]}]}'),
    ]
    sleeps: list[float] = []

    def fake_urlopen(*args, **kwargs):
        event = events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    provider = OpenAIEmbeddingProvider(
        api_key="k",
        retry_max_attempts=3,
        retry_base_delay_sec=0.2,
        retry_max_delay_sec=1.0,
        retry_jitter=False,
        _urlopen=fake_urlopen,
        _sleep=sleeps.append,
    )

    vectors = provider.embed_texts(["hello"])
    assert len(vectors) == 1
    assert sleeps == [0.2]


def test_openai_provider_honors_retry_after_header() -> None:
    events: list[object] = [
        _http_error(429, '{"error":"rate_limited"}', retry_after="2.5"),
        _FakeResponse(b'{"data":[{"embedding":[1.0]}]}'),
    ]
    sleeps: list[float] = []

    def fake_urlopen(*args, **kwargs):
        event = events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    provider = OpenAIEmbeddingProvider(
        api_key="k",
        retry_max_attempts=3,
        retry_base_delay_sec=0.2,
        retry_max_delay_sec=10.0,
        retry_jitter=False,
        _urlopen=fake_urlopen,
        _sleep=sleeps.append,
    )
    provider.embed_texts(["hello"])
    assert sleeps == [2.5]


def test_openai_provider_does_not_retry_non_retryable_http() -> None:
    call_count = 0
    sleeps: list[float] = []

    def fake_urlopen(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise _http_error(400, '{"error":"bad_request"}')

    provider = OpenAIEmbeddingProvider(
        api_key="k",
        retry_max_attempts=5,
        retry_jitter=False,
        _urlopen=fake_urlopen,
        _sleep=sleeps.append,
    )

    with pytest.raises(RuntimeError, match="HTTP 400"):
        provider.embed_texts(["hello"])
    assert call_count == 1
    assert sleeps == []


def test_openai_provider_retries_network_error() -> None:
    events: list[object] = [
        urllib.error.URLError("temporary"),
        _FakeResponse(b'{"data":[{"embedding":[1.0]}]}'),
    ]
    sleeps: list[float] = []

    def fake_urlopen(*args, **kwargs):
        event = events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    provider = OpenAIEmbeddingProvider(
        api_key="k",
        retry_max_attempts=3,
        retry_base_delay_sec=0.1,
        retry_jitter=False,
        _urlopen=fake_urlopen,
        _sleep=sleeps.append,
    )

    provider.embed_texts(["hello"])
    assert sleeps == [0.1]
