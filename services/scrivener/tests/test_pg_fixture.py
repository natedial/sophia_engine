"""The Postgres fixture gives each test an empty schema."""

from src.db.models import Observation


def test_fixture_gives_empty_observations(pg_session) -> None:
    assert pg_session.query(Observation).count() == 0
