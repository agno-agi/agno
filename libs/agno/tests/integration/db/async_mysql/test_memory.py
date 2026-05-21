"""Integration tests for AsyncMySQLDb memory methods"""

import pytest

from agno.db.schemas.memory import UserMemory


@pytest.mark.asyncio
async def test_upsert_and_get_user_memory(async_mysql_db_real):
    """Test upserting and retrieving a user memory"""
    memory = UserMemory(
        memory_id="test-memory-1",
        memory="User likes Python programming",
        user_id="test-user",
        topics=["programming", "python"],
    )

    # Upsert memory
    result = await async_mysql_db_real.upsert_user_memory(memory)
    assert result is not None
    assert result.memory_id == "test-memory-1"

    # Get memory back
    retrieved = await async_mysql_db_real.get_user_memory("test-memory-1")
    assert retrieved is not None
    assert retrieved.memory == "User likes Python programming"
    assert "python" in retrieved.topics


@pytest.mark.asyncio
async def test_get_user_memories_with_filters(async_mysql_db_real):
    """Test getting memories with various filters"""
    # Create multiple memories
    for i in range(3):
        memory = UserMemory(
            memory_id=f"test-filter-memory-{i}",
            memory=f"Memory content {i}",
            user_id=f"user-{i % 2}",
            topics=["topic1"] if i % 2 == 0 else ["topic2"],
        )
        await async_mysql_db_real.upsert_user_memory(memory)

    # Get all memories for user-0
    user_memories = await async_mysql_db_real.get_user_memories(user_id="user-0")
    assert len(user_memories) >= 2

    # Filter by topics
    topic_memories = await async_mysql_db_real.get_user_memories(topics=["topic1"])
    assert len(topic_memories) >= 2


@pytest.mark.asyncio
async def test_delete_user_memory(async_mysql_db_real):
    """Test deleting a user memory"""
    memory = UserMemory(
        memory_id="test-delete-memory",
        memory="This will be deleted",
        user_id="test-user",
    )

    # Upsert and then delete
    await async_mysql_db_real.upsert_user_memory(memory)
    await async_mysql_db_real.delete_user_memory("test-delete-memory")

    # Verify it's gone
    retrieved = await async_mysql_db_real.get_user_memory("test-delete-memory")
    assert retrieved is None


@pytest.mark.asyncio
async def test_delete_multiple_user_memories(async_mysql_db_real):
    """Test deleting multiple user memories"""
    # Create multiple memories
    memory_ids = []
    for i in range(3):
        memory = UserMemory(
            memory_id=f"test-bulk-delete-{i}",
            memory=f"Memory {i}",
            user_id="test-user",
        )
        await async_mysql_db_real.upsert_user_memory(memory)
        memory_ids.append(memory.memory_id)

    # Delete all at once
    await async_mysql_db_real.delete_user_memories(memory_ids)

    # Verify all are gone
    for memory_id in memory_ids:
        retrieved = await async_mysql_db_real.get_user_memory(memory_id)
        assert retrieved is None


@pytest.mark.asyncio
async def test_get_all_memory_topics(async_mysql_db_real):
    """Test getting all unique memory topics"""
    # Create memories with different topics
    memories = [
        UserMemory(memory_id="m1", memory="Memory 1", topics=["ai", "ml"]),
        UserMemory(memory_id="m2", memory="Memory 2", topics=["python", "ai"]),
        UserMemory(memory_id="m3", memory="Memory 3", topics=["ml", "data"]),
    ]

    for memory in memories:
        await async_mysql_db_real.upsert_user_memory(memory)

    # Get all topics
    topics = await async_mysql_db_real.get_all_memory_topics()
    assert "ai" in topics
    assert "ml" in topics
    assert "python" in topics
    assert "data" in topics


@pytest.mark.asyncio
async def test_get_user_memory_stats(async_mysql_db_real):
    """Test getting user memory statistics"""
    # Create memories for different users
    for i in range(5):
        memory = UserMemory(
            memory_id=f"test-stats-memory-{i}",
            memory=f"Memory {i}",
            user_id=f"user-{i % 2}",
        )
        await async_mysql_db_real.upsert_user_memory(memory)

    # Get stats
    stats, total = await async_mysql_db_real.get_user_memory_stats()
    assert total >= 2  # At least 2 users
    assert len(stats) >= 2


@pytest.mark.asyncio
async def test_upsert_memories(async_mysql_db_real):
    """Test upsert_memories for inserting new memories"""
    # Create memories
    memories = [
        UserMemory(
            memory_id=f"bulk_memory_{i}",
            memory=f"Bulk memory content {i}",
            user_id="bulk_user",
            topics=["bulk", f"topic_{i}"],
        )
        for i in range(5)
    ]

    # Bulk upsert memories
    results = await async_mysql_db_real.upsert_memories(memories)

    # Verify results
    assert len(results) == 5
    for i, result in enumerate(results):
        assert isinstance(result, UserMemory)
        assert result.memory_id == f"bulk_memory_{i}"
        assert result.user_id == "bulk_user"
        assert "bulk" in result.topics


@pytest.mark.asyncio
async def test_upsert_memories_update(async_mysql_db_real):
    """Test upsert_memories for updating existing memories"""
    # Create initial memories
    initial_memories = [
        UserMemory(
            memory_id=f"update_memory_{i}",
            memory=f"Original content {i}",
            user_id="update_user",
            topics=["original"],
        )
        for i in range(3)
    ]
    await async_mysql_db_real.upsert_memories(initial_memories)

    # Update memories
    updated_memories = [
        UserMemory(
            memory_id=f"update_memory_{i}",
            memory=f"Updated content {i}",
            user_id="update_user",
            topics=["updated", f"topic_{i}"],
        )
        for i in range(3)
    ]
    results = await async_mysql_db_real.upsert_memories(updated_memories)

    # Verify updates
    assert len(results) == 3
    for i, result in enumerate(results):
        assert isinstance(result, UserMemory)
        assert result.memory == f"Updated content {i}"
        assert "updated" in result.topics
        assert "original" not in result.topics
