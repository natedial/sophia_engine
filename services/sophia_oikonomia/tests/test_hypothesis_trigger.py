"""Tests for hypothesis trigger matching."""

from datetime import UTC, datetime

import pytest

from sophia_oikonomia.core.runtime import OikonomiaRuntime
from sophia_oikonomia.core.types import (
    ExecutionSpec,
    ModelDefinition,
    ModelFamily,
    ModelTrigger,
    TriggerType,
)


def _make_runtime() -> OikonomiaRuntime:
    """Create a runtime without store for testing _match_trigger."""
    runtime = OikonomiaRuntime.__new__(OikonomiaRuntime)
    return runtime


class TestHypothesisTriggerMatching:
    """Tests for HYPOTHESIS trigger matching logic."""

    def test_model_without_subscription_returns_empty(self) -> None:
        """Model without hypothesis_subscriptions should not match."""
        runtime = _make_runtime()
        model = ModelDefinition(
            id="test-model",
            name="Test Model",
            family=ModelFamily.MACRO,
            owner="test",
            execution=ExecutionSpec(adapter_id="test"),
            metadata={},
        )
        trigger = ModelTrigger(
            trigger_type=TriggerType.HYPOTHESIS,
            as_of=datetime.now(UTC),
            reason="fed_25bp",
            payload={"source": "policy", "target": "growth", "hypothesis_type": "fed_policy"},
        )

        matches = runtime._match_trigger(model, trigger)
        assert matches == []

    def test_model_with_wildcard_subscription_matches_all(self) -> None:
        """Model with '*' subscription should match any hypothesis."""
        runtime = _make_runtime()
        model = ModelDefinition(
            id="test-model",
            name="Test Model",
            family=ModelFamily.MACRO,
            owner="test",
            execution=ExecutionSpec(adapter_id="test"),
            metadata={"hypothesis_subscriptions": ["*"]},
        )
        trigger = ModelTrigger(
            trigger_type=TriggerType.HYPOTHESIS,
            as_of=datetime.now(UTC),
            reason="fed_25bp",
            payload={"source": "policy", "target": "growth", "hypothesis_type": "fed_policy"},
        )

        matches = runtime._match_trigger(model, trigger)
        assert matches == ["hypothesis:fed_25bp"]

    def test_model_with_exact_type_subscription_matches(self) -> None:
        """Model with exact hypothesis_type subscription should match."""
        runtime = _make_runtime()
        model = ModelDefinition(
            id="test-model",
            name="Test Model",
            family=ModelFamily.MACRO,
            owner="test",
            execution=ExecutionSpec(adapter_id="test"),
            metadata={"hypothesis_subscriptions": ["fed_policy"]},
        )
        trigger = ModelTrigger(
            trigger_type=TriggerType.HYPOTHESIS,
            as_of=datetime.now(UTC),
            reason="fed_25bp",
            payload={"source": "policy", "target": "growth", "hypothesis_type": "fed_policy"},
        )

        matches = runtime._match_trigger(model, trigger)
        assert matches == ["hypothesis:fed_25bp"]

    def test_model_with_source_subscription_matches(self) -> None:
        """Model with source in subscriptions should match."""
        runtime = _make_runtime()
        model = ModelDefinition(
            id="test-model",
            name="Test Model",
            family=ModelFamily.MACRO,
            owner="test",
            execution=ExecutionSpec(adapter_id="test"),
            metadata={"hypothesis_subscriptions": ["policy"]},
        )
        trigger = ModelTrigger(
            trigger_type=TriggerType.HYPOTHESIS,
            as_of=datetime.now(UTC),
            reason="fed_25bp",
            payload={"source": "policy", "target": "growth"},
        )

        matches = runtime._match_trigger(model, trigger)
        assert matches == ["hypothesis:fed_25bp"]

    def test_model_with_target_subscription_matches(self) -> None:
        """Model with target in subscriptions should match."""
        runtime = _make_runtime()
        model = ModelDefinition(
            id="test-model",
            name="Test Model",
            family=ModelFamily.MACRO,
            owner="test",
            execution=ExecutionSpec(adapter_id="test"),
            metadata={"hypothesis_subscriptions": ["growth"]},
        )
        trigger = ModelTrigger(
            trigger_type=TriggerType.HYPOTHESIS,
            as_of=datetime.now(UTC),
            reason="fed_25bp",
            payload={"source": "policy", "target": "growth"},
        )

        matches = runtime._match_trigger(model, trigger)
        assert matches == ["hypothesis:fed_25bp"]

    def test_model_with_non_matching_subscription_returns_empty(self) -> None:
        """Model with non-matching subscription should not match."""
        runtime = _make_runtime()
        model = ModelDefinition(
            id="test-model",
            name="Test Model",
            family=ModelFamily.MACRO,
            owner="test",
            execution=ExecutionSpec(adapter_id="test"),
            metadata={"hypothesis_subscriptions": ["inflation_hypothesis"]},
        )
        trigger = ModelTrigger(
            trigger_type=TriggerType.HYPOTHESIS,
            as_of=datetime.now(UTC),
            reason="fed_25bp",
            payload={"source": "policy", "target": "growth", "hypothesis_type": "fed_policy"},
        )

        matches = runtime._match_trigger(model, trigger)
        assert matches == []

    def test_multiple_subscriptions_matches_any(self) -> None:
        """Model with multiple subscriptions should match if any match."""
        runtime = _make_runtime()
        model = ModelDefinition(
            id="test-model",
            name="Test Model",
            family=ModelFamily.MACRO,
            owner="test",
            execution=ExecutionSpec(adapter_id="test"),
            metadata={
                "hypothesis_subscriptions": ["inflation_hypothesis", "fed_policy", "ecb_policy"]
            },
        )
        trigger = ModelTrigger(
            trigger_type=TriggerType.HYPOTHESIS,
            as_of=datetime.now(UTC),
            reason="fed_25bp",
            payload={"source": "policy", "target": "growth", "hypothesis_type": "fed_policy"},
        )

        matches = runtime._match_trigger(model, trigger)
        assert matches == ["hypothesis:fed_25bp"]
