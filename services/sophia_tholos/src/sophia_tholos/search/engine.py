"""Vendored from research-store/distill_tool/search.py — hybrid search engine."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sophia_tholos.search.embeddings import EmbeddingConfig, EmbeddingModel


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    run_id: str
    source_path: str | None
    page_number: int
    chunk_index: int
    text: str
    keywords: list[dict]
    lexical_score: float
    semantic_score: float
    hybrid_score: float


@dataclass(frozen=True)
class SearchScope:
    run_ids: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    exclude_source_paths: tuple[str, ...] = ()
    source_path_prefix: str | None = None
    source_path_contains: str | None = None
    min_page_number: int | None = None
    max_page_number: int | None = None
    max_per_source: int | None = None
    date_from: str | None = None
    date_to: str | None = None

    @property
    def has_filters(self) -> bool:
        return any(
            (
                self.run_ids,
                self.source_paths,
                self.exclude_source_paths,
                self.source_path_prefix,
                self.source_path_contains,
                self.min_page_number is not None,
                self.max_page_number is not None,
                self.date_from,
                self.date_to,
            )
        )


class HybridSearchEngine:
    def __init__(
        self,
        db_path: str | Path,
        npz_path: str | Path | None = None,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.db_path = Path(db_path)
        self.npz_path = Path(npz_path) if npz_path else None
        self.model_name = model_name
        self._model: EmbeddingModel | None = None
        self._embedding_chunk_ids: np.ndarray | None = None
        self._embedding_matrix: np.ndarray | None = None
        self._last_semantic_error: str | None = None
        self._load_embeddings()

    def search(
        self,
        query: str,
        limit: int = 10,
        run_id: str | None = None,
        run_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        exclude_source_paths: list[str] | None = None,
        source_path_prefix: str | None = None,
        source_path_contains: str | None = None,
        min_page_number: int | None = None,
        max_page_number: int | None = None,
        max_per_source: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword_weight: float = 0.55,
        semantic_weight: float = 0.45,
        min_lexical_score: float = 0.05,
        semantic_tail_mode: str = "filter",
        semantic_tail_penalty: float = 0.25,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query or limit <= 0:
            return []

        scope = self._build_scope(
            run_id=run_id,
            run_ids=run_ids,
            source_paths=source_paths,
            exclude_source_paths=exclude_source_paths,
            source_path_prefix=source_path_prefix,
            source_path_contains=source_path_contains,
            min_page_number=min_page_number,
            max_page_number=max_page_number,
            max_per_source=max_per_source,
            date_from=date_from,
            date_to=date_to,
        )
        allowed_chunk_ids = self._chunk_ids_for_scope(scope) if scope.has_filters else None
        if allowed_chunk_ids is not None and not allowed_chunk_ids:
            return []

        self._last_semantic_error = None
        candidate_limit = max(limit * 8, 50)

        lexical_scores: dict[str, float] = {}
        if keyword_weight > 0.0 or semantic_weight <= 0.0:
            lexical_scores = self._lexical_scores(
                query,
                scope=scope,
                limit=candidate_limit,
            )

        semantic_scores: dict[str, float] = {}
        if semantic_weight > 0.0:
            semantic_scores = self._semantic_scores(
                query,
                allowed_chunk_ids=allowed_chunk_ids,
                limit=candidate_limit,
            )

        if semantic_weight > 0.0 and not semantic_scores:
            if not lexical_scores:
                lexical_scores = self._lexical_scores(
                    query,
                    scope=scope,
                    limit=candidate_limit,
                )
            semantic_weight = 0.0
            keyword_weight = 1.0
        elif lexical_scores and not semantic_scores:
            semantic_weight = 0.0
            keyword_weight = 1.0
        elif semantic_scores and not lexical_scores:
            semantic_weight = 1.0
            keyword_weight = 0.0

        total_weight = keyword_weight + semantic_weight
        if total_weight <= 0:
            keyword_weight = 1.0
            semantic_weight = 0.0
            total_weight = 1.0
        keyword_weight /= total_weight
        semantic_weight /= total_weight

        all_chunk_ids = set(lexical_scores) | set(semantic_scores)
        if not all_chunk_ids:
            return []

        min_lexical_score = max(0.0, min_lexical_score)
        semantic_tail_penalty = max(0.0, min(1.0, semantic_tail_penalty))
        semantic_tail_mode = semantic_tail_mode.lower().strip()
        if semantic_tail_mode not in {"filter", "demote", "allow"}:
            semantic_tail_mode = "filter"
        lexical_constraints_active = keyword_weight > 0.0 and any(score > 0.0 for score in lexical_scores.values())

        final_scores: list[tuple[str, float, float, float]] = []
        for chunk_id in all_chunk_ids:
            lexical = lexical_scores.get(chunk_id, 0.0)
            semantic = semantic_scores.get(chunk_id, 0.0)
            hybrid = (keyword_weight * lexical) + (semantic_weight * semantic)

            if lexical_constraints_active and semantic > 0.0 and lexical <= 0.0:
                if semantic_tail_mode == "filter":
                    continue
                if semantic_tail_mode == "demote":
                    hybrid *= semantic_tail_penalty

            if lexical_constraints_active and min_lexical_score > 0.0 and 0.0 <= lexical < min_lexical_score:
                hybrid *= lexical / min_lexical_score

            final_scores.append((chunk_id, lexical, semantic, hybrid))

        final_scores.sort(key=lambda row: row[3], reverse=True)
        selection_pool = final_scores[:limit]
        if scope.max_per_source:
            pool_size = min(len(final_scores), max(limit * 6, limit))
            selection_pool = final_scores[:pool_size]
        metadata = self._load_chunk_metadata([row[0] for row in selection_pool])

        results: list[SearchResult] = []
        source_counts: dict[str, int] = {}
        for chunk_id, lexical, semantic, hybrid in selection_pool:
            chunk = metadata.get(chunk_id)
            if not chunk:
                continue
            if scope.max_per_source:
                source_key = str(chunk.get("source_path") or "").strip().lower() or "__none__"
                if source_counts.get(source_key, 0) >= scope.max_per_source:
                    continue
                source_counts[source_key] = source_counts.get(source_key, 0) + 1
            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    run_id=chunk["run_id"],
                    source_path=chunk["source_path"],
                    page_number=chunk["page_number"],
                    chunk_index=chunk["chunk_index"],
                    text=chunk["text"],
                    keywords=chunk["keywords"],
                    lexical_score=lexical,
                    semantic_score=semantic,
                    hybrid_score=hybrid,
                )
            )
            if len(results) >= limit:
                break

        return results

    @property
    def chunk_count(self) -> int:
        """Count total chunks in the SQLite database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0

    @property
    def npz_dims(self) -> tuple[int, int] | None:
        """Return (num_embeddings, embedding_dim) or None if not loaded."""
        if self._embedding_matrix is not None:
            return self._embedding_matrix.shape
        return None

    def get_chunk(self, chunk_id: str) -> dict | None:
        """Fetch a single chunk by ID."""
        meta = self._load_chunk_metadata([chunk_id])
        return meta.get(chunk_id)

    def list_sources(self) -> list[dict]:
        """List distinct source_path values with chunk counts."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT source_path, COUNT(*) as chunk_count "
                    "FROM chunks GROUP BY source_path ORDER BY chunk_count DESC"
                ).fetchall()
            return [{"source_path": row[0], "chunk_count": row[1]} for row in rows]
        except Exception:
            return []

    def _lexical_scores(self, query: str, scope: SearchScope, limit: int) -> dict[str, float]:
        text_query, keyword_query, phrase_query = self._build_lexical_queries(query)
        text_rows = self._fts_query(
            table="chunks_fts",
            query=text_query,
            scope=scope,
            limit=limit,
        )
        keyword_rows = self._fts_query(
            table="keyword_fts",
            query=keyword_query,
            scope=scope,
            limit=limit,
        )
        phrase_rows: list[tuple[str, float]] = []
        if phrase_query:
            phrase_rows = self._fts_query(
                table="chunks_fts",
                query=phrase_query,
                scope=scope,
                limit=limit,
            )

        text_scores = _normalize_bm25(text_rows)
        keyword_scores = _normalize_bm25(keyword_rows)
        phrase_scores = _normalize_bm25(phrase_rows)
        chunk_ids = set(text_scores) | set(keyword_scores) | set(phrase_scores)

        combined: dict[str, float] = {}
        for chunk_id in chunk_ids:
            if phrase_query:
                score = (
                    0.50 * keyword_scores.get(chunk_id, 0.0)
                    + 0.30 * text_scores.get(chunk_id, 0.0)
                    + 0.20 * phrase_scores.get(chunk_id, 0.0)
                )
            else:
                score = 0.65 * keyword_scores.get(chunk_id, 0.0) + 0.35 * text_scores.get(chunk_id, 0.0)
            if score > 0.0:
                combined[chunk_id] = score
        return combined

    def _fts_query(
        self,
        table: str,
        query: str,
        scope: SearchScope,
        limit: int,
    ) -> list[tuple[str, float]]:
        if not query.strip():
            return []

        sql = (
            f"SELECT {table}.chunk_id, bm25({table}) AS score "
            f"FROM {table} "
            f"JOIN chunks c ON c.chunk_id = {table}.chunk_id "
            f"WHERE {table} MATCH ?"
        )
        params: list[object] = [query]
        scope_conditions, scope_params = self._build_scope_sql(scope)
        if scope_conditions:
            sql += " AND " + " AND ".join(scope_conditions)
            params.extend(scope_params)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                safe_query = _sanitize_fts_query(query)
                if not safe_query:
                    return []
                params[0] = safe_query
                rows = conn.execute(sql, params).fetchall()
        return [(str(row[0]), float(row[1])) for row in rows]

    def _semantic_scores(
        self,
        query: str,
        allowed_chunk_ids: set[str] | None,
        limit: int,
    ) -> dict[str, float]:
        if self._embedding_matrix is None or self._embedding_chunk_ids is None:
            return {}
        if self._embedding_matrix.size == 0:
            return {}

        try:
            model = self._get_model()
            query_vector = model.embed([query])[0]
            similarities = self._embedding_matrix @ query_vector
        except Exception as exc:
            message = " ".join(str(exc).split())
            self._last_semantic_error = f"{type(exc).__name__}: {message[:180]}"
            return {}

        if allowed_chunk_ids is not None:
            if not allowed_chunk_ids:
                return {}
            mask = np.array(
                [chunk_id in allowed_chunk_ids for chunk_id in self._embedding_chunk_ids],
                dtype=bool,
            )
            if not np.any(mask):
                return {}
            idxs = np.where(mask)[0]
            subset_scores = similarities[idxs]
            top_n = min(limit, subset_scores.shape[0])
            top_local = np.argpartition(subset_scores, -top_n)[-top_n:]
            top_idxs = idxs[top_local]
        else:
            top_n = min(limit, similarities.shape[0])
            top_idxs = np.argpartition(similarities, -top_n)[-top_n:]

        top_pairs = sorted(
            ((int(i), float(similarities[i])) for i in top_idxs),
            key=lambda row: row[1],
            reverse=True,
        )
        return {
            str(self._embedding_chunk_ids[i]): max(0.0, min(1.0, (score + 1.0) / 2.0))
            for i, score in top_pairs
        }

    @property
    def last_semantic_error(self) -> str | None:
        return self._last_semantic_error

    def _load_chunk_metadata(self, chunk_ids: list[str]) -> dict[str, dict]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT chunk_id, run_id, source_path, page_number, chunk_index, text, keywords_json
                FROM chunks
                WHERE chunk_id IN ({placeholders})
                """,
                chunk_ids,
            ).fetchall()

        metadata: dict[str, dict] = {}
        for row in rows:
            metadata[str(row[0])] = {
                "run_id": str(row[1]),
                "source_path": row[2],
                "page_number": int(row[3]),
                "chunk_index": int(row[4]),
                "text": str(row[5]),
                "keywords": json.loads(row[6]),
            }
        return metadata

    def _chunk_ids_for_scope(self, scope: SearchScope) -> set[str]:
        sql = "SELECT chunk_id FROM chunks c"
        params: list[object] = []
        scope_conditions, scope_params = self._build_scope_sql(scope)
        if scope_conditions:
            sql += " WHERE " + " AND ".join(scope_conditions)
            params.extend(scope_params)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return {str(row[0]) for row in rows}

    @staticmethod
    def _build_scope(
        *,
        run_id: str | None,
        run_ids: list[str] | None,
        source_paths: list[str] | None,
        exclude_source_paths: list[str] | None,
        source_path_prefix: str | None,
        source_path_contains: str | None,
        min_page_number: int | None,
        max_page_number: int | None,
        max_per_source: int | None,
        date_from: str | None,
        date_to: str | None,
    ) -> SearchScope:
        run_scope = _normalize_string_sequence(run_ids)
        if isinstance(run_id, str) and run_id.strip():
            run_scope.add(run_id.strip())

        include_sources = _normalize_string_sequence(source_paths)
        exclude_sources = _normalize_string_sequence(exclude_source_paths)

        prefix = source_path_prefix.strip() if isinstance(source_path_prefix, str) else ""
        contains = source_path_contains.strip() if isinstance(source_path_contains, str) else ""
        min_page = min_page_number if isinstance(min_page_number, int) and min_page_number > 0 else None
        max_page = max_page_number if isinstance(max_page_number, int) and max_page_number > 0 else None
        if min_page is not None and max_page is not None and min_page > max_page:
            min_page, max_page = max_page, min_page

        per_source = max_per_source if isinstance(max_per_source, int) and max_per_source > 0 else None
        if per_source is not None:
            per_source = max(1, min(20, per_source))

        return SearchScope(
            run_ids=tuple(sorted(run_scope)),
            source_paths=tuple(sorted(include_sources)),
            exclude_source_paths=tuple(sorted(exclude_sources)),
            source_path_prefix=prefix or None,
            source_path_contains=contains or None,
            min_page_number=min_page,
            max_page_number=max_page,
            max_per_source=per_source,
            date_from=date_from.strip() if isinstance(date_from, str) and date_from.strip() else None,
            date_to=date_to.strip() if isinstance(date_to, str) and date_to.strip() else None,
        )

    @staticmethod
    def _build_scope_sql(scope: SearchScope) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if scope.run_ids:
            placeholders = ",".join("?" for _ in scope.run_ids)
            conditions.append(f"c.run_id IN ({placeholders})")
            params.extend(scope.run_ids)

        if scope.source_paths:
            placeholders = ",".join("?" for _ in scope.source_paths)
            conditions.append(f"c.source_path IN ({placeholders})")
            params.extend(scope.source_paths)

        if scope.exclude_source_paths:
            placeholders = ",".join("?" for _ in scope.exclude_source_paths)
            conditions.append(f"(c.source_path IS NULL OR c.source_path NOT IN ({placeholders}))")
            params.extend(scope.exclude_source_paths)

        if scope.source_path_prefix:
            conditions.append("LOWER(COALESCE(c.source_path, '')) LIKE ?")
            params.append(f"{scope.source_path_prefix.lower()}%")

        if scope.source_path_contains:
            conditions.append("LOWER(COALESCE(c.source_path, '')) LIKE ?")
            params.append(f"%{scope.source_path_contains.lower()}%")

        if scope.min_page_number is not None:
            conditions.append("c.page_number >= ?")
            params.append(scope.min_page_number)

        if scope.max_page_number is not None:
            conditions.append("c.page_number <= ?")
            params.append(scope.max_page_number)

        source_date_expr = "DATE(COALESCE(NULLIF(c.source_date, ''), c.created_at))"

        if scope.date_from:
            conditions.append(f"{source_date_expr} >= DATE(?)")
            params.append(scope.date_from)

        if scope.date_to:
            conditions.append(f"{source_date_expr} <= DATE(?)")
            params.append(scope.date_to)

        return conditions, params

    def _to_keyword_query(self, query: str) -> str:
        tokens = re.findall(r'"[^"]+"|\w[\w\-]*', query.lower())
        if not tokens:
            return query
        normalized: list[str] = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if token.startswith('"') and token.endswith('"') and len(token) > 2:
                normalized.append(token)
                continue
            if token in {"and", "or", "not", "near"}:
                normalized.append(token.upper())
                continue
            normalized.append(token)
        return " ".join(normalized)

    def _build_lexical_queries(self, query: str) -> tuple[str, str, str | None]:
        if _is_structured_fts_query(query):
            return query, self._to_keyword_query(query), None

        tokens = _extract_query_tokens(query, drop_stopwords=True)
        if not tokens:
            tokens = _extract_query_tokens(query, drop_stopwords=False)
        if not tokens:
            normalized = self._to_keyword_query(query)
            return normalized, normalized, None

        text_query = " AND ".join(tokens)
        keyword_query = " ".join(tokens)
        phrase = _best_query_phrase(query)
        phrase_query = f'"{phrase}"' if phrase else None
        return text_query, keyword_query, phrase_query

    def _get_model(self) -> EmbeddingModel:
        if self._model is None:
            self._model = EmbeddingModel(
                EmbeddingConfig(model_name=self.model_name, batch_size=16, local_files_only=True, quiet=True)
            )
        return self._model

    def _load_embeddings(self) -> None:
        if not self.npz_path or not self.npz_path.exists():
            return
        data = np.load(self.npz_path)
        self._embedding_chunk_ids = data["chunk_ids"].astype(str)
        self._embedding_matrix = data["embeddings"].astype("float32")


