"""Embedding providers and vector helpers for Sophia memory."""

from __future__ import annotations

import json
import logging
import math
import random
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from hashlib import blake2b
from http.client import HTTPMessage
from typing import Protocol

logger = logging.getLogger(__name__)

SparseVector = dict[int, float]

_DEFAULT_HASH_DIM = 256

_STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "have",
    "will",
    "would",
    "about",
    "into",
    "your",
    "you",
    "our",
    "for",
    "are",
    "was",
    "were",
    "can",
    "could",
    "should",
}

_TOKEN_SYNONYMS = {
    "buy": "buy",
    "purchase": "buy",
    "acquire": "buy",
    "sell": "sell",
    "liquidate": "sell",
    "bond": "bond",
    "bonds": "bond",
    "treasury": "bond",
    "treasuries": "bond",
    "note": "bond",
    "notes": "bond",
    "latency": "speed",
    "slow": "speed",
    "slower": "speed",
    "fast": "speed",
    "faster": "speed",
    "quick": "speed",
    "quickly": "speed",
    "performance": "speed",
    "preference": "prefer",
    "prefer": "prefer",
    "prefers": "prefer",
    "like": "prefer",
    "likes": "prefer",
    "love": "prefer",
    "avoid": "avoid",
    "dislike": "avoid",
    "risk": "risk",
    "danger": "risk",
    "issue": "issue",
    "problem": "issue",
    "bug": "issue",
    "error": "issue",
    "implementation": "implement",
    "implementing": "implement",
    "implemented": "implement",
    "code": "implement",
}


class EmbeddingProvider(Protocol):
    """Provider interface for embedding text into sparse vectors."""

    @property
    def name(self) -> str:
        """Stable provider/model identifier."""

    def embed_texts(self, texts: list[str]) -> list[SparseVector]:
        """Embed a batch of texts."""


def cosine_sparse(a: SparseVector, b: SparseVector) -> float:
    """Cosine similarity for sparse vectors (assumes vectors are normalized)."""
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(idx, 0.0) for idx, value in a.items())


def serialize_sparse_vector(vec: SparseVector) -> str:
    """Serialize sparse vector to JSON."""
    return json.dumps({str(idx): value for idx, value in vec.items()})


def deserialize_sparse_vector(payload: str) -> SparseVector:
    """Deserialize sparse vector from JSON."""
    raw = json.loads(payload)
    return {int(idx): float(value) for idx, value in raw.items()}


def _normalize_token(token: str) -> str:
    token = token.lower().strip()
    if not token:
        return token
    if token in _TOKEN_SYNONYMS:
        return _TOKEN_SYNONYMS[token]
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return _TOKEN_SYNONYMS.get(token, token)


def _semantic_terms(text: str) -> list[str]:
    raw_tokens = re.findall(r"[a-z0-9_]{3,}", text.lower())
    tokens = [
        _normalize_token(tok)
        for tok in raw_tokens
        if tok not in _STOPWORDS
    ]
    terms: list[str] = [tok for tok in tokens if tok]
    for i in range(len(tokens) - 1):
        if tokens[i] and tokens[i + 1]:
            terms.append(f"{tokens[i]}_{tokens[i + 1]}")
    return terms


def _normalize_sparse(vec: SparseVector) -> SparseVector:
    norm = math.sqrt(sum(value * value for value in vec.values()))
    if norm <= 0:
        return {}
    return {idx: value / norm for idx, value in vec.items()}


def _dense_to_sparse(values: list[float], min_abs: float = 1e-12) -> SparseVector:
    vec = {
        idx: float(value)
        for idx, value in enumerate(values)
        if abs(value) >= min_abs
    }
    return _normalize_sparse(vec)


def hash_semantic_vector(text: str, *, dim: int = _DEFAULT_HASH_DIM) -> SparseVector:
    """Local semantic-ish embedding based on hashed normalized terms."""
    counts = Counter(_semantic_terms(text))
    if not counts:
        return {}

    vec: SparseVector = {}
    for term, count in counts.items():
        digest = blake2b(term.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest, "little") % dim
        vec[idx] = vec.get(idx, 0.0) + float(count)
    return _normalize_sparse(vec)


@dataclass
class HashEmbeddingProvider:
    """Deterministic local embedding provider."""

    model_name: str = "hash-v1"
    dim: int = _DEFAULT_HASH_DIM

    @property
    def name(self) -> str:
        return self.model_name

    def embed_texts(self, texts: list[str]) -> list[SparseVector]:
        return [hash_semantic_vector(text, dim=self.dim) for text in texts]


