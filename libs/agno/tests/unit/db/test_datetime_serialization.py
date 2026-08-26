"""
Unit tests for datetime serialization in database utilities.

These tests verify the fix for GitHub issue #6327:
TypeError: Object of type datetime is not JSON serializable when saving agent sessions.
"""

import json
from datetime import date, datetime, timezone
from uuid import uuid4

from agno.db.utils import CustomJSONEncoder, json_serializer
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

    def test_issue_6327_metadata_with_datetime(self, tmp_path):
        """
        Regression test for issue #6327.

        When using datetime objects in agent metadata, the session save
        should not fail with "TypeError: Object of type datetime is not JSON serializable".
        SQLite binds the metadata dict straight to the JSON column, so the
        engine's json_serializer (CustomJSONEncoder) is what handles datetimes.
        """
        from agno.db.base import SessionType
        from agno.db.sqlite import SqliteDb

        # This is the exact scenario from the bug report
        session_metadata = {
            "created_at": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
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

        db = SqliteDb(db_file=str(tmp_path / "issue_6327.db"))

        # This should NOT raise TypeError
        assert db.upsert_session(session) is not None

        stored = db.get_session(session_id="test-session-123", session_type=SessionType.AGENT)
        assert stored is not None
        assert stored.metadata["created_at"] == "2025-01-15T10:00:00+00:00"
        assert stored.metadata["environment"] == "test"
        assert "last_updated" in stored.metadata["nested"]

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
