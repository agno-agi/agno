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


def test_upsert_memories(postgres_db_real: PostgresDb):
    """Test upsert_memories for inserting new memories"""

    # Create memories
    memories = []
    for i in range(5):
        memory = UserMemory(
            memory_id=f"bulk_memory_{i}",
            memory=f"Bulk test memory {i} with user preferences and information",
            topics=[f"topic_{i}", "bulk_test"],
            user_id=f"user_{i}",
            input=f"Input that generated memory {i}",
            agent_id=f"agent_{i}",
            updated_at=datetime.now(),
        )
        memories.append(memory)

    # Bulk upsert memories
    results = postgres_db_real.upsert_memories(memories)

    # Verify results
    assert len(results) == 5
    for i, result in enumerate(results):
        assert isinstance(result, UserMemory)
        assert result.memory_id == f"bulk_memory_{i}"
        assert result.user_id == f"user_{i}"
        assert result.agent_id == f"agent_{i}"
        assert result.topics is not None
        assert f"topic_{i}" in result.topics
        assert "bulk_test" in result.topics


def test_upsert_memories_update(postgres_db_real: PostgresDb):
    """Test upsert_memories for updating existing memories"""

    # Create memories
    initial_memories = []
    for i in range(3):
        memory = UserMemory(
            memory_id=f"update_memory_{i}",
            memory=f"Original memory {i}",
            topics=["original"],
            user_id=f"user_{i}",
            input=f"Original input {i}",
            updated_at=datetime.now(),
        )
        initial_memories.append(memory)
    postgres_db_real.upsert_memories(initial_memories)

    # Update memories
    updated_memories = []
    for i in range(3):
        memory = UserMemory(
            memory_id=f"update_memory_{i}",  # Same ID for update
            memory=f"Updated memory {i} with more information",
            topics=["updated", "enhanced"],
            user_id=f"user_{i}",
            input=f"Updated input {i}",
            feedback="positive",
            agent_id=f"new_agent_{i}",
            updated_at=datetime.now(),
        )
        updated_memories.append(memory)
    results = postgres_db_real.upsert_memories(updated_memories)
    assert len(results) == 3

    # Verify updates
    for i, result in enumerate(results):
        assert isinstance(result, UserMemory)
        assert result.memory_id == f"update_memory_{i}"
        assert "Updated memory" in result.memory
        assert result.topics == ["updated", "enhanced"]
        assert result.agent_id == f"new_agent_{i}"


def test_upsert_memories_performance(postgres_db_real: PostgresDb):
    """Ensure the bulk upsert method is considerably faster than individual upserts"""
    import time as time_module

    # Create memories
    memories = []
    for i in range(30):
        memory = UserMemory(
            memory_id=f"perf_memory_{i}",
            memory=f"Performance test memory {i} with detailed information",
            topics=["performance", "test"],
            user_id="perf_user",
            agent_id=f"perf_agent_{i}",
            updated_at=datetime.now(),
        )
        memories.append(memory)

    # Test individual upsert
    start_time = time_module.time()
    for memory in memories:
        postgres_db_real.upsert_user_memory(memory)
    individual_time = time_module.time() - start_time

    # Clean up for bulk upsert
    memory_ids = [m.memory_id for m in memories if m.memory_id]
    postgres_db_real.delete_user_memories(memory_ids)

    # Test bulk upsert
    start_time = time_module.time()
    postgres_db_real.upsert_memories(memories)
    bulk_time = time_module.time() - start_time

    # Verify all memories were created
    all_memories = postgres_db_real.get_user_memories(user_id="perf_user")
    assert len(all_memories) == 30

    # Bulk should be at least 2x faster
    assert bulk_time < individual_time / 2, (
        f"Bulk upsert is not fast enough: {bulk_time:.3f}s vs {individual_time:.3f}s"
    )


def test_get_user_memory_with_user_id_filter(postgres_db_real: PostgresDb):
    """Test get_user_memory with user_id filtering"""
    # Create memories for different users
    memory1 = UserMemory(
        memory_id="memory_user1",
        memory="Memory for user 1",
        user_id="user1",
        updated_at=datetime.now(),
    )
    memory2 = UserMemory(
        memory_id="memory_user2",
        memory="Memory for user 2",
        user_id="user2",
        updated_at=datetime.now(),
    )

    postgres_db_real.upsert_user_memory(memory1)
    postgres_db_real.upsert_user_memory(memory2)

    # Get memory with correct user_id
    result = postgres_db_real.get_user_memory(memory_id="memory_user1", user_id="user1")
    assert result is not None
    assert isinstance(result, UserMemory)
    assert result.memory_id == "memory_user1"
    assert result.user_id == "user1"

    # Get memory with wrong user_id should return None
    result = postgres_db_real.get_user_memory(memory_id="memory_user1", user_id="user2")
    assert result is None

    # Get memory without user_id filter should work
    result = postgres_db_real.get_user_memory(memory_id="memory_user1")
    assert result is not None
    assert result.user_id == "user1"


