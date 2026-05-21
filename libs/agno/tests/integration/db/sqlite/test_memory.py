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