def _normalize_bm25(rows: list[tuple[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    values = [row[1] for row in rows]
    best = min(values)
    worst = max(values)
    if abs(worst - best) < 1e-9:
        return {chunk_id: 1.0 for chunk_id, _ in rows}

    normalized: dict[str, float] = {}
    for chunk_id, value in rows:
        normalized[chunk_id] = (worst - value) / (worst - best)
    return normalized


def _sanitize_fts_query(query: str) -> str:
    tokens = re.findall(r"\w[\w\-]*", query.lower())
    return " ".join(tokens)


_FTS_BOOLEAN_TERMS = {"and", "or", "not", "near"}
_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "for",
    "from", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the",
    "their", "these", "this", "to", "was", "were", "with",
}


def _is_structured_fts_query(query: str) -> bool:
    return bool(re.search(r'"|\(|\)|\*|\b(?:and|or|not|near)\b', query, flags=re.IGNORECASE))


def _extract_query_tokens(query: str, drop_stopwords: bool) -> list[str]:
    raw_tokens = re.findall(r"\w[\w\-]*", query.lower())
    tokens: list[str] = []
    for token in raw_tokens:
        if token in _FTS_BOOLEAN_TERMS:
            continue
        if drop_stopwords and token in _QUERY_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _best_query_phrase(query: str) -> str | None:
    raw_tokens = re.findall(r"\w[\w\-]*", query.lower())
    runs: list[list[str]] = []
    current: list[str] = []
    for token in raw_tokens:
        if token in _FTS_BOOLEAN_TERMS or token in _QUERY_STOPWORDS:
            if len(current) >= 2:
                runs.append(current)
            current = []
            continue
        current.append(token)
    if len(current) >= 2:
        runs.append(current)
    if not runs:
        return None
    longest = max(runs, key=len)
    return " ".join(longest)


def _normalize_string_sequence(values: list[str] | tuple[str, ...] | None) -> set[str]:
    normalized: set[str] = set()
    if not values:
        return normalized
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if cleaned:
            normalized.add(cleaned)
    return normalized
