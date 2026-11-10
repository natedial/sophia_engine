from __future__ import annotations

import pytest

from outside_research_agent.analyst import (
    IncompleteAnalystOutput,
    extract_claims,
)
from tests.helpers import load_fixture


def test_two_authors_one_release_share_independence_group():
    payload = load_fixture("analyst_document_maps.json")
    result = extract_claims(payload)
    assert len(result.claims) == 2
    authors = {item["author"] for item in result.claims}
    assert authors == {"Goldman Sachs", "Citi"}
    groups = {item["independence_group"] for item in result.claims}
    assert groups == {"release:cpi-2026-09"}
    occurrence_ids = {item["occurrence_id"] for item in result.claims}
    assert len(occurrence_ids) == 2
    for item in result.claims:
        assert item["namespace"] == "analyst"
        assert "claim:" not in item["occurrence_id"] or item["occurrence_id"] != item.get(
            "independence_group"
        )
        assert item["occurrence_id"] != "claim:inflation_surprise:policy_path:up"
        assert item["locations"]
        assert item["snapshot_hash"]
        assert item["excerpt"]


def test_claim_key_is_not_the_occurrence_id():
    payload = load_fixture("analyst_document_maps.json")
    first = extract_claims(payload).claims[0]
    assert first["occurrence_id"].startswith("11:doc-gs-cpi-2026-09:0:")
    assert "claim:inflation_surprise:policy_path:up" in first["occurrence_id"]


def test_incomplete_analyst_output_is_not_negative_evidence():
    with pytest.raises(IncompleteAnalystOutput, match="did not finish"):
        extract_claims(load_fixture("analyst_incomplete.json"))


def test_incomplete_document_is_skipped_with_warning():
    payload = {
        "documents": [
            {
                "research_id": 7,
                "status": "incomplete",
                "payload_json": {"status": "incomplete"},
            },
            load_fixture("analyst_document_maps.json")["documents"][0],
        ]
    }
    result = extract_claims(payload)
    assert len(result.claims) == 1
    assert result.warnings
    assert "not treated as negative evidence" in result.warnings[0]


def test_generic_bundle_passes_through_unchanged():
    bundle = load_fixture("generic_bundle.json")
    result = extract_claims(bundle)
    assert result.claims == [bundle]


def test_argument_graph_sides_map_to_claims():
    payload = {
        "query": "interpretation_gaps",
        "interpretation_gaps": [
            {
                "referent_key": "release:cpi-2026-09",
                "sides": [
                    {
                        "publisher": "Barclays",
                        "research_id": 16,
                        "claim": "Path moves higher.",
                        "claim_key": "claim:inflation_surprise:policy_path:up",
                        "support_strength": "reasoned",
                        "evidence_text": "quoted CPI surprise",
                        "ref_key": "page 4",
                        "referent_keys": ["release:cpi-2026-09"],
                    }
                ],
            }
        ],
    }
    result = extract_claims(payload)
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim["author"] == "Barclays"
    assert claim["independence_group"] == "release:cpi-2026-09"
    assert claim["locations"] == ["page 4"]
    assert claim["occurrence_id"] != claim["independence_group"]
