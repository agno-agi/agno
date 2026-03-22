"""Regression test for CustomEvent dynamic attributes serialization.

See: https://github.com/agno-agi/agno/issues/7075

CustomEvent allows setting arbitrary attributes via setattr, but these were
lost during to_dict() serialization and not restored on from_dict() round-trip.
"""

from agno.run.agent import CustomEvent


def test_custom_event_dynamic_attributes_survive_to_dict():
    """Test that CustomEvent attributes set via kwargs appear in to_dict()."""
    evt = CustomEvent(event="CustomEvent", my_field="hello", my_data={"key": "value"})

    # Verify attributes exist on the instance
    assert evt.my_field == "hello"
    assert evt.my_data == {"key": "value"}

    # Serialize
    serialized = evt.to_dict()

    # Dynamic attributes should be preserved
    assert "my_field" in serialized, "my_field was lost during to_dict()"
    assert "my_data" in serialized, "my_data was lost during to_dict()"
    assert serialized["my_field"] == "hello"
    assert serialized["my_data"] == {"key": "value"}


def test_custom_event_round_trip():
    """Test that CustomEvent survives a to_dict -> from_dict round-trip."""
    evt = CustomEvent(event="CustomEvent", chart_type="bar", data={"labels": ["a", "b"], "values": [1, 2]})

    serialized = evt.to_dict()
    restored = CustomEvent.from_dict(serialized)

    assert restored.event == "CustomEvent"
    assert restored.chart_type == "bar"
    assert restored.data == {"labels": ["a", "b"], "values": [1, 2]}


def test_custom_event_declared_fields_still_work():
    """Test that declared dataclass fields still work correctly."""
    evt = CustomEvent(event="CustomEvent", tool_call_id="abc123", my_field="test")

    serialized = evt.to_dict()

    assert "tool_call_id" in serialized
    assert serialized["tool_call_id"] == "abc123"
    assert "my_field" in serialized
    assert serialized["my_field"] == "test"
