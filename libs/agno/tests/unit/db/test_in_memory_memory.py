"""Unit tests for InMemoryDb memory operations."""

import pytest

from agno.db.in_memory.in_memory_db import InMemoryDb


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
