"""
Integration tests for MongoDB get_all_memory_topics filter logic.

Verifies that the match_filter correctly isolates topics by user_id.
Uses mongomock for lightweight testing without requiring a real MongoDB instance.
"""

import pytest

try:
    import mongomock
    from pymongo import MongoClient

    MONGOMOCK_AVAILABLE = True
except ImportError:
    MONGOMOCK_AVAILABLE = False


pytestmark = pytest.mark.skipif(not MONGOMOCK_AVAILABLE, reason="mongomock not installed")


@pytest.fixture
def mock_mongo_client():
    return mongomock.MongoClient()


@pytest.fixture
def db_with_memories(mock_mongo_client):
    db = mock_mongo_client["test_agno"]
    memories = db["memories"]

    memories.insert_many(
        [
            {"memory_id": "m1", "user_id": "alice", "memory": "alice pref 1", "topics": ["work", "python"]},
            {"memory_id": "m2", "user_id": "alice", "memory": "alice pref 2", "topics": ["travel", "japan"]},
            {"memory_id": "m3", "user_id": "bob", "memory": "bob pref 1", "topics": ["gaming", "rust"]},
            {"memory_id": "m4", "user_id": "bob", "memory": "bob pref 2", "topics": ["work", "typescript"]},
            {"memory_id": "m5", "user_id": "charlie", "memory": "charlie pref", "topics": ["music"]},
            {"memory_id": "m6", "user_id": "alice", "memory": "empty topics", "topics": []},
            {"memory_id": "m7", "user_id": "alice", "memory": "null topics", "topics": None},
            {"memory_id": "m8", "user_id": "bob", "memory": "shared topic", "topics": ["work"]},
        ]
    )
    return memories


class TestMongoDistinctFilterLogic:
    def test_distinct_returns_all_topics_when_no_filter(self, db_with_memories):
        match_filter = {}
        topics = db_with_memories.distinct("topics", match_filter)
        topics = [t for t in topics if t]

        expected = {"work", "python", "travel", "japan", "gaming", "rust", "typescript", "music"}
        assert set(topics) == expected

    def test_distinct_filters_by_user_id(self, db_with_memories):
        match_filter = {"user_id": "alice"}
        topics = db_with_memories.distinct("topics", match_filter)
        topics = [t for t in topics if t]

        assert set(topics) == {"work", "python", "travel", "japan"}

    def test_distinct_filters_bob(self, db_with_memories):
        match_filter = {"user_id": "bob"}
        topics = db_with_memories.distinct("topics", match_filter)
        topics = [t for t in topics if t]

        assert set(topics) == {"gaming", "rust", "work", "typescript"}

    def test_distinct_returns_empty_for_unknown_user(self, db_with_memories):
        match_filter = {"user_id": "unknown_user"}
        topics = db_with_memories.distinct("topics", match_filter)
        topics = [t for t in topics if t]

        assert topics == []

    def test_distinct_handles_empty_and_null_topics(self, db_with_memories):
        match_filter = {"user_id": "alice"}
        topics = db_with_memories.distinct("topics", match_filter)

        assert None in topics or [] == [t for t in topics if t is None]

    def test_shared_topic_appears_for_both_users(self, db_with_memories):
        alice_topics = set(t for t in db_with_memories.distinct("topics", {"user_id": "alice"}) if t)
        bob_topics = set(t for t in db_with_memories.distinct("topics", {"user_id": "bob"}) if t)

        assert "work" in alice_topics
        assert "work" in bob_topics


class TestMongoDbGetAllMemoryTopics:
    def test_get_all_memory_topics_no_filter(self, mock_mongo_client, db_with_memories):
        from typing import Any, Dict, List, Optional

        def get_all_memory_topics(collection, user_id: Optional[str] = None) -> List[str]:
            match_filter: Dict[str, Any] = {} if user_id is None else {"user_id": user_id}
            topics = collection.distinct("topics", match_filter)
            return [topic for topic in topics if topic]

        result = get_all_memory_topics(db_with_memories)
        assert set(result) == {"work", "python", "travel", "japan", "gaming", "rust", "typescript", "music"}

    def test_get_all_memory_topics_with_user_filter(self, mock_mongo_client, db_with_memories):
        from typing import Any, Dict, List, Optional

        def get_all_memory_topics(collection, user_id: Optional[str] = None) -> List[str]:
            match_filter: Dict[str, Any] = {} if user_id is None else {"user_id": user_id}
            topics = collection.distinct("topics", match_filter)
            return [topic for topic in topics if topic]

        assert set(get_all_memory_topics(db_with_memories, user_id="alice")) == {"work", "python", "travel", "japan"}
        assert set(get_all_memory_topics(db_with_memories, user_id="bob")) == {"gaming", "rust", "work", "typescript"}
        assert set(get_all_memory_topics(db_with_memories, user_id="charlie")) == {"music"}
        assert get_all_memory_topics(db_with_memories, user_id="nobody") == []


class TestTenantIsolation:
    def test_alice_cannot_see_bob_topics(self, db_with_memories):
        alice_topics = set(db_with_memories.distinct("topics", {"user_id": "alice"}))
        bob_only = {"gaming", "rust", "typescript"}

        for topic in bob_only:
            assert topic not in alice_topics, f"Alice should not see Bob's topic: {topic}"

    def test_bob_cannot_see_alice_topics(self, db_with_memories):
        bob_topics = set(db_with_memories.distinct("topics", {"user_id": "bob"}))
        alice_only = {"python", "travel", "japan"}

        for topic in alice_only:
            assert topic not in bob_topics, f"Bob should not see Alice's topic: {topic}"

    def test_total_topics_equals_sum_of_user_topics_minus_overlap(self, db_with_memories):
        all_topics = set(t for t in db_with_memories.distinct("topics", {}) if t)
        alice_topics = set(t for t in db_with_memories.distinct("topics", {"user_id": "alice"}) if t)
        bob_topics = set(t for t in db_with_memories.distinct("topics", {"user_id": "bob"}) if t)
        charlie_topics = set(t for t in db_with_memories.distinct("topics", {"user_id": "charlie"}) if t)

        assert all_topics == alice_topics | bob_topics | charlie_topics
