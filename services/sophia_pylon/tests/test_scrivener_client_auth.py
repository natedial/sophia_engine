"""Scrivener service authentication wiring."""

from pylon.core import Pylon, PylonConfig


def test_pylon_passes_scrivener_service_key_as_header() -> None:
    pylon = Pylon(
        PylonConfig(
            scrivener_url="http://scrivener:8000",
            scrivener_api_key="test-service-key",
        )
    )

    assert pylon._scrivener_client._headers == {
        "X-Scrivener-API-Key": "test-service-key"
    }
