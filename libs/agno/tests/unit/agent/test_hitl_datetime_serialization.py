"""
Unit tests for datetime serialization in HITL external_execution payloads.

Verifies fix for issue #5729: non-JSON-serializable types (datetime, UUID, etc.)
in session JSONB fields must be converted to JSON-compatible values before
PostgreSQL JSONB storage.

The fix adds sanitize_jsonb_value() in db/utils.py and applies it in both
PostgresDb and AsyncPostgresDb upsert_session() methods, matching the
serialization pattern already used by SqliteDb.
"""

import json
from datetime import date, datetime, timezone
from uuid import UUID

from agno.db.utils import CustomJSONEncoder, sanitize_jsonb_value
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput


class TestSanitizeJsonbValue:
    """Tests for the sanitize_jsonb_value helper."""

    def test_none_returns_none(self):
        assert sanitize_jsonb_value(None) is None

    def test_basic_types_passthrough(self):
        assert sanitize_jsonb_value("hello") == "hello"
        assert sanitize_jsonb_value(42) == 42
        assert sanitize_jsonb_value(3.14) == 3.14
        assert sanitize_jsonb_value(True) is True

    def test_datetime_converted_to_iso(self):
        dt = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert sanitize_jsonb_value(dt) == "2025-06-15T10:30:00+00:00"

    def test_naive_datetime_converted_to_iso(self):
        dt = datetime(2025, 6, 15, 10, 30, 0)
        assert sanitize_jsonb_value(dt) == "2025-06-15T10:30:00"

    def test_date_converted_to_iso(self):
        d = date(2025, 6, 15)
        assert sanitize_jsonb_value(d) == "2025-06-15"

    def test_uuid_converted_to_string(self):
        u = UUID("12345678-1234-5678-1234-567812345678")
        assert sanitize_jsonb_value(u) == "12345678-1234-5678-1234-567812345678"

    def test_dict_with_datetime(self):
        data = {
            "scheduled_at": datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            "name": "test",
            "count": 5,
        }
        result = sanitize_jsonb_value(data)
        assert result["scheduled_at"] == "2025-06-15T10:00:00+00:00"
        assert result["name"] == "test"
        assert result["count"] == 5

    def test_nested_dict_with_datetime(self):
        data = {
            "outer": {
                "inner_dt": datetime(2025, 1, 1, 0, 0, 0),
                "value": 42,
            }
        }
        result = sanitize_jsonb_value(data)
        assert result["outer"]["inner_dt"] == "2025-01-01T00:00:00"
        assert result["outer"]["value"] == 42

    def test_list_with_datetime(self):
        data = [datetime(2025, 1, 1), "hello", 123]
        result = sanitize_jsonb_value(data)
        assert result[0] == "2025-01-01T00:00:00"
        assert result[1] == "hello"
        assert result[2] == 123

    def test_result_is_json_serializable(self):
        """sanitize_jsonb_value output must be fully JSON-serializable."""
        data = {
            "dt": datetime(2025, 3, 1, 8, 0, 0, tzinfo=timezone.utc),
            "uid": UUID("abcdef01-2345-6789-abcd-ef0123456789"),
            "nested": {
                "dates": [date(2025, 1, 1), date(2025, 12, 31)],
            },
        }
        result = sanitize_jsonb_value(data)
        # Must not raise TypeError
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["dt"] == "2025-03-01T08:00:00+00:00"


