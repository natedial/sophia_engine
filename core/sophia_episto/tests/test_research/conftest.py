from __future__ import annotations

from pathlib import Path

import pytest

from sophia_episto.research.engine import ResearchEngine

from tests.test_research.helpers import FakeRunner


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "research.sqlite"


@pytest.fixture
def engine(db_path: Path) -> ResearchEngine:
    return ResearchEngine(db_path, runner=FakeRunner())
