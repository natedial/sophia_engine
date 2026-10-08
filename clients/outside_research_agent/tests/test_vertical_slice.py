from __future__ import annotations

import json
import subprocess
from pathlib import Path

from outside_research_agent.analyst import extract_claims
from outside_research_agent.sophia import SophiaCli
from outside_research_agent.workflow import resume_case, run_case
from tests.helpers import (
    CLIENT_SRC,
    FIXTURES,
    demo_observations,
    load_fixture,
    python,
    sophia_env,
)


def test_analyst_fixture_opens_case_and_second_client_resumes(tmp_path: Path):
    db_path = tmp_path / "research.sqlite"
    first = SophiaCli(db_path, python=python(), env=sophia_env())
    claims = extract_claims(load_fixture("analyst_document_maps.json")).claims
    result = run_case(
        first,
        actor="agent-a",
        claims=claims,
        observations=demo_observations(),
    )
    assert result["case_id"]
    explanation = result["explanation"]
    assert "inflation surprise" in explanation["question"]
    assert explanation["scope"]["jurisdiction"] == "US"
    assert explanation["scope"]["horizon"] == "4 quarters"
    assert len(explanation["source_claims"]) == 2
    authors = {item["claim"]["author"] for item in explanation["source_claims"]}
    assert authors == {"Goldman Sachs", "Citi"}
    groups = {item["independence_group"] for item in explanation["source_claims"]}
    assert groups == {"release:cpi-2026-09"}
    channels = {item["channel"] for item in explanation["hypotheses"]}
    assert channels == {"reaction_function", "growth_channel"}
    kinds = {
        "source": {item["kind"] for item in explanation["source_claims"]},
        "results": {item["kind"] for item in explanation["computed_results"]},
        "interpretations": {item["kind"] for item in explanation["agent_interpretations"]},
    }
    assert kinds["source"] == {"source_statement"}
    assert kinds["interpretations"] == {"interpretation"}
    assert explanation["agent_interpretations"]
    if explanation["computed_results"]:
        assert kinds["results"] == {"computed_result"}
    assessment = result["assessment"]["assessment"]
    assert "intervene" not in assessment["allowed_uses"]

    second = SophiaCli(db_path, python=python(), env=sophia_env())
    resumed = resume_case(second, case_id=result["case_id"])
    assert resumed["case"]["case_id"] == result["case_id"]
    assert resumed["explanation"]["hypotheses"]
    assert resumed["explanation"]["source_claims"]
    if result["test"].get("result"):
        assert resumed["runs"]
        assert resumed["runs"][0]["result"]["run_id"] == result["test"]["result"]["run_id"]


def test_generic_non_analyst_fixture_works_through_cli_client(tmp_path: Path):
    db_path = tmp_path / "research.sqlite"
    sophia = SophiaCli(db_path, python=python(), env=sophia_env())
    result = run_case(
        sophia,
        actor="agent-a",
        claims=extract_claims(load_fixture("generic_bundle.json")).claims,
        observations=demo_observations(),
    )
    claim = result["explanation"]["source_claims"][0]
    assert claim["claim"]["namespace"] == "generic.notes"
    assert claim["kind"] == "source_statement"


def test_harness_cli_run_and_resume(tmp_path: Path):
    db_path = tmp_path / "research.sqlite"
    observations = tmp_path / "obs.json"
    observations.write_text(json.dumps(demo_observations()), encoding="utf-8")
    env = sophia_env()
    env["PYTHONPATH"] = str(CLIENT_SRC) + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    run = subprocess.run(
        [
            python(),
            "-m",
            "outside_research_agent",
            "run",
            "--db",
            str(db_path),
            "--analyst-json",
            str(FIXTURES / "analyst_document_maps.json"),
            "--observations-json",
            str(observations),
            "--actor",
            "agent-a",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(CLIENT_SRC.parent),
    )
    assert run.returncode == 0, run.stderr
    opened = json.loads(run.stdout)
    resume = subprocess.run(
        [
            python(),
            "-m",
            "outside_research_agent",
            "resume",
            "--db",
            str(db_path),
            "--case-id",
            opened["case_id"],
            "--actor",
            "agent-b",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(CLIENT_SRC.parent),
    )
    assert resume.returncode == 0, resume.stderr
    resumed = json.loads(resume.stdout)
    assert resumed["case"]["case_id"] == opened["case_id"]
    assert resumed["explanation"]["agent_interpretations"]


def test_incomplete_analyst_cli_does_not_open_a_case(tmp_path: Path):
    db_path = tmp_path / "research.sqlite"
    env = sophia_env()
    completed = subprocess.run(
        [
            python(),
            "-m",
            "outside_research_agent",
            "run",
            "--db",
            str(db_path),
            "--analyst-json",
            str(FIXTURES / "analyst_incomplete.json"),
            "--actor",
            "agent-a",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(CLIENT_SRC.parent),
    )
    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["error"]["code"] == "IncompleteAnalystOutput"
    assert not db_path.exists()
