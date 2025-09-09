"""Integration tests for the Memory related methods of the PostgresDb class"""

from datetime import datetime

import pytest

from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.memory import UserMemory


@pytest.fixture(autouse=True)
def cleanup_memories(postgres_db_real: PostgresDb):
    """Fixture to clean-up memory rows after each test"""
    yield

    with postgres_db_real.Session() as session:
        try:
            memory_table = postgres_db_real._get_table("memories")
            session.execute(memory_table.delete())
            session.commit()
        except Exception:
            session.rollback()


@pytest.fixture
def sample_user_memory() -> UserMemory:
    """Fixture returning a sample UserMemory"""
    return UserMemory(
        memory_id="test_memory_1",
        memory="User prefers coffee over tea and likes working in the morning",
        topics=["preferences", "work_habits"],
        user_id="test_user_1",
        input="I prefer coffee and work best in the morning",
        updated_at=datetime.now(),
        feedback="positive",
        agent_id="test_agent_1",
        team_id="test_team_1",
    )


def test_insert_memory(postgres_db_real: PostgresDb, sample_user_memory):
    """Ensure upsert_user_memory inserts a new memory correctly"""
    result = postgres_db_real.upsert_user_memory(sample_user_memory)

    assert result is not None
    assert isinstance(result, UserMemory)
    assert result.memory_id == sample_user_memory.memory_id
    assert result.memory == sample_user_memory.memory
    assert result.topics == sample_user_memory.topics
    assert result.user_id == sample_user_memory.user_id
    assert result.agent_id == sample_user_memory.agent_id
    assert result.team_id == sample_user_memory.team_id


def test_update_memory(postgres_db_real: PostgresDb, sample_user_memory):
    """Ensure upsert_user_memory updates an existing memory correctly"""
    postgres_db_real.upsert_user_memory(sample_user_memory)
    sample_user_memory.memory = "Updated: User prefers tea now and works best at night"
    sample_user_memory.topics = ["preferences", "work_habits", "updated"]

    result = postgres_db_real.upsert_user_memory(sample_user_memory)

    assert result is not None
    assert isinstance(result, UserMemory)
    assert result.memory == sample_user_memory.memory
    assert result.topics == sample_user_memory.topics


def test_upsert_memory_without_deserialization(postgres_db_real: PostgresDb, sample_user_memory):
    """Ensure upsert_user_memory without deserialization returns a dict"""
    result = postgres_db_real.upsert_user_memory(sample_user_memory, deserialize=False)

    assert result is not None
    assert isinstance(result, dict)
    assert result["memory_id"] == sample_user_memory.memory_id


def test_get_memory_by_id(postgres_db_real: PostgresDb, sample_user_memory):
    """Ensure get_user_memory returns a UserMemory"""
    postgres_db_real.upsert_user_memory(sample_user_memory)

    result = postgres_db_real.get_user_memory(memory_id=sample_user_memory.memory_id)

    assert result is not None
    assert isinstance(result, UserMemory)
    assert result.memory_id == sample_user_memory.memory_id
    assert result.memory == sample_user_memory.memory


def test_get_user_memory_without_deserialize(postgres_db_real: PostgresDb, sample_user_memory):
    """Test get_user_memory without deserialization"""
    postgres_db_real.upsert_user_memory(sample_user_memory)

    result = postgres_db_real.get_user_memory(memory_id=sample_user_memory.memory_id, deserialize=False)

    assert result is not None
    assert isinstance(result, dict)
    assert result["memory_id"] == sample_user_memory.memory_id


def test_delete_user_memory(postgres_db_real: PostgresDb, sample_user_memory):
    """Ensure delete_user_memory deletes the memory"""
    postgres_db_real.upsert_user_memory(sample_user_memory)

    # Verify the memory exists
    memory = postgres_db_real.get_user_memory(memory_id=sample_user_memory.memory_id)
    assert memory is not None

    # Delete the memory
    postgres_db_real.delete_user_memory(sample_user_memory.memory_id)

    # Verify the memory has been deleted
    memory = postgres_db_real.get_user_memory(memory_id=sample_user_memory.memory_id)
    assert memory is None


