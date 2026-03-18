"""Persistence tests for the SQLite-backed Oikonomia store."""

from pathlib import Path

from sophia_oikonomia.core.store import OikonomiaStore
from sophia_oikonomia.core.types import ExecutionSpec, ModelDefinition, ModelFamily, ModelState


def test_store_persists_models_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "oikonomia.db"
    first = OikonomiaStore(db_path)
    definition = ModelDefinition(
        id="bistro-v1",
        name="BISTRO",
        family=ModelFamily.MACRO,
        owner="rates",
        state=ModelState.CHAMPION,
        production_slot="macro_us_inflation",
        execution=ExecutionSpec(adapter_id="bistro"),
    )
    first.save_model(definition)

    second = OikonomiaStore(db_path)
    loaded = second.get_model("bistro-v1")

    assert loaded is not None
    assert loaded.id == "bistro-v1"
    assert loaded.state == ModelState.CHAMPION
