from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLIENT_SRC = REPO_ROOT / "clients" / "outside_research_agent" / "src"
EPISTO_SRC = REPO_ROOT / "core" / "sophia_episto" / "src"
OIKONOMIA_SRC = REPO_ROOT / "services" / "sophia_oikonomia" / "src"
ARITHMOS_SRC = REPO_ROOT / "services" / "sophia_arithmos" / "src"


def sophia_env() -> dict[str, str]:
    env = os.environ.copy()
    parts = [
        str(CLIENT_SRC),
        str(EPISTO_SRC),
        str(OIKONOMIA_SRC),
        str(ARITHMOS_SRC),
        env.get("PYTHONPATH", ""),
    ]
    env["PYTHONPATH"] = os.pathsep.join(part for part in parts if part)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def load_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def demo_observations(vintage: str = "v1") -> dict:
    start = date(2020, 1, 1)
    source = []
    target = []
    value = 0.0
    for index in range(40):
        value += 0.08 if index % 3 else -0.03
        day = (start + timedelta(days=index)).isoformat()
        source.append({"date": day, "value": round(value, 4)})
        target.append({"date": day, "value": round(value + 0.05 * index, 4)})
    return {
        "vintage": vintage,
        "as_of": "2026-09-30",
        "window_start": "2020-01-01",
        "window_end": "2020-02-09",
        "source_series": "inflation_surprise",
        "target_series": "policy_path",
        "source_observations": source,
        "target_observations": target,
    }


def source_tree(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if "tests" not in path.parts]


def python() -> str:
    return sys.executable