def test_delete_multiple_user_memories(postgres_db_real: PostgresDb):
    """Ensure delete_user_memories deletes multiple memories"""

    # Inserting some memories
    memory_ids = []
    for i in range(3):
        memory = UserMemory(
            memory_id=f"memory_{i}", memory=f"Test memory {i}", user_id="test_user", updated_at=datetime.now()
        )
        postgres_db_real.upsert_user_memory(memory)
        memory_ids.append(memory.memory_id)

    # Deleting the first two memories
    postgres_db_real.delete_user_memories(memory_ids[:2])

    # Verify deletions
    deleted_memory_1 = postgres_db_real.get_user_memory(memory_id="memory_0")
    deleted_memory_2 = postgres_db_real.get_user_memory(memory_id="memory_1")
    assert deleted_memory_1 is None
    assert deleted_memory_2 is None

    # Verify the third memory was not deleted
    remaining_memory = postgres_db_real.get_user_memory(memory_id="memory_2")
    assert remaining_memory is not None


def test_get_all_memory_topics(postgres_db_real: PostgresDb):
    """Ensure get_all_memory_topics returns all unique memory topics"""

    # Create memories with different topics
    memories = [
        UserMemory(
            memory_id="memory_1",
            memory="Memory 1",
            topics=["topic1", "topic2"],
            user_id="user1",
            updated_at=datetime.now(),
        ),
        UserMemory(
            memory_id="memory_2",
            memory="Memory 2",
            topics=["topic2", "topic3"],
            user_id="user2",
            updated_at=datetime.now(),
        ),
        UserMemory(
            memory_id="memory_3",
            memory="Memory 3",
            topics=["topic1", "topic4"],
            user_id="user3",
            updated_at=datetime.now(),
        ),
    ]

    for memory in memories:
        postgres_db_real.upsert_user_memory(memory)

    # Get all topics
    topics = postgres_db_real.get_all_memory_topics()
    assert set(topics) == {"topic1", "topic2", "topic3", "topic4"}


def test_get_user_memory_stats(postgres_db_real: PostgresDb):
    """Ensure get_user_memory_stats returns the correct statistics"""

    # Inserting some memories
    memories = [
        UserMemory(
            memory_id="memory_1", memory="Memory 1", user_id="user1", agent_id="agent1", updated_at=datetime.now()
        ),
        UserMemory(
            memory_id="memory_2", memory="Memory 2", user_id="user1", agent_id="agent2", updated_at=datetime.now()
        ),
    ]

    for memory in memories:
        postgres_db_real.upsert_user_memory(memory)

    # Verify the correct statistics are returned
    stats, count = postgres_db_real.get_user_memory_stats()
    assert count == 1
    assert len(stats) == 1
    assert stats[0]["user_id"] == "user1"
    assert stats[0]["total_memories"] == 2


def test_comprehensive_user_memory_fields(postgres_db_real: PostgresDb):
    """Ensure all UserMemory fields are properly handled"""

    # Creating a comprehensive memory
    comprehensive_memory = UserMemory(
        memory_id="comprehensive_memory",
        memory="This is a comprehensive test memory with detailed information about user preferences and behaviors",
        topics=["preferences", "behavior", "detailed", "comprehensive"],
        user_id="comprehensive_user",
        input="Original input that led to this memory being created",
        updated_at=datetime(2021, 1, 1, 12, 0, 0),
        feedback="Very positive feedback about this memory",
        agent_id="comprehensive_agent",
        team_id="comprehensive_team",
    )

    # Inserting the memory
    result = postgres_db_real.upsert_user_memory(comprehensive_memory)
    assert result is not None
    assert isinstance(result, UserMemory)

    # Verify all fields are preserved
    assert result.memory_id == comprehensive_memory.memory_id
    assert result.memory == comprehensive_memory.memory
    assert result.topics == comprehensive_memory.topics
    assert result.user_id == comprehensive_memory.user_id
    assert result.input == comprehensive_memory.input
    assert result.agent_id == comprehensive_memory.agent_id
    assert result.team_id == comprehensive_memory.team_id

    # Verify the memory can be retrieved with all fields intact
    retrieved = postgres_db_real.get_user_memory(memory_id=comprehensive_memory.memory_id)  # type: ignore

    assert retrieved is not None and isinstance(retrieved, UserMemory)
    assert retrieved.memory_id == comprehensive_memory.memory_id
    assert retrieved.memory == comprehensive_memory.memory
    assert retrieved.topics == comprehensive_memory.topics
    assert retrieved.user_id == comprehensive_memory.user_id
    assert retrieved.input == comprehensive_memory.input
    assert retrieved.agent_id == comprehensive_memory.agent_id
    assert retrieved.team_id == comprehensive_memory.team_id
