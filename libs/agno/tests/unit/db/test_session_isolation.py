"""Tests for session-level user_id isolation (IDOR prevention).

Verifies that delete_session, delete_sessions, and rename_session
properly filter by user_id when provided, preventing cross-user access.
"""

import pytest

from agno.db.base import SessionType
from agno.db.in_memory.in_memory_db import InMemoryDb


@pytest.fixture
def db():
    db = InMemoryDb()
    db._sessions = [
        {
            "session_id": "s1",
            "user_id": "alice",
            "session_type": "agent",
            "session_data": {"session_name": "Alice Session"},
        },
        {
            "session_id": "s2",
            "user_id": "bob",
            "session_type": "agent",
            "session_data": {"session_name": "Bob Session"},
        },
        {
            "session_id": "s3",
            "user_id": "alice",
            "session_type": "agent",
            "session_data": {"session_name": "Alice Session 2"},
        },
    ]
    return db


class TestDeleteSessionIsolation:
    def test_delete_own_session(self, db):
        result = db.delete_session("s1", user_id="alice")
        assert result is True
        assert len(db._sessions) == 2
        assert all(s["session_id"] != "s1" for s in db._sessions)

    def test_delete_other_users_session_blocked(self, db):
        result = db.delete_session("s1", user_id="bob")
        assert result is False
        assert len(db._sessions) == 3

    def test_delete_without_user_id_wildcard(self, db):
        result = db.delete_session("s1", user_id=None)
        assert result is True
        assert len(db._sessions) == 2

    def test_delete_nonexistent_session(self, db):
        result = db.delete_session("s999", user_id="alice")
        assert result is False
        assert len(db._sessions) == 3


class TestDeleteSessionsIsolation:
    def test_delete_own_sessions(self, db):
        db.delete_sessions(["s1", "s3"], user_id="alice")
        assert len(db._sessions) == 1
        assert db._sessions[0]["session_id"] == "s2"

    def test_delete_mixed_ownership_only_deletes_own(self, db):
        db.delete_sessions(["s1", "s2"], user_id="alice")
        assert len(db._sessions) == 2
        remaining_ids = {s["session_id"] for s in db._sessions}
        assert "s2" in remaining_ids
        assert "s3" in remaining_ids

    def test_delete_without_user_id_wildcard(self, db):
        db.delete_sessions(["s1", "s2"], user_id=None)
        assert len(db._sessions) == 1
        assert db._sessions[0]["session_id"] == "s3"

    def test_delete_other_users_sessions_blocked(self, db):
        db.delete_sessions(["s1", "s3"], user_id="bob")
        assert len(db._sessions) == 3


class TestRenameSessionIsolation:
    def test_rename_own_session(self, db):
        result = db.rename_session(
            session_id="s1",
            session_type=SessionType.AGENT,
            session_name="New Name",
            user_id="alice",
            deserialize=False,
        )
        assert result is not None
        assert result["session_data"]["session_name"] == "New Name"

    def test_rename_other_users_session_blocked(self, db):
        result = db.rename_session(
            session_id="s1",
            session_type=SessionType.AGENT,
            session_name="Hacked Name",
            user_id="bob",
            deserialize=False,
        )
        assert result is None
        assert db._sessions[0]["session_data"]["session_name"] == "Alice Session"

    def test_rename_without_user_id_wildcard(self, db):
        result = db.rename_session(
            session_id="s1",
            session_type=SessionType.AGENT,
            session_name="Wildcard Name",
            user_id=None,
            deserialize=False,
        )
        assert result is not None
        assert result["session_data"]["session_name"] == "Wildcard Name"

    def test_rename_nonexistent_session(self, db):
        result = db.rename_session(
            session_id="s999",
            session_type=SessionType.AGENT,
            session_name="Ghost",
            user_id="alice",
            deserialize=False,
        )
        assert result is None
