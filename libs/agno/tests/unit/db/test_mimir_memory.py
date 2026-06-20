"""Tests for MimirDb persistent memory provider."""

import json
import os
import tempfile

import pytest

from agno.db.mimir import MimirDb
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession


class TestMimirDbMemory:
    """Test memory CRUD and FTS5 search operations."""

    @pytest.fixture
    def db(self):
        db_path = os.path.join(tempfile.mkdtemp(), "test_mimir.db")
        mdb = MimirDb(db_path=db_path)
        yield mdb
        mdb.close()

    def test_upsert_and_get_memory(self, db):
        mem = UserMemory(memory="User prefers dark mode", topics=["preferences", "ui"])
        result = db.upsert_user_memory(mem)
        assert result.memory_id is not None

        retrieved = db.get_user_memory(result.memory_id)
        assert retrieved is not None
        assert retrieved.memory == "User prefers dark mode"
        assert "preferences" in retrieved.topics

    def test_get_user_memories_by_user(self, db):
        db.upsert_user_memory(UserMemory(
            memory="Memory A", user_id="user1", topics=["topic1"]
        ))
        db.upsert_user_memory(UserMemory(
            memory="Memory B", user_id="user1", topics=["topic2"]
        ))
        db.upsert_user_memory(UserMemory(
            memory="Memory C", user_id="user2", topics=["topic1"]
        ))

        results = db.get_user_memories(user_id="user1")
        assert len(results) == 2

    def test_fts5_search(self, db):
        db.upsert_user_memory(UserMemory(
            memory="User loves Python programming",
            user_id="user1",
            topics=["coding"]
        ))
        db.upsert_user_memory(UserMemory(
            memory="User prefers dark mode",
            user_id="user1",
            topics=["preferences"]
        ))

        results = db.get_user_memories(search_content="Python")
        assert len(results) == 1
        assert "Python" in results[0].memory

    def test_clear_memories(self, db):
        db.upsert_user_memory(UserMemory(memory="Test 1"))
        db.upsert_user_memory(UserMemory(memory="Test 2"))
        assert len(db.get_user_memories()) == 2
        db.clear_memories()
        assert len(db.get_user_memories()) == 0

    def test_delete_user_memory(self, db):
        mem = db.upsert_user_memory(UserMemory(memory="To delete"))
        assert db.get_user_memory(mem.memory_id) is not None
        db.delete_user_memory(mem.memory_id)
        assert db.get_user_memory(mem.memory_id) is None

    def test_get_all_memory_topics(self, db):
        db.upsert_user_memory(UserMemory(memory="M1", topics=["coding", "python"]))
        db.upsert_user_memory(UserMemory(memory="M2", topics=["preferences", "python"]))
        topics = db.get_all_memory_topics()
        assert "python" in topics
        assert "coding" in topics
        assert "preferences" in topics

    def test_update_memory(self, db):
        mem = db.upsert_user_memory(UserMemory(
            memory="Original text", topics=["topic1"]
        ))
        mem.memory = "Updated text"
        mem.topics = ["topic1", "topic2"]
        db.upsert_user_memory(mem)

        retrieved = db.get_user_memory(mem.memory_id)
        assert retrieved.memory == "Updated text"
        assert "topic2" in retrieved.topics

    def test_memory_stats(self, db):
        for i in range(5):
            db.upsert_user_memory(UserMemory(
                memory=f"Memory {i}", user_id="stats-user"
            ))
        stats, total = db.get_user_memory_stats(user_id="stats-user")
        assert total == 5
        assert len(stats) == 5


class TestMimirDbSession:
    """Test session operations."""

    @pytest.fixture
    def db(self):
        db_path = os.path.join(tempfile.mkdtemp(), "test_mimir.db")
        mdb = MimirDb(db_path=db_path)
        yield mdb
        mdb.close()

    def test_upsert_and_get_session(self, db):
        session = AgentSession(
            session_id="sess-1",
            agent_id="agent-1",
            user_id="user-1",
        )
        db.upsert_session(session)

        retrieved = db.get_session("sess-1")
        assert retrieved is not None
        assert retrieved.session_id == "sess-1"

    def test_delete_session(self, db):
        session = AgentSession(session_id="sess-del", agent_id="agent-1")
        db.upsert_session(session)
        assert db.get_session("sess-del") is not None
        db.delete_session("sess-del")
        assert db.get_session("sess-del") is None

    def test_get_sessions_by_user(self, db):
        db.upsert_session(AgentSession(session_id="s1", agent_id="a1", user_id="u1"))
        db.upsert_session(AgentSession(session_id="s2", agent_id="a2", user_id="u1"))
        db.upsert_session(AgentSession(session_id="s3", agent_id="a3", user_id="u2"))

        # deserialize=True returns a flat list of Sessions
        results = db.get_sessions(user_id="u1")
        assert len(results) == 2

        # deserialize=False returns (list, total)
        dicts, total = db.get_sessions(user_id="u1", deserialize=False)
        assert total == 2
        assert len(dicts) == 2


class TestMimirDbTableExists:
    """Test table existence checks."""

    def test_table_exists(self):
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        db = MimirDb(db_path=db_path)
        assert db.table_exists(db.memory_table_name) is True
        assert db.table_exists(db.session_table_name) is True
        assert db.table_exists("nonexistent_table") is False
        db.close()


class TestMimirDbClose:
    """Test connection lifecycle."""

    def test_close_and_reopen(self):
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        db = MimirDb(db_path=db_path)

        # Insert data
        db.upsert_user_memory(UserMemory(memory="Test persistence"))
        db.close()

        # Reopen and verify
        db2 = MimirDb(db_path=db_path)
        memories = db2.get_user_memories()
        assert len(memories) == 1
        assert memories[0].memory == "Test persistence"
        db2.close()
