"""Postgres-backed test fixture.

Tests that need real Postgres behaviour (ON CONFLICT, DISTINCT ON) use
``pg_session``. It connects to ``SCRIVENER_TEST_DATABASE_URL`` and skips the
test when that variable is unset. Point it at a throwaway database: every
table is emptied after each test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.db import connection
from src.db.models import Base

TEST_URL_ENV = "SCRIVENER_TEST_DATABASE_URL"


@pytest.fixture(scope="session")
def pg_engine():
    url = os.environ.get(TEST_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_URL_ENV} is not set")
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine, monkeypatch) -> Iterator[Session]:
    """A session on an empty schema; code under test shares the same engine."""
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    monkeypatch.setattr(connection, "_engine", pg_engine)
    monkeypatch.setattr(connection, "_session_factory", factory)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        with pg_engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