def test_delete_user_memory_with_user_id_filter(postgres_db_real: PostgresDb):
    """Test delete_user_memory with user_id filtering"""
    # Create memories for different users
    memory1 = UserMemory(
        memory_id="del_memory_user1",
        memory="Memory for user 1",
        user_id="user1",
        updated_at=datetime.now(),
    )
    memory2 = UserMemory(
        memory_id="del_memory_user2",
        memory="Memory for user 2",
        user_id="user2",
        updated_at=datetime.now(),
    )

    postgres_db_real.upsert_user_memory(memory1)
    postgres_db_real.upsert_user_memory(memory2)

    # Try to delete memory1 with wrong user_id (should not delete)
    postgres_db_real.delete_user_memory(memory_id="del_memory_user1", user_id="user2")

    # Verify memory1 still exists
    result = postgres_db_real.get_user_memory(memory_id="del_memory_user1")
    assert result is not None

    # Delete memory1 with correct user_id (should delete)
    postgres_db_real.delete_user_memory(memory_id="del_memory_user1", user_id="user1")

    # Verify memory1 is deleted
    result = postgres_db_real.get_user_memory(memory_id="del_memory_user1")
    assert result is None

    # Verify memory2 still exists
    result = postgres_db_real.get_user_memory(memory_id="del_memory_user2")
    assert result is not None


def test_delete_user_memories_with_user_id_filter(postgres_db_real: PostgresDb):
    """Test delete_user_memories with user_id filtering"""
    # Create memories for different users
    memories = [
        UserMemory(memory_id="bulk_del_m1", memory="Memory 1", user_id="user1", updated_at=datetime.now()),
        UserMemory(memory_id="bulk_del_m2", memory="Memory 2", user_id="user1", updated_at=datetime.now()),
        UserMemory(memory_id="bulk_del_m3", memory="Memory 3", user_id="user2", updated_at=datetime.now()),
        UserMemory(memory_id="bulk_del_m4", memory="Memory 4", user_id="user2", updated_at=datetime.now()),
    ]

    for memory in memories:
        postgres_db_real.upsert_user_memory(memory)

    # Try to delete user1's memories with user2's ID (should not delete user1's memories)
    postgres_db_real.delete_user_memories(memory_ids=["bulk_del_m1", "bulk_del_m2"], user_id="user2")

    # Verify user1's memories still exist
    result1 = postgres_db_real.get_user_memory(memory_id="bulk_del_m1")
    result2 = postgres_db_real.get_user_memory(memory_id="bulk_del_m2")
    assert result1 is not None
    assert result2 is not None

    # Delete user1's memories with correct user_id
    postgres_db_real.delete_user_memories(memory_ids=["bulk_del_m1", "bulk_del_m2"], user_id="user1")

    # Verify user1's memories are deleted
    result1 = postgres_db_real.get_user_memory(memory_id="bulk_del_m1")
    result2 = postgres_db_real.get_user_memory(memory_id="bulk_del_m2")
    assert result1 is None
    assert result2 is None

    # Verify user2's memories still exist
    result3 = postgres_db_real.get_user_memory(memory_id="bulk_del_m3")
    result4 = postgres_db_real.get_user_memory(memory_id="bulk_del_m4")
    assert result3 is not None
    assert result4 is not None


def test_delete_user_memories_without_user_id_filter(postgres_db_real: PostgresDb):
    """Test delete_user_memories without user_id filtering deletes all specified memories"""
    # Create memories for different users
    memories = [
        UserMemory(memory_id="no_filter_m1", memory="Memory 1", user_id="user1", updated_at=datetime.now()),
        UserMemory(memory_id="no_filter_m2", memory="Memory 2", user_id="user2", updated_at=datetime.now()),
        UserMemory(memory_id="no_filter_m3", memory="Memory 3", user_id="user3", updated_at=datetime.now()),
    ]

    for memory in memories:
        postgres_db_real.upsert_user_memory(memory)

    # Delete memories without user_id filter (should delete all specified)
    postgres_db_real.delete_user_memories(memory_ids=["no_filter_m1", "no_filter_m2"])

    # Verify memories are deleted regardless of user_id
    result1 = postgres_db_real.get_user_memory(memory_id="no_filter_m1")
    result2 = postgres_db_real.get_user_memory(memory_id="no_filter_m2")
    assert result1 is None
    assert result2 is None

    # Verify the third memory still exists
    result3 = postgres_db_real.get_user_memory(memory_id="no_filter_m3")
    assert result3 is not None
