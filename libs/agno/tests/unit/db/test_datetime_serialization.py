"""
Unit tests for datetime serialization in database utilities.

These tests verify the fix for GitHub issue #6327:
TypeError: Object of type datetime is not JSON serializable when saving agent sessions.
"""

import json
from datetime import date, datetime, timezone
from uuid import uuid4

from agno.db.utils import CustomJSONEncoder, json_serializer, serialize_session_json_fields
from agno.session.agent import AgentSession


class TestCustomJSONEncoder:
    """Tests for CustomJSONEncoder class."""

    def test_encode_datetime(self):
        """Test that datetime objects are encoded to ISO format."""
        dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = json.dumps({"timestamp": dt}, cls=CustomJSONEncoder)
        assert '"2025-01-15T10:30:00+00:00"' in result

    def test_encode_datetime_naive(self):
        """Test that naive datetime objects are encoded to ISO format."""
        dt = datetime(2025, 1, 15, 10, 30, 0)
        result = json.dumps({"timestamp": dt}, cls=CustomJSONEncoder)
        assert '"2025-01-15T10:30:00"' in result

    def test_encode_date(self):
        """Test that date objects are encoded to ISO format."""
        d = date(2025, 1, 15)
        result = json.dumps({"date": d}, cls=CustomJSONEncoder)
        assert '"2025-01-15"' in result

    def test_encode_uuid(self):
        """Test that UUID objects are encoded to string."""
        uid = uuid4()
        result = json.dumps({"id": uid}, cls=CustomJSONEncoder)
        assert str(uid) in result

    def test_encode_nested_datetime(self):
        """Test that nested datetime objects are encoded."""
        data = {
            "created_at": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            "nested": {
                "updated_at": datetime(2025, 1, 16, 12, 0, 0, tzinfo=timezone.utc),
                "items": [
                    {"date": date(2025, 1, 17)},
                ],
            },
        }
        result = json.dumps(data, cls=CustomJSONEncoder)
        parsed = json.loads(result)

        assert parsed["created_at"] == "2025-01-15T10:00:00+00:00"
        assert parsed["nested"]["updated_at"] == "2025-01-16T12:00:00+00:00"
        assert parsed["nested"]["items"][0]["date"] == "2025-01-17"

    def test_encode_type(self):
        """Test that type objects are encoded to string."""
        result = json.dumps({"type": str}, cls=CustomJSONEncoder)
        assert "<class 'str'>" in result


class TestJsonSerializer:
    """Tests for json_serializer function used by SQLAlchemy engine."""

    def test_serializer_with_datetime(self):
        """Test that json_serializer handles datetime objects."""
        data = {"timestamp": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)}
        result = json_serializer(data)
        assert '"2025-01-15T10:00:00+00:00"' in result

    def test_serializer_with_nested_datetime(self):
        """Test that json_serializer handles nested datetime objects."""
        data = {
            "metadata": {
                "created_at": datetime.now(timezone.utc),
                "nested": {
                    "updated_at": datetime.now(timezone.utc),
                },
            }
        }
        # Should not raise TypeError
        result = json_serializer(data)
        assert isinstance(result, str)

    def test_serializer_returns_valid_json(self):
        """Test that json_serializer returns valid JSON string."""
        data = {
            "id": uuid4(),
            "timestamp": datetime.now(timezone.utc),
            "date": date.today(),
        }
        result = json_serializer(data)
        # Should be valid JSON that can be parsed
        parsed = json.loads(result)
        assert "id" in parsed
        assert "timestamp" in parsed
        assert "date" in parsed


