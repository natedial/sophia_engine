from __future__ import annotations

from sophia.agent import SophiaAgent


def test_probe_queries_rank_longer_keywords_first_for_geopolitical_query() -> None:
    probes = SophiaAgent._build_research_probe_queries(
        "what are the takes on GDP and labor impact of the Iran conflict?"
    )
    # The full raw message is always probe 0.
    assert probes[0].lower().startswith("what are the takes")

    # The compact keyword fallback should rank longer content words up front.
    # "conflict" (8), "impact" (6), "labor" (5), "iran" (4), "take" (4),
    # "gdp" (3). "week"/"past"/"our"/etc. are stop words.
    fallback = probes[1]
    assert "conflict" in fallback
    assert "iran" in fallback
    assert "impact" in fallback
    assert "labor" in fallback
    assert "gdp" in fallback
    conflict_idx = fallback.index("conflict")
    gdp_idx = fallback.index("gdp")
    assert conflict_idx < gdp_idx, (
        "Longer content terms should precede shorter ones in the fallback probe"
    )


def test_probe_queries_still_emit_legal_bonus_for_ieepa_tariff() -> None:
    probes = SophiaAgent._build_research_probe_queries(
        "What is the IEEPA tariff supreme court ruling status?"
    )
    # IEEPA legal bonus probe must still be present (rank-independent).
    joined = " | ".join(probes)
    assert "ieepa" in joined
    assert "tariff" in joined
    assert "supreme" in joined
    assert "court" in joined


def test_probe_queries_empty_input_returns_empty() -> None:
    assert SophiaAgent._build_research_probe_queries("") == []


def test_probe_queries_deduplicates() -> None:
    probes = SophiaAgent._build_research_probe_queries("iran iran conflict conflict")
    assert len(probes) == len(set(probes))