@dataclass
class OpenAIEmbeddingProvider:
    """OpenAI-compatible embedding provider using raw HTTP calls."""

    api_key: str
    model_name: str = "text-embedding-3-small"
    base_url: str = "https://api.openai.com/v1"
    timeout_sec: float = 20.0
    retry_max_attempts: int = 4
    retry_base_delay_sec: float = 0.5
    retry_max_delay_sec: float = 8.0
    retry_jitter: bool = True
    _urlopen: object | None = None
    _sleep: object | None = None

    @property
    def name(self) -> str:
        return self.model_name

    def __post_init__(self) -> None:
        if self._urlopen is None:
            self._urlopen = urllib.request.urlopen
        if self._sleep is None:
            self._sleep = time.sleep

    def embed_texts(self, texts: list[str]) -> list[SparseVector]:
        if not texts:
            return []
        payload = json.dumps({"model": self.model_name, "input": texts}).encode("utf-8")
        url = self.base_url.rstrip("/") + "/embeddings"
        request = urllib.request.Request(
            url=url,
            method="POST",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        attempts = max(1, self.retry_max_attempts)
        for attempt in range(attempts):
            try:
                assert self._urlopen is not None
                with self._urlopen(request, timeout=self.timeout_sec) as response:
                    raw = response.read().decode("utf-8")
                return self._parse_embedding_response(raw, expected=len(texts))
            except urllib.error.HTTPError as exc:
                body = self._read_error_body(exc)
                should_retry = self._is_retryable_http_status(exc.code) and attempt < attempts - 1
                if should_retry:
                    retry_after = self._parse_retry_after(exc.headers)
                    delay = self._compute_delay(attempt, retry_after)
                    logger.warning(
                        "openai_embedding_retry_http status=%s attempt=%s/%s delay=%.3fs",
                        exc.code,
                        attempt + 1,
                        attempts,
                        delay,
                    )
                    assert self._sleep is not None
                    self._sleep(delay)
                    continue
                raise RuntimeError(
                    f"OpenAI embedding HTTP {exc.code}: {body[:240]}"
                ) from exc
            except urllib.error.URLError as exc:
                should_retry = attempt < attempts - 1
                if should_retry:
                    delay = self._compute_delay(attempt, None)
                    logger.warning(
                        "openai_embedding_retry_network attempt=%s/%s delay=%.3fs error=%s",
                        attempt + 1,
                        attempts,
                        delay,
                        exc,
                    )
                    assert self._sleep is not None
                    self._sleep(delay)
                    continue
                raise RuntimeError(f"OpenAI embedding network error: {exc}") from exc
        raise RuntimeError("OpenAI embedding retry loop exited unexpectedly")

    def _parse_embedding_response(self, raw: str, *, expected: int) -> list[SparseVector]:
        data = json.loads(raw).get("data", [])
        if len(data) != expected:
            raise RuntimeError(
                f"OpenAI embedding response size mismatch: expected {expected}, got {len(data)}"
            )
        out: list[SparseVector] = []
        for item in data:
            dense = item.get("embedding")
            if not isinstance(dense, list):
                raise RuntimeError("OpenAI embedding payload missing 'embedding' list")
            out.append(_dense_to_sparse([float(v) for v in dense]))
        return out

    @staticmethod
    def _read_error_body(exc: urllib.error.HTTPError) -> str:
        try:
            body = exc.read().decode("utf-8")
            return body
        except Exception:
            return "<unreadable>"

    @staticmethod
    def _is_retryable_http_status(code: int) -> bool:
        return code in {429, 500, 502, 503, 504}

    @staticmethod
    def _parse_retry_after(headers: HTTPMessage | None) -> float | None:
        if not headers:
            return None
        raw = headers.get("Retry-After")
        if not raw:
            return None
        try:
            value = float(raw.strip())
        except ValueError:
            return None
        if value <= 0:
            return None
        return value

    def _compute_delay(self, attempt: int, retry_after: float | None) -> float:
        max_delay = max(0.0, self.retry_max_delay_sec)
        if retry_after is not None:
            return min(max_delay, retry_after)
        base = max(0.0, self.retry_base_delay_sec)
        delay = min(max_delay, base * (2**attempt))
        if self.retry_jitter:
            delay *= random.uniform(0.5, 1.5)
            delay = min(max_delay, delay)
        return delay


def create_embedding_provider(
    *,
    provider: str,
    model: str,
    openai_api_key: str,
    openai_base_url: str,
    timeout_sec: float,
    openai_retry_max_attempts: int = 4,
    openai_retry_base_delay_sec: float = 0.5,
    openai_retry_max_delay_sec: float = 8.0,
    openai_retry_jitter: bool = True,
) -> EmbeddingProvider:
    """Build an embedding provider from config values."""
    normalized = provider.strip().lower()
    if normalized in {"hash", "local", "default"}:
        return HashEmbeddingProvider(model_name=model or "hash-v1")
    if normalized == "openai":
        if not openai_api_key:
            raise ValueError("OpenAI embedding provider requires an API key.")
        model_name = model or "text-embedding-3-small"
        return OpenAIEmbeddingProvider(
            api_key=openai_api_key,
            model_name=model_name,
            base_url=openai_base_url,
            timeout_sec=timeout_sec,
            retry_max_attempts=openai_retry_max_attempts,
            retry_base_delay_sec=openai_retry_base_delay_sec,
            retry_max_delay_sec=openai_retry_max_delay_sec,
            retry_jitter=openai_retry_jitter,
        )
    raise ValueError(f"Unsupported embedding provider: {provider}")