class TestSerializeSessionJsonFields:
    """Tests for serialize_session_json_fields function used by SQLite."""

    def test_serialize_metadata_with_datetime(self):
        """Test that metadata with datetime is serialized correctly."""
        session = {
            "session_id": "test-123",
            "metadata": {
                "created_at": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                "environment": "test",
            },
        }
        result = serialize_session_json_fields(session)

        # metadata should now be a JSON string
        assert isinstance(result["metadata"], str)

        # Parse it back and verify datetime was converted
        parsed = json.loads(result["metadata"])
        assert parsed["created_at"] == "2025-01-15T10:00:00+00:00"
        assert parsed["environment"] == "test"

    def test_serialize_session_data_with_datetime(self):
        """Test that session_data with datetime is serialized correctly."""
        session = {
            "session_id": "test-123",
            "session_data": {
                "last_updated": datetime.now(timezone.utc),
            },
        }
        result = serialize_session_json_fields(session)

        assert isinstance(result["session_data"], str)
        parsed = json.loads(result["session_data"])
        assert "last_updated" in parsed

    def test_serialize_agent_data_with_datetime(self):
        """Test that agent_data with datetime is serialized correctly."""
        session = {
            "session_id": "test-123",
            "agent_data": {
                "agent_id": "agent-1",
                "initialized_at": datetime.now(timezone.utc),
            },
        }
        result = serialize_session_json_fields(session)

        assert isinstance(result["agent_data"], str)
        parsed = json.loads(result["agent_data"])
        assert parsed["agent_id"] == "agent-1"
        assert "initialized_at" in parsed

    def test_serialize_all_fields_with_datetime(self):
        """Test that all JSON fields can contain datetime objects."""
        now = datetime.now(timezone.utc)
        session = {
            "session_id": "test-123",
            "session_data": {"ts": now},
            "agent_data": {"ts": now},
            "team_data": {"ts": now},
            "workflow_data": {"ts": now},
            "metadata": {"ts": now},
            "chat_history": [{"ts": now}],
            "summary": {"ts": now},
            "runs": [{"ts": now}],
        }

        # Should not raise TypeError
        result = serialize_session_json_fields(session)

        # All fields should be JSON strings now
        for field in [
            "session_data",
            "agent_data",
            "team_data",
            "workflow_data",
            "metadata",
            "chat_history",
            "summary",
            "runs",
        ]:
            assert isinstance(result[field], str), f"{field} should be a string"

    def test_serialize_none_fields(self):
        """Test that None fields are handled correctly."""
        session = {
            "session_id": "test-123",
            "metadata": None,
            "session_data": None,
        }
        result = serialize_session_json_fields(session)

        assert result["metadata"] is None
        assert result["session_data"] is None


class TestAgentSessionWithDatetime:
    """Tests for AgentSession serialization with datetime objects."""

    def test_session_to_dict_with_datetime_metadata(self):
        """Test that AgentSession.to_dict works with datetime in metadata."""
        session = AgentSession(
            session_id="test-123",
            agent_id="agent-1",
            metadata={
                "created_at": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                "nested": {
                    "updated_at": datetime.now(timezone.utc),
                },
            },
        )

        # to_dict should work (datetime objects are preserved)
        session_dict = session.to_dict()
        assert "metadata" in session_dict

        # Serializing with CustomJSONEncoder should work
        result = json.dumps(session_dict["metadata"], cls=CustomJSONEncoder)
        assert isinstance(result, str)

    def test_session_to_dict_with_datetime_session_data(self):
        """Test that AgentSession.to_dict works with datetime in session_data."""
        session = AgentSession(
            session_id="test-123",
            agent_id="agent-1",
            session_data={
                "last_activity": datetime.now(timezone.utc),
            },
        )

        session_dict = session.to_dict()

        # Serializing with CustomJSONEncoder should work
        result = json.dumps(session_dict["session_data"], cls=CustomJSONEncoder)
        assert isinstance(result, str)


class TestDatetimeSerializationRegression:
    """Regression tests for GitHub issue #6327."""

    def test_issue_6327_metadata_with_datetime(self):
        """
        Regression test for issue #6327.

        When using datetime objects in agent metadata, the session save
        should not fail with "TypeError: Object of type datetime is not JSON serializable".
        """
        # This is the exact scenario from the bug report
        session_metadata = {
            "created_at": datetime.now(timezone.utc),
            "environment": "test",
            "nested": {
                "last_updated": datetime.now(timezone.utc),
            },
        }

        session = AgentSession(
            session_id="test-session-123",
            agent_id="test-agent",
            user_id="test-user",
            metadata=session_metadata,
        )

        session_dict = session.to_dict()

        # This should NOT raise TypeError
        serialized = serialize_session_json_fields(session_dict.copy())

        # Verify metadata was serialized
        assert isinstance(serialized["metadata"], str)
        parsed = json.loads(serialized["metadata"])
        assert "created_at" in parsed
        assert "nested" in parsed
        assert "last_updated" in parsed["nested"]

    def test_issue_6327_json_serializer_for_postgres(self):
        """
        Test that json_serializer works for PostgreSQL JSONB columns.

        PostgreSQL uses json_serializer parameter on create_engine() to handle
        non-JSON-serializable types in JSONB columns.
        """
        # Simulate what PostgreSQL would store in JSONB
        data = {
            "created_at": datetime.now(timezone.utc),
            "nested": {
                "timestamp": datetime.now(timezone.utc),
            },
        }

        # json_serializer is what SQLAlchemy calls for JSONB serialization
        result = json_serializer(data)

        # Should be valid JSON
        parsed = json.loads(result)
        assert isinstance(parsed["created_at"], str)
        assert isinstance(parsed["nested"]["timestamp"], str)
