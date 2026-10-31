"""Unit tests for InMemoryDb memory operations."""

import pytest

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.db.schemas.memory import UserMemory


@pytest.fixture
def db():
    db = InMemoryDb()
    db._memories = [
        {"memory_id": "m1", "user_id": "alice", "memory": "alice thing", "topics": ["pref", "ui"]},
        {"memory_id": "m2", "user_id": "bob", "memory": "bob thing", "topics": ["code", "ts"]},
    ]
    return db


class TestGetAllMemoryTopicsIsolation:
    def test_returns_all_topics_when_no_user_filter(self, db):
        assert set(db.get_all_memory_topics()) == {"pref", "ui", "code", "ts"}

    def test_returns_only_own_topics_when_filtered_by_user(self, db):
        assert set(db.get_all_memory_topics(user_id="alice")) == {"pref", "ui"}
        assert set(db.get_all_memory_topics(user_id="bob")) == {"code", "ts"}

    def test_returns_empty_for_unknown_user(self, db):
        assert db.get_all_memory_topics(user_id="nobody") == []


class TestUpsertUserMemoryDetachesCallerState:
    """`to_dict()` passes nested values through by reference, so what the database
    stores must be detached from the caller's `UserMemory`. #10977"""

    def _memory(self) -> UserMemory:
        return UserMemory(memory_id="m1", user_id="alice", memory="alice thing", topics=["agents"])

    def test_mutating_the_caller_after_upsert_does_not_change_stored_topics(self):
        db = InMemoryDb()
        memory = self._memory()
        db.upsert_user_memory(memory)

        memory.topics.append("unsaved")

        stored = db.get_user_memory("m1", deserialize=False)
        assert stored["topics"] == ["agents"]

    def test_stored_topics_do_not_leak_into_topic_listings(self):
        db = InMemoryDb()
        memory = self._memory()
        db.upsert_user_memory(memory)

        memory.topics.append("unsaved")

        assert db.get_all_memory_topics(user_id="alice") == ["agents"]

    def test_mutating_the_returned_dict_does_not_change_stored_topics(self):
        db = InMemoryDb()
        returned = db.upsert_user_memory(self._memory(), deserialize=False)

        returned["topics"].append("unsaved")

        assert db.get_user_memory("m1", deserialize=False)["topics"] == ["agents"]

    def test_bulk_upsert_detaches_every_memory(self):
        db = InMemoryDb()
        memories = [
            UserMemory(memory_id="m1", user_id="alice", memory="a", topics=["agents"]),
            UserMemory(memory_id="m2", user_id="bob", memory="b", topics=["code"]),
        ]
        db.upsert_memories(memories)

        memories[0].topics.append("unsaved")

        assert db.get_user_memory("m1", deserialize=False)["topics"] == ["agents"]
        assert db.get_user_memory("m2", deserialize=False)["topics"] == ["code"]
