"""Integration tests for the Memory related methods of the AsyncPostgresDb class"""

import time
from typing import List

import pytest
import pytest_asyncio

from agno.db.postgres import AsyncPostgresDb
from agno.db.schemas.memory import UserMemory


@pytest_asyncio.fixture(autouse=True)
async def cleanup_memories(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up memory rows after each test"""
    yield

    try:
        memory_table = await async_postgres_db_real._get_table("memories")
        async with async_postgres_db_real.async_session_factory() as session:
            await session.execute(memory_table.delete())
            await session.commit()
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture
def sample_user_memory() -> UserMemory:
    """Fixture returning a sample UserMemory"""
    return UserMemory(
        memory_id="test_memory_1",
        memory={"content": "This is a test memory", "importance": "high"},
        input="Test input that created this memory",
        user_id="test_user_1",
        agent_id="test_agent_1",
        topics=["testing", "memory"],
        updated_at=int(time.time()),
    )


@pytest.fixture
def sample_user_memories() -> List[UserMemory]:
    """Fixture returning multiple sample UserMemories"""
    memories = []
    for i in range(5):
        memories.append(
            UserMemory(
                memory_id=f"test_memory_{i}",
                memory={"content": f"This is test memory {i}", "importance": "medium"},
                input=f"Test input {i}",
                user_id="test_user_1",
                agent_id=f"test_agent_{i % 2}",  # Alternate between two agents
                topics=["testing", f"topic_{i}"],
                updated_at=int(time.time()) + i,
            )
        )
    return memories


@pytest.mark.asyncio
async def test_upsert_user_memory(async_postgres_db_real: AsyncPostgresDb, sample_user_memory: UserMemory):
    """Test upserting a user memory"""
    # First insert
    result = await async_postgres_db_real.upsert_user_memory(sample_user_memory)

    assert result is not None
    assert isinstance(result, UserMemory)
    assert result.memory_id == "test_memory_1"
    assert result.user_id == "test_user_1"
    assert result.memory["content"] == "This is a test memory"

    # Update the memory
    sample_user_memory.memory["updated"] = True
    updated_result = await async_postgres_db_real.upsert_user_memory(sample_user_memory)

    assert updated_result is not None
    assert updated_result.memory["updated"] is True


@pytest.mark.asyncio
async def test_upsert_user_memory_auto_id(async_postgres_db_real: AsyncPostgresDb):
    """Test upserting a user memory without ID (should auto-generate)"""
    memory = UserMemory(
        memory={"content": "Memory without ID"},
        user_id="test_user_1",
        agent_id="test_agent_1",
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert result.memory_id is not None
    assert len(result.memory_id) > 0


@pytest.mark.asyncio
async def test_get_user_memory(async_postgres_db_real: AsyncPostgresDb, sample_user_memory: UserMemory):
    """Test getting a single user memory"""
    # First upsert the memory
    await async_postgres_db_real.upsert_user_memory(sample_user_memory)

    # Now get it back
    result = await async_postgres_db_real.get_user_memory("test_memory_1")

    assert result is not None
    assert isinstance(result, UserMemory)
    assert result.memory_id == "test_memory_1"
    assert result.user_id == "test_user_1"
    assert result.memory["content"] == "This is a test memory"


@pytest.mark.asyncio
async def test_get_user_memory_deserialize_false(
    async_postgres_db_real: AsyncPostgresDb, sample_user_memory: UserMemory
):
    """Test getting a user memory as raw dict"""
    # First upsert the memory
    await async_postgres_db_real.upsert_user_memory(sample_user_memory)

    # Now get it back as dict
    result = await async_postgres_db_real.get_user_memory("test_memory_1", deserialize=False)

    assert result is not None
    assert isinstance(result, dict)
    assert result["memory_id"] == "test_memory_1"
    assert result["user_id"] == "test_user_1"


@pytest.mark.asyncio
async def test_get_user_memories_all(async_postgres_db_real: AsyncPostgresDb, sample_user_memories: List[UserMemory]):
    """Test getting all user memories"""
    # Insert all memories
    for memory in sample_user_memories:
        await async_postgres_db_real.upsert_user_memory(memory)

    # Get all memories
    result = await async_postgres_db_real.get_user_memories()

    assert len(result) == 5
    assert all(isinstance(memory, UserMemory) for memory in result)


@pytest.mark.asyncio
async def test_get_user_memories_with_filters(
    async_postgres_db_real: AsyncPostgresDb, sample_user_memories: List[UserMemory]
):
    """Test getting user memories with various filters"""
    # Insert all memories
    for memory in sample_user_memories:
        await async_postgres_db_real.upsert_user_memory(memory)

    # Filter by user_id
    result = await async_postgres_db_real.get_user_memories(user_id="test_user_1")
    assert len(result) == 5

    # Filter by agent_id
    result = await async_postgres_db_real.get_user_memories(agent_id="test_agent_0")
    assert len(result) == 3  # memories 0, 2, 4

    # Filter by topics
    result = await async_postgres_db_real.get_user_memories(topics=["topic_1"])
    assert len(result) == 1
    assert result[0].memory_id == "test_memory_1"

    # Filter by search content
    result = await async_postgres_db_real.get_user_memories(search_content="test memory 2")
    assert len(result) == 1
    assert result[0].memory_id == "test_memory_2"


@pytest.mark.asyncio
async def test_get_user_memories_with_pagination(
    async_postgres_db_real: AsyncPostgresDb, sample_user_memories: List[UserMemory]
):
    """Test getting user memories with pagination"""
    # Insert all memories
    for memory in sample_user_memories:
        await async_postgres_db_real.upsert_user_memory(memory)

    # Test pagination - get first page
    result, total_count = await async_postgres_db_real.get_user_memories(limit=2, page=1, deserialize=False)

    assert len(result) == 2
    assert total_count == 5

    # Test pagination - get second page
    result, total_count = await async_postgres_db_real.get_user_memories(limit=2, page=2, deserialize=False)

    assert len(result) == 2
    assert total_count == 5


@pytest.mark.asyncio
async def test_get_user_memories_with_sorting(
    async_postgres_db_real: AsyncPostgresDb, sample_user_memories: List[UserMemory]
):
    """Test getting user memories with sorting"""
    # Insert all memories
    for memory in sample_user_memories:
        await async_postgres_db_real.upsert_user_memory(memory)

    # Sort by updated_at ascending
    result = await async_postgres_db_real.get_user_memories(sort_by="updated_at", sort_order="asc")

    assert len(result) == 5
    # Should be ordered by updated_at (oldest first)
    assert result[0].memory_id == "test_memory_0"
    assert result[-1].memory_id == "test_memory_4"


@pytest.mark.asyncio
async def test_delete_user_memory(async_postgres_db_real: AsyncPostgresDb, sample_user_memory: UserMemory):
    """Test deleting a single user memory"""
    # First insert the memory
    await async_postgres_db_real.upsert_user_memory(sample_user_memory)

    # Verify it exists
    result = await async_postgres_db_real.get_user_memory("test_memory_1")
    assert result is not None

    # Delete it
    await async_postgres_db_real.delete_user_memory("test_memory_1")

    # Verify it's gone
    result = await async_postgres_db_real.get_user_memory("test_memory_1")
    assert result is None


@pytest.mark.asyncio
async def test_delete_user_memories_bulk(
    async_postgres_db_real: AsyncPostgresDb, sample_user_memories: List[UserMemory]
):
    """Test deleting multiple user memories"""
    # Insert all memories
    for memory in sample_user_memories:
        await async_postgres_db_real.upsert_user_memory(memory)

    # Verify they exist
    memories = await async_postgres_db_real.get_user_memories()
    assert len(memories) == 5

    # Delete some of them
    memory_ids = ["test_memory_0", "test_memory_2", "test_memory_4"]
    await async_postgres_db_real.delete_user_memories(memory_ids)

    # Verify correct ones are gone
    memories = await async_postgres_db_real.get_user_memories()
    assert len(memories) == 2
    remaining_ids = [m.memory_id for m in memories]
    assert "test_memory_1" in remaining_ids
    assert "test_memory_3" in remaining_ids


@pytest.mark.asyncio
async def test_clear_memories(async_postgres_db_real: AsyncPostgresDb, sample_user_memories: List[UserMemory]):
    """Test clearing all memories"""
    # Insert all memories
    for memory in sample_user_memories:
        await async_postgres_db_real.upsert_user_memory(memory)

    # Verify they exist
    memories = await async_postgres_db_real.get_user_memories()
    assert len(memories) == 5

    # Clear all memories
    await async_postgres_db_real.clear_memories()

    # Verify they're all gone
    memories = await async_postgres_db_real.get_user_memories()
    assert len(memories) == 0


@pytest.mark.asyncio
async def test_get_all_memory_topics(async_postgres_db_real: AsyncPostgresDb, sample_user_memories: List[UserMemory]):
    """Test getting all memory topics"""
    # Insert all memories
    for memory in sample_user_memories:
        await async_postgres_db_real.upsert_user_memory(memory)

    # Get all topics
    topics = await async_postgres_db_real.get_all_memory_topics()

    # Should contain all unique topics from the memories
    assert "testing" in topics
    assert "topic_0" in topics
    assert "topic_1" in topics
    assert "topic_2" in topics
    assert "topic_3" in topics
    assert "topic_4" in topics
    assert len(topics) == 6  # "testing" + 5 unique "topic_N"


@pytest.mark.asyncio
async def test_get_user_memory_stats(async_postgres_db_real: AsyncPostgresDb):
    """Test getting user memory statistics"""
    # Create memories for different users
    memories = []

    for user_i in range(3):
        for mem_i in range(2 if user_i == 0 else 1):  # User 0 gets 2 memories, others get 1
            memory = UserMemory(
                memory_id=f"memory_u{user_i}_m{mem_i}",
                memory={"content": f"Memory for user {user_i}"},
                user_id=f"user_{user_i}",
                agent_id="test_agent",
                updated_at=int(time.time()) + user_i * 10 + mem_i,
            )
            memories.append(memory)
            await async_postgres_db_real.upsert_user_memory(memory)

    # Get stats
    stats, total_count = await async_postgres_db_real.get_user_memory_stats()

    assert len(stats) == 3
    assert total_count == 3

    print(stats)

    # Stats should be ordered by last_memory_updated_at desc
    # User 2 should be first (highest timestamp)
    assert stats[0]["user_id"] == "user_2"
    assert stats[0]["total_memories"] == 1

    # User 0 should have 2 memories
    user_0_stats = next(s for s in stats if s["user_id"] == "user_0")
    assert user_0_stats["total_memories"] == 2


@pytest.mark.asyncio
async def test_get_user_memory_stats_with_pagination(async_postgres_db_real: AsyncPostgresDb):
    """Test getting user memory stats with pagination"""
    # Create memories for 5 different users
    for user_i in range(5):
        memory = UserMemory(
            memory_id=f"memory_u{user_i}",
            memory={"content": f"Memory for user {user_i}"},
            user_id=f"user_{user_i}",
            agent_id="test_agent",
            updated_at=int(time.time()) + user_i,
        )
        await async_postgres_db_real.upsert_user_memory(memory)

    # Get first page
    stats, total_count = await async_postgres_db_real.get_user_memory_stats(limit=2, page=1)

    assert len(stats) == 2
    assert total_count == 5

    # Get second page
    stats, total_count = await async_postgres_db_real.get_user_memory_stats(limit=2, page=2)

    assert len(stats) == 2
    assert total_count == 5
