"""
Unit tests for datetime serialization in HITL external_execution payloads.

Verifies fix for issue #5729: datetime objects in tool_args and other
ToolExecution fields must be converted to ISO format strings before
JSON serialization, especially when using Postgres session storage.
"""

import json
from datetime import date, datetime, timezone
from typing import Any, Dict

from agno.models.response import ToolExecution, _sanitize_datetime
from agno.run.agent import RunOutput


class TestSanitizeDatetime:
    """Tests for the _sanitize_datetime helper."""

    def test_datetime_converted_to_iso(self):
        dt = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert _sanitize_datetime(dt) == "2025-06-15T10:30:00+00:00"

    def test_naive_datetime_converted_to_iso(self):
        dt = datetime(2025, 6, 15, 10, 30, 0)
        assert _sanitize_datetime(dt) == "2025-06-15T10:30:00"

    def test_date_converted_to_iso(self):
        d = date(2025, 6, 15)
        assert _sanitize_datetime(d) == "2025-06-15"

    def test_dict_with_datetime(self):
        data: Dict[str, Any] = {
            "scheduled_at": datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            "name": "test",
        }
        result = _sanitize_datetime(data)
        assert result["scheduled_at"] == "2025-06-15T10:00:00+00:00"
        assert result["name"] == "test"

    def test_nested_dict_with_datetime(self):
        data: Dict[str, Any] = {
            "outer": {
                "inner_dt": datetime(2025, 1, 1, 0, 0, 0),
                "value": 42,
            }
        }
        result = _sanitize_datetime(data)
        assert result["outer"]["inner_dt"] == "2025-01-01T00:00:00"
        assert result["outer"]["value"] == 42

    def test_list_with_datetime(self):
        data = [datetime(2025, 1, 1), "hello", 123]
        result = _sanitize_datetime(data)
        assert result[0] == "2025-01-01T00:00:00"
        assert result[1] == "hello"
        assert result[2] == 123

    def test_non_datetime_passthrough(self):
        assert _sanitize_datetime("hello") == "hello"
        assert _sanitize_datetime(42) == 42
        assert _sanitize_datetime(None) is None
        assert _sanitize_datetime(3.14) == 3.14


class TestToolExecutionDatetimeSerialization:
    """Tests for ToolExecution.to_dict() with datetime objects in tool_args."""

    def test_tool_args_with_datetime(self):
        """Datetime in tool_args should be converted to ISO string in to_dict()."""
        te = ToolExecution(
            tool_call_id="call_1",
            tool_name="schedule_meeting",
            tool_args={
                "title": "Standup",
                "scheduled_at": datetime(2025, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
            },
        )
        d = te.to_dict()
        assert d["tool_args"]["scheduled_at"] == "2025-06-15T09:00:00+00:00"
        assert d["tool_args"]["title"] == "Standup"

    def test_tool_args_with_date(self):
        """Date in tool_args should be converted to ISO string in to_dict()."""
        te = ToolExecution(
            tool_call_id="call_2",
            tool_name="create_event",
            tool_args={
                "event_date": date(2025, 12, 25),
            },
        )
        d = te.to_dict()
        assert d["tool_args"]["event_date"] == "2025-12-25"

    def test_tool_args_with_nested_datetime(self):
        """Nested datetime in tool_args should be sanitized."""
        te = ToolExecution(
            tool_call_id="call_3",
            tool_name="complex_tool",
            tool_args={
                "metadata": {
                    "created_at": datetime(2025, 1, 1, 12, 0, 0),
                    "tags": ["a", "b"],
                },
                "items": [
                    {"ts": datetime(2025, 2, 1, 0, 0, 0)},
                ],
            },
        )
        d = te.to_dict()
        assert d["tool_args"]["metadata"]["created_at"] == "2025-01-01T12:00:00"
        assert d["tool_args"]["items"][0]["ts"] == "2025-02-01T00:00:00"

    def test_to_dict_json_serializable(self):
        """to_dict() result should be fully JSON-serializable when tool_args has datetime."""
        te = ToolExecution(
            tool_call_id="call_4",
            tool_name="test_tool",
            tool_args={
                "start": datetime(2025, 3, 1, 8, 0, 0, tzinfo=timezone.utc),
                "end": datetime(2025, 3, 1, 17, 0, 0, tzinfo=timezone.utc),
            },
            external_execution_required=True,
        )
        d = te.to_dict()
        # Should not raise TypeError
        result = json.dumps(d)
        parsed = json.loads(result)
        assert parsed["tool_args"]["start"] == "2025-03-01T08:00:00+00:00"
        assert parsed["tool_args"]["end"] == "2025-03-01T17:00:00+00:00"

    def test_tool_args_none(self):
        """None tool_args should not cause errors."""
        te = ToolExecution(
            tool_call_id="call_5",
            tool_name="no_args_tool",
            tool_args=None,
        )
        d = te.to_dict()
        assert d["tool_args"] is None

    def test_tool_args_without_datetime(self):
        """tool_args without datetime should be unaffected."""
        te = ToolExecution(
            tool_call_id="call_6",
            tool_name="simple_tool",
            tool_args={"key": "value", "count": 5},
        )
        d = te.to_dict()
        assert d["tool_args"] == {"key": "value", "count": 5}


class TestRunOutputDatetimeSerialization:
    """Tests for RunOutput.to_json() with datetime objects in tool payloads."""

    def test_to_json_with_datetime_in_tool_args(self):
        """RunOutput.to_json() should handle datetime in tool_args."""
        te = ToolExecution(
            tool_call_id="call_10",
            tool_name="schedule",
            tool_args={
                "when": datetime(2025, 7, 4, 12, 0, 0, tzinfo=timezone.utc),
            },
            external_execution_required=True,
        )
        run_output = RunOutput(
            run_id="run_1",
            tools=[te],
        )
        # Should not raise TypeError
        json_str = run_output.to_json()
        parsed = json.loads(json_str)
        assert parsed["tools"][0]["tool_args"]["when"] == "2025-07-04T12:00:00+00:00"

    def test_to_json_with_datetime_in_session_state(self):
        """RunOutput.to_json() should handle datetime in session_state."""
        run_output = RunOutput(
            run_id="run_2",
            session_state={
                "last_active": datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            },
        )
        # Should not raise TypeError
        json_str = run_output.to_json()
        parsed = json.loads(json_str)
        assert parsed["session_state"]["last_active"] == "2025-01-01T00:00:00+00:00"


class TestToolExecutionRoundTrip:
    """Test that to_dict -> from_dict round-trip works with datetime in tool_args."""

    def test_round_trip_preserves_iso_strings(self):
        te = ToolExecution(
            tool_call_id="call_rt",
            tool_name="book_flight",
            tool_args={
                "departure": datetime(2025, 8, 1, 6, 0, 0, tzinfo=timezone.utc),
                "destination": "NYC",
            },
            external_execution_required=True,
            result="Booked",
        )
        d = te.to_dict()
        # Serialize to JSON and back
        json_str = json.dumps(d)
        restored_dict = json.loads(json_str)
        te2 = ToolExecution.from_dict(restored_dict)

        assert te2.tool_call_id == "call_rt"
        assert te2.tool_name == "book_flight"
        assert te2.tool_args is not None
        assert te2.tool_args["departure"] == "2025-08-01T06:00:00+00:00"
        assert te2.tool_args["destination"] == "NYC"
        assert te2.result == "Booked"
