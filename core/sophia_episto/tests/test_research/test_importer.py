from sophia_episto.research.contracts import HypothesisRecordStatus
from sophia_episto.research.importer import import_legacy_graph


def test_legacy_graph_import_is_not_promoted(engine):
    result = import_legacy_graph(
        engine,
        {
            "edges": [
                {
                    "source": "inflation",
                    "target": "policy",
                    "probability": 0.7,
                    "confidence": 0.8,
                    "strength": 0.0,
                    "mechanism": "reaction function",
                }
            ]
        },
    )
    assert result["promoted"] is False
    assert result["status"] == "legacy_unassessed"
    snapshot = engine.get_case({"case_id": result["case_id"]})
    hypothesis = snapshot["hypotheses"][0]
    assert hypothesis["assessment"]["status"] == HypothesisRecordStatus.LEGACY_UNASSESSED.value
    assert "intervene" not in hypothesis["assessment"]["allowed_uses"]
    scores = snapshot["scope"]["extra"]["legacy_scores"]
    assert scores[0]["legacy_probability"] == 0.7
