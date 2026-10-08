"""Transport Analyst public JSON into generic source-claim bundles.

`claim_key` is a semantic grouping key, not an occurrence ID. Occurrence
identity is built from document/analysis identity plus claim location.
Incomplete Analyst output is reported as missing source, never as negative
evidence. This module does not import Analyst packages or read its database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


INCOMPLETE_STATUSES = frozenset({"incomplete", "missing", "failed", "pending"})


class AnalystSurfaceError(Exception):
    """Failure talking to Analyst's public surface."""


class AnalystUnavailable(AnalystSurfaceError):
    """Analyst cannot be reached. Sophia cases remain inspectable without it."""


class IncompleteAnalystOutput(AnalystSurfaceError):
    """Analyst returned incomplete source output. Not negative evidence."""


@dataclass
class TransportResult:
    claims: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def load_analyst_payload(path: Path) -> Any:
    if not path.exists():
        raise AnalystUnavailable(f"Analyst payload is not available: {path}")
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise IncompleteAnalystOutput("Analyst payload is empty")
    return json.loads(raw)


def extract_claims(payload: Any) -> TransportResult:
    """Map Analyst public JSON, or pass through already-generic claims."""
    if _is_incomplete_envelope(payload):
        raise IncompleteAnalystOutput(
            str(payload.get("message") or "Analyst source output is incomplete")
        )
    if _is_generic_claim(payload):
        return TransportResult(claims=[dict(payload)])
    if isinstance(payload, dict) and _generic_claim_list(payload.get("claims")):
        return TransportResult(claims=[dict(item) for item in payload["claims"]])
    if isinstance(payload, list) and payload and all(_is_generic_claim(item) for item in payload):
        return TransportResult(claims=[dict(item) for item in payload])

    warnings: list[str] = []
    claims: list[dict[str, Any]] = []
    documents = list(_iter_documents(payload))
    if documents:
        for document in documents:
            if _document_incomplete(document):
                research_id = document.get("research_id")
                warnings.append(
                    f"research_id={research_id}: incomplete Analyst output; "
                    "not treated as negative evidence"
                )
                continue
            claims.extend(_claims_from_document(document))
        return TransportResult(claims=claims, warnings=warnings)

    for side in _iter_graph_sides(payload):
        claims.append(_claim_from_side(side))
    if not claims:
        raise IncompleteAnalystOutput(
            "Analyst payload contained no document maps, graph sides, or generic claims"
        )
    return TransportResult(claims=claims, warnings=warnings)


def _is_incomplete_envelope(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or "").lower()
    return status in INCOMPLETE_STATUSES and "argument_map" not in payload


def _is_generic_claim(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("namespace"), str)
        and isinstance(payload.get("occurrence_id"), str)
        and "argument_map" not in payload
        and "payload_json" not in payload
    )


def _generic_claim_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_is_generic_claim(item) for item in value)


