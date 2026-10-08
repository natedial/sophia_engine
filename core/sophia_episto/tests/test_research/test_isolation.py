from __future__ import annotations

from pathlib import Path

from sophia_episto.research.engine import ResearchEngine


RESEARCH_ROOT = (
    Path(__file__).resolve().parents[2] / "src" / "sophia_episto" / "research"
)
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_episto_core_dependencies_exclude_stats_libraries():
    text = PYPROJECT.read_text(encoding="utf-8")
    core, extras = text.split("[project.optional-dependencies]", 1)
    for name in ("numpy", "scipy", "statsmodels"):
        assert name not in core
        assert name in extras


def test_research_package_source_has_no_numpy():
    for path in RESEARCH_ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import numpy" not in text
        assert "import scipy" not in text
        assert "import statsmodels" not in text
        assert "from numpy" not in text
        assert "from scipy" not in text
        assert "from statsmodels" not in text


def test_research_engine_imports_without_causal_discovery():
    import importlib
    import sys

    sys.modules.pop("sophia_episto.causal.discovery", None)
    import sophia_episto.research.engine as engine_mod

    importlib.reload(engine_mod)
    assert "sophia_episto.causal.discovery" not in sys.modules
    assert hasattr(engine_mod, "ResearchEngine")


def test_causal_package_import_does_not_load_discovery():
    import sys

    sys.modules.pop("sophia_episto.causal.discovery", None)
    import sophia_episto.causal as causal

    assert "sophia_episto.causal.discovery" not in sys.modules
    assert causal.CausalGraph is not None


def test_two_cases_do_not_share_runs(engine, db_path):
    from tests.test_research.helpers import FakeRunner, snapshot
    from tests.test_research.test_acceptance import _open, _propose

    first = _open(engine)
    second_engine = ResearchEngine(db_path, runner=FakeRunner())
    second = second_engine.open_case(
        {
            "protocol_version": "1",
            "actor": "agent-b",
            "question": "A different case with the same series shape",
        }
    )
    hyp_a = _propose(
        engine, first["case_id"], first["revision"], "agent-a", "reaction_function", "positive", "a"
    )
    hyp_b = _propose(
        second_engine,
        second["case_id"],
        second["revision"],
        "agent-b",
        "reaction_function",
        "positive",
        "b",
    )
    payload_input = snapshot("v1", [0.1, 0.2], [0.2, 0.3]).model_dump()
    run_a = engine.request_test(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": first["case_id"],
            "expected_revision": hyp_a["revision"],
            "idempotency_key": "iso-a",
            "hypothesis_id": hyp_a["hypothesis"]["hypothesis_id"],
            "method": "granger_predictive",
            "input": payload_input,
        }
    )
    run_b = second_engine.request_test(
        {
            "protocol_version": "1",
            "actor": "agent-b",
            "case_id": second["case_id"],
            "expected_revision": hyp_b["revision"],
            "idempotency_key": "iso-b",
            "hypothesis_id": hyp_b["hypothesis"]["hypothesis_id"],
            "method": "granger_predictive",
            "input": payload_input,
        }
    )
    assert run_a["result"]["run_id"] != run_b["result"]["run_id"]
    assert run_a["result"]["fingerprint"] != run_b["result"]["fingerprint"]
    expl_a = engine.explain_case({"case_id": first["case_id"]})
    expl_b = second_engine.explain_case({"case_id": second["case_id"]})
    assert expl_a["computed_results"][0]["run_id"] == run_a["result"]["run_id"]
    assert expl_b["computed_results"][0]["run_id"] == run_b["result"]["run_id"]
    assert len(expl_a["computed_results"]) == 1
    assert len(expl_b["computed_results"]) == 1
