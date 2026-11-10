from __future__ import annotations

from pathlib import Path

import pytest

from outside_research_agent.analyst import (
    AnalystUnavailable,
    extract_claims,
    load_analyst_payload,
)
from outside_research_agent.sophia import SophiaCli
from outside_research_agent.workflow import resume_case, run_case
from tests.helpers import (
    CLIENT_SRC,
    EPISTO_SRC,
    demo_observations,
    load_fixture,
    python,
    sophia_env,
    source_tree,
)


def test_analyst_mapping_does_not_need_sophia(tmp_path: Path):
    payload = load_fixture("analyst_document_maps.json")
    result = extract_claims(payload)
    assert result.claims
    assert not list(tmp_path.glob("*.sqlite"))


def test_missing_analyst_payload_is_unavailable(tmp_path: Path):
    missing = tmp_path / "absent.json"
    with pytest.raises(AnalystUnavailable):
        load_analyst_payload(missing)


def test_sophia_explains_case_when_analyst_is_gone(tmp_path: Path):
    analyst = tmp_path / "analyst.json"
    analyst.write_text(
        (Path(__file__).parent / "fixtures" / "analyst_document_maps.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "research.sqlite"
    sophia = SophiaCli(db_path, python=python(), env=sophia_env())
    first = run_case(
        sophia,
        actor="agent-a",
        claims=extract_claims(load_analyst_payload(analyst)).claims,
        observations=demo_observations(),
    )
    analyst.unlink()
    with pytest.raises(AnalystUnavailable):
        load_analyst_payload(analyst)
    resumed = resume_case(SophiaCli(db_path, python=python(), env=sophia_env()), case_id=first["case_id"])
    assert resumed["explanation"]["case_id"] == first["case_id"]
    assert resumed["explanation"]["source_claims"]
    kinds = {item["kind"] for item in resumed["explanation"]["source_claims"]}
    assert kinds == {"source_statement"}


def test_client_does_not_import_engine_or_analyst_packages():
    forbidden = (
        "import sophia_episto",
        "from sophia_episto",
        "import research_analysis_layer",
        "from research_analysis_layer",
        "import nexus",
        "from nexus",
    )
    for path in source_tree(CLIENT_SRC):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path} contains {needle}"


def test_episto_does_not_import_outside_agent():
    for path in source_tree(EPISTO_SRC):
        text = path.read_text(encoding="utf-8")
        assert "outside_research_agent" not in text
        assert "research_analysis_layer" not in text


def test_no_shared_sqlite_between_packages(tmp_path: Path):
    db_path = tmp_path / "research.sqlite"
    oikonomia = tmp_path / "oikonomia.sqlite"
    sophia = SophiaCli(
        db_path,
        python=python(),
        oikonomia_db=oikonomia,
        env=sophia_env(),
    )
    run_case(
        sophia,
        actor="agent-a",
        claims=extract_claims(load_fixture("generic_bundle.json")).claims,
        observations=demo_observations(),
    )
    assert db_path.exists()
    assert db_path != oikonomia
    assert not list(tmp_path.glob("analysis.db"))
