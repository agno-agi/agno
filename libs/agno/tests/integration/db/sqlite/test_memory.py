"""Integration tests for the Memory related methods of the SqliteDb class"""

from typing import cast

import pytest

from agno.db.schemas.memory import UserMemory
from agno.db.sqlite.sqlite import SqliteDb


@pytest.fixture(autouse=True)
def cleanup_memories(sqlite_db_real: SqliteDb):
    """Fixture to clean-up session rows after each test"""
    yield

    with sqlite_db_real.Session() as session:
        try:
            memories_table = sqlite_db_real._get_table("memories")
            if memories_table is not None:
                session.execute(memories_table.delete())
                session.commit()
        except Exception:
            session.rollback()


@pytest.fixture
def sample_memory() -> UserMemory:
    """Fixture returning a sample UserMemory"""
    return UserMemory(memory_id="1", memory="User likes surfing", user_id="1", topics=["sports", "water"])


def test_insert_memory(sqlite_db_real: SqliteDb, sample_memory: UserMemory):
    """Ensure the upsert method works as expected when inserting a new AgentSession"""
    result = sqlite_db_real.upsert_user_memory(sample_memory, deserialize=True)
    assert result is not None

    memory = cast(UserMemory, result)
    assert memory.memory_id == sample_memory.memory_id
    assert memory.memory == sample_memory.memory
    assert memory.user_id == sample_memory.user_id
    assert memory.topics == sample_memory.topics


def test_get_memories_by_topics(sqlite_db_real: SqliteDb):
    """Test getting memories by topics."""
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="1", memory="User likes surfing", user_id="1", topics=["sports", "water"]),
        deserialize=True,
    )
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="2", memory="User likes sushi", user_id="1", topics=["food", "japanese"]), deserialize=True
    )
    memories = sqlite_db_real.get_user_memories(topics=["sports"])
    assert len(memories) == 1
    assert memories[0].memory_id == "1"
    assert memories[0].memory == "User likes surfing"
    assert memories[0].user_id == "1"
    assert memories[0].topics == ["sports", "water"]


def test_get_all_memory_topics(sqlite_db_real: SqliteDb):
    """Test get_all_memory_topics returns all unique topics"""
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="t1", memory="Memory 1", user_id="user1", topics=["topic1", "topic2"])
    )
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="t2", memory="Memory 2", user_id="user2", topics=["topic2", "topic3"])
    )

    topics = sqlite_db_real.get_all_memory_topics()
    assert set(topics) == {"topic1", "topic2", "topic3"}


def test_get_all_memory_topics_with_user_id_filter(sqlite_db_real: SqliteDb):
    """Test get_all_memory_topics filters correctly by user_id (PR #7490 fix)"""
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="alice1", memory="Alice memory", user_id="alice", topics=["work", "python"])
    )
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="alice2", memory="Alice memory 2", user_id="alice", topics=["travel"])
    )
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="bob1", memory="Bob memory", user_id="bob", topics=["gaming", "rust"])
    )

    alice_topics = sqlite_db_real.get_all_memory_topics(user_id="alice")
    assert set(alice_topics) == {"work", "python", "travel"}

    bob_topics = sqlite_db_real.get_all_memory_topics(user_id="bob")
    assert set(bob_topics) == {"gaming", "rust"}

    all_topics = sqlite_db_real.get_all_memory_topics()
    assert set(all_topics) == {"work", "python", "travel", "gaming", "rust"}


def test_get_all_memory_topics_unknown_user_returns_empty(sqlite_db_real: SqliteDb):
    """Test get_all_memory_topics returns empty list for unknown user"""
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="existing", memory="Existing", user_id="existing_user", topics=["topic1"])
    )

    unknown_topics = sqlite_db_real.get_all_memory_topics(user_id="unknown_user")
    assert unknown_topics == []


def test_get_all_memory_topics_tenant_isolation(sqlite_db_real: SqliteDb):
    """Test that user_id filtering provides proper tenant isolation"""
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="iso1", memory="Alice secret", user_id="alice", topics=["confidential", "alice_only"])
    )
    sqlite_db_real.upsert_user_memory(
        UserMemory(memory_id="iso2", memory="Bob secret", user_id="bob", topics=["confidential", "bob_only"])
    )

    alice_topics = set(sqlite_db_real.get_all_memory_topics(user_id="alice"))
    bob_topics = set(sqlite_db_real.get_all_memory_topics(user_id="bob"))

    assert "alice_only" in alice_topics
    assert "alice_only" not in bob_topics
    assert "bob_only" in bob_topics
    assert "bob_only" not in alice_topics