class TestToolExecutionSerialization:
    """Tests for ToolExecution serialization with datetime objects in tool_args."""

    def test_tool_args_with_datetime_is_json_serializable_via_encoder(self):
        """ToolExecution.to_dict() with datetime in tool_args should be
        serializable when using CustomJSONEncoder (as the DB layer does)."""
        te = ToolExecution(
            tool_call_id="call_1",
            tool_name="schedule_meeting",
            tool_args={
                "title": "Standup",
                "scheduled_at": datetime(2025, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
            },
        )
        d = te.to_dict()
        # Serializable with CustomJSONEncoder
        result = json.dumps(d, cls=CustomJSONEncoder)
        parsed = json.loads(result)
        assert parsed["tool_args"]["scheduled_at"] == "2025-06-15T09:00:00+00:00"

    def test_tool_args_with_datetime_via_sanitize_jsonb(self):
        """sanitize_jsonb_value should handle ToolExecution dicts."""
        te = ToolExecution(
            tool_call_id="call_2",
            tool_name="create_event",
            tool_args={
                "event_date": date(2025, 12, 25),
                "nested": {"created": datetime(2025, 1, 1, 0, 0, 0)},
            },
            external_execution_required=True,
        )
        d = te.to_dict()
        sanitized = sanitize_jsonb_value(d)
        # Must be fully JSON-serializable with plain json.dumps
        json_str = json.dumps(sanitized)
        parsed = json.loads(json_str)
        assert parsed["tool_args"]["event_date"] == "2025-12-25"
        assert parsed["tool_args"]["nested"]["created"] == "2025-01-01T00:00:00"

    def test_tool_args_none(self):
        """None tool_args should not cause errors."""
        te = ToolExecution(
            tool_call_id="call_3",
            tool_name="no_args_tool",
            tool_args=None,
        )
        d = te.to_dict()
        sanitized = sanitize_jsonb_value(d)
        assert sanitized["tool_args"] is None

    def test_tool_args_without_datetime(self):
        """tool_args without datetime should be unaffected."""
        te = ToolExecution(
            tool_call_id="call_4",
            tool_name="simple_tool",
            tool_args={"key": "value", "count": 5},
        )
        d = te.to_dict()
        sanitized = sanitize_jsonb_value(d)
        assert sanitized["tool_args"] == {"key": "value", "count": 5}


class TestRunOutputSerialization:
    """Tests for RunOutput serialization with datetime objects."""

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


class TestGetFunctionCallForToolExecution:
    """Tests for get_function_call_for_tool_execution with datetime in tool_args."""

    def test_datetime_in_tool_args(self):
        """get_function_call_for_tool_execution should not raise TypeError
        when tool_args contains datetime objects."""
        from agno.utils.tools import get_function_call_for_tool_execution

        te = ToolExecution(
            tool_call_id="call_func",
            tool_name="schedule_meeting",
            tool_args={
                "title": "Standup",
                "scheduled_at": datetime(2025, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
            },
        )
        # Should not raise TypeError (returns None because no functions registered)
        get_function_call_for_tool_execution(te)


class TestSessionDataSerialization:
    """Tests simulating the session serialization path used by PostgresDb.upsert_session."""

    def test_session_data_with_datetime_in_session_state(self):
        """Session data containing datetime in session_state should be
        serializable after sanitize_jsonb_value (as PostgresDb does)."""
        session_data = {
            "session_state": {
                "last_active": datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
                "created": datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "query_count": 5,
            }
        }
        sanitized = sanitize_jsonb_value(session_data)
        # Must be serializable with plain json.dumps (no custom encoder)
        json_str = json.dumps(sanitized)
        parsed = json.loads(json_str)
        assert parsed["session_state"]["last_active"] == "2025-06-15T10:00:00+00:00"
        assert parsed["session_state"]["query_count"] == 5

    def test_runs_with_datetime_in_tool_args(self):
        """Runs field containing ToolExecution with datetime in tool_args
        should be serializable after sanitize_jsonb_value."""
        te = ToolExecution(
            tool_call_id="call_pg",
            tool_name="render_chart",
            tool_args={
                "timestamp": datetime(2025, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
                "data": [{"month": "Jan", "revenue": 5000}],
            },
            external_execution_required=True,
        )
        run_output = RunOutput(run_id="run_pg", tools=[te])
        runs = [run_output.to_dict()]
        sanitized = sanitize_jsonb_value(runs)
        # Must be serializable with plain json.dumps (no custom encoder)
        json_str = json.dumps(sanitized)
        parsed = json.loads(json_str)
        assert parsed[0]["tools"][0]["tool_args"]["timestamp"] == "2025-06-15T09:00:00+00:00"

    def test_metadata_with_uuid_and_datetime(self):
        """Metadata containing UUID and datetime should be serializable
        after sanitize_jsonb_value."""
        metadata = {
            "request_id": UUID("12345678-1234-5678-1234-567812345678"),
            "created_at": datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc),
            "tags": ["production", "v2"],
        }
        sanitized = sanitize_jsonb_value(metadata)
        json_str = json.dumps(sanitized)
        parsed = json.loads(json_str)
        assert parsed["request_id"] == "12345678-1234-5678-1234-567812345678"
        assert parsed["created_at"] == "2025-03-01T00:00:00+00:00"

    def test_round_trip_preserves_data(self):
        """sanitize_jsonb_value round-trip should preserve converted values."""
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
        sanitized = sanitize_jsonb_value(d)
        json_str = json.dumps(sanitized)
        restored = json.loads(json_str)
        te2 = ToolExecution.from_dict(restored)

        assert te2.tool_call_id == "call_rt"
        assert te2.tool_name == "book_flight"
        assert te2.tool_args is not None
        assert te2.tool_args["departure"] == "2025-08-01T06:00:00+00:00"
        assert te2.tool_args["destination"] == "NYC"
        assert te2.result == "Booked"
