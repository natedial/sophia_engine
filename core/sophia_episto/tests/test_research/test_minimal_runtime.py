from __future__ import annotations

import re
from pathlib import Path

from sophia_episto.research.engine import ResearchEngine
from tests.test_research.helpers import FakeRunner


REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
MAKEFILE = REPO_ROOT / "Makefile"
RESEARCH_SRC = Path(__file__).resolve().parents[2] / "src" / "sophia_episto" / "research"
PRIMA_ADAPTER = (
    REPO_ROOT / "agents" / "sophia_prima" / "src" / "sophia" / "episto_adapter.py"
)
DISCOVERY = (
    Path(__file__).resolve().parents[2] / "src" / "sophia_episto" / "causal" / "discovery.py"
)
OPTIMIZER = Path(__file__).resolve().parents[2] / "src" / "sophia_episto" / "optimizer"


def _service_block(name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n.*?(?=^  [a-z0-9_]+:|\Z)",
        text,
    )
    assert match is not None, f"missing compose service {name}"
    return match.group(0)


def test_default_compose_is_research_stack():
    default = ("postgres", "scrivener", "sophia_arithmos")
    legacy = (
        "sophia_kampe",
        "sophia_canvas",
        "sophia_dashboard",
        "sophia_tholos",
        "sophia_gateway",
    )
    for name in default:
        assert "profiles:" not in _service_block(name)
    for name in legacy:
        assert 'profiles: ["legacy-assistant"]' in _service_block(name)


def test_makefile_keeps_legacy_stack_opt_in():
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "up-legacy:" in text
    assert "--profile legacy-assistant" in text


def test_research_package_does_not_import_retired_surfaces():
    needles = (
        "sophia_prima",
        "sophia.gateway",
        "sophia_canvas",
        "sophia_forge",
        "sophia_dashboard",
        "telegram",
        "sophia_pylon",
        "sophia_tholos",
        "sophia_episto.optimizer",
        "causallearn",
    )
    for path in RESEARCH_SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            assert needle not in text, f"{path.name} mentions {needle}"


def test_prima_causal_adapter_does_not_load_causal_service():
    text = PRIMA_ADAPTER.read_text(encoding="utf-8")
    assert "get_causal_service" not in text
    assert "return False" in text


def test_pc_algorithm_is_not_registered():
    text = DISCOVERY.read_text(encoding="utf-8")
    assert "def pc_algorithm" not in text
    assert "causallearn" not in text


def test_optimizer_stub_removed():
    assert not OPTIMIZER.exists()


def test_research_engine_runs_without_prima(engine):
    opened = engine.open_case(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "question": "Does the research stack need Prima?",
        }
    )
    assert opened["case_id"]
    assert isinstance(engine.runner, FakeRunner)