def _iter_documents(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and _looks_like_document(item):
                yield item
        return
    if not isinstance(payload, dict):
        return
    if isinstance(payload.get("documents"), list):
        for item in payload["documents"]:
            if isinstance(item, dict):
                yield item
        return
    if _looks_like_document(payload):
        yield payload


def _looks_like_document(item: dict[str, Any]) -> bool:
    if "argument_map" in item:
        return True
    nested = item.get("payload_json")
    return isinstance(nested, dict) and "argument_map" in nested


def _document_incomplete(document: dict[str, Any]) -> bool:
    nested = document.get("payload_json") if isinstance(document.get("payload_json"), dict) else {}
    status = str(document.get("status") or nested.get("status") or "").lower()
    if status in INCOMPLETE_STATUSES:
        return True
    argmap = nested.get("argument_map") if nested else document.get("argument_map")
    return not isinstance(argmap, list)


def _claims_from_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    nested = document.get("payload_json") if isinstance(document.get("payload_json"), dict) else {}
    body = nested or document
    argmap = body.get("argument_map") or document.get("argument_map") or []
    research_id = document.get("research_id") or body.get("research_id")
    document_hash = document.get("document_hash") or body.get("document_hash")
    publisher = document.get("publisher") or document.get("source")
    captured = body.get("captured_at")
    meta = body.get("argument_map_meta") if isinstance(body.get("argument_map_meta"), dict) else {}
    captured = captured or meta.get("captured_at")
    published = document.get("source_date") or body.get("published_at")
    version = (
        body.get("analysis_version")
        or meta.get("extractor_version")
        or document.get("latest_analysis_version")
    )
    claims: list[dict[str, Any]] = []
    for index, node in enumerate(argmap):
        if not isinstance(node, dict):
            continue
        claims.append(
            _claim_from_node(
                node,
                research_id=research_id,
                document_hash=document_hash,
                publisher=publisher,
                captured=captured,
                published=published,
                version=version,
                index=index,
            )
        )
    return claims


def _claim_from_node(
    node: dict[str, Any],
    *,
    research_id: Any,
    document_hash: Any,
    publisher: Any,
    captured: Any,
    published: Any,
    version: Any,
    index: int,
) -> dict[str, Any]:
    evidence = [item for item in (node.get("evidence") or []) if isinstance(item, dict)]
    locations = [str(item["ref_key"]) for item in evidence if item.get("ref_key")]
    excerpts = [str(item["text"]) for item in evidence if item.get("text")]
    referents = [str(item["referent_key"]) for item in evidence if item.get("referent_key")]
    claim_key = node.get("claim_key")
    occurrence_id = ":".join(
        str(part)
        for part in (research_id, document_hash or version, index, claim_key)
        if part not in (None, "")
    )
    independence = referents[0] if referents else (str(claim_key) if claim_key else occurrence_id)
    qualifications = [str(item) for item in (node.get("conditions") or [])]
    if node.get("support_strength"):
        qualifications.append(f"analyst_support_strength:{node['support_strength']}")
    parser_versions = {}
    if version:
        parser_versions["analyst_analysis_version"] = str(version)
    content_hash = str(document_hash) if document_hash else None
    snapshot_hash = None
    if content_hash:
        snapshot_hash = (
            content_hash if content_hash.startswith("sha256:") else f"sha256:{content_hash}"
        )
    return {
        "namespace": "analyst",
        "occurrence_id": occurrence_id,
        "document_revision": str(version or document_hash or research_id),
        "content_hash": content_hash,
        "snapshot_hash": snapshot_hash,
        "author": publisher,
        "publisher": publisher,
        "published_at": _as_iso(published),
        "captured_at": _as_iso(captured),
        "locations": locations,
        "excerpt": excerpts[0] if excerpts else node.get("claim"),
        "independence_group": independence,
        "qualifications": qualifications,
        "parser_versions": parser_versions,
    }


def _iter_graph_sides(payload: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(payload, dict):
        return
    buckets = []
    for key in ("interpretation_gaps", "contradictions", "hits"):
        value = payload.get(key)
        if isinstance(value, list):
            buckets.extend(value)
    for item in buckets:
        if not isinstance(item, dict):
            continue
        sides = item.get("sides") or item.get("opposing_sides")
        if isinstance(sides, list):
            for side in sides:
                if isinstance(side, dict):
                    yield side
        elif item.get("claim") or item.get("research_id"):
            yield item


def _claim_from_side(side: dict[str, Any]) -> dict[str, Any]:
    research_id = side.get("research_id")
    claim_key = side.get("claim_key")
    referents = [str(item) for item in (side.get("referent_keys") or []) if item]
    if side.get("referent_key"):
        referents.insert(0, str(side["referent_key"]))
    occurrence_id = ":".join(
        str(part) for part in (research_id, claim_key, side.get("publisher")) if part not in (None, "")
    )
    location = side.get("evidence_ref") or side.get("ref_key")
    locations = [str(location)] if location else []
    return {
        "namespace": "analyst",
        "occurrence_id": occurrence_id,
        "document_revision": str(research_id) if research_id is not None else None,
        "author": side.get("publisher"),
        "publisher": side.get("publisher"),
        "locations": locations,
        "excerpt": side.get("evidence_text") or side.get("claim"),
        "independence_group": referents[0] if referents else claim_key,
        "qualifications": (
            [f"analyst_support_strength:{side['support_strength']}"]
            if side.get("support_strength")
            else []
        ),
        "parser_versions": {},
    }


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "T" not in text:
        return f"{text}T00:00:00Z"
    return text
