"""Integration tests for OracleDb memory methods"""

from agno.db.schemas.memory import UserMemory


def test_upsert_and_get_user_memory(oracle_db_real):
    """Test upserting and retrieving a user memory"""
    memory = UserMemory(
        memory_id="test-memory-1",
        memory="User likes Python programming",
        user_id="test-user",
        topics=["programming", "python"],
    )

    # Upsert memory
    result = oracle_db_real.upsert_user_memory(memory)
    assert result is not None
    assert result.memory_id == "test-memory-1"

    # Get memory back
    retrieved = oracle_db_real.get_user_memory("test-memory-1")
    assert retrieved is not None
    assert retrieved.memory == "User likes Python programming"
    assert "python" in retrieved.topics


def test_get_user_memories_with_filters(oracle_db_real):
    """Test getting memories with various filters"""
    # Create multiple memories
    for i in range(3):
        memory = UserMemory(
            memory_id=f"test-filter-memory-{i}",
            memory=f"Memory content {i}",
            user_id=f"user-{i % 2}",
            topics=["topic1"] if i % 2 == 0 else ["topic2"],
        )
        oracle_db_real.upsert_user_memory(memory)

    # Get all memories for user-0
    user_memories = oracle_db_real.get_user_memories(user_id="user-0")
    assert len(user_memories) >= 2

    # Filter by topics
    topic_memories = oracle_db_real.get_user_memories(topics=["topic1"])
    assert len(topic_memories) >= 2


def test_delete_user_memory(oracle_db_real):
    """Test deleting a user memory"""
    memory = UserMemory(
        memory_id="test-delete-memory",
        memory="This will be deleted",
        user_id="test-user",
    )

    # Upsert and then delete
    oracle_db_real.upsert_user_memory(memory)
    oracle_db_real.delete_user_memory("test-delete-memory")

    # Verify it's gone
    retrieved = oracle_db_real.get_user_memory("test-delete-memory")
    assert retrieved is None


def test_delete_multiple_user_memories(oracle_db_real):
    """Test deleting multiple user memories"""
    # Create multiple memories
    memory_ids = []
    for i in range(3):
        memory = UserMemory(
            memory_id=f"test-bulk-delete-{i}",
            memory=f"Memory {i}",
            user_id="test-user",
        )
        oracle_db_real.upsert_user_memory(memory)
        memory_ids.append(memory.memory_id)

    # Delete all at once
    oracle_db_real.delete_user_memories(memory_ids)

    # Verify all are gone
    for memory_id in memory_ids:
        retrieved = oracle_db_real.get_user_memory(memory_id)
        assert retrieved is None


def test_get_all_memory_topics(oracle_db_real):
    """Test getting all unique memory topics"""
    # Create memories with different topics
    memories = [
        UserMemory(memory_id="m1", memory="Memory 1", topics=["ai", "ml"]),
        UserMemory(memory_id="m2", memory="Memory 2", topics=["python", "ai"]),
        UserMemory(memory_id="m3", memory="Memory 3", topics=["ml", "data"]),
    ]

    for memory in memories:
        oracle_db_real.upsert_user_memory(memory)

    # Get all topics
    topics = oracle_db_real.get_all_memory_topics()
    assert "ai" in topics
    assert "ml" in topics
    assert "python" in topics
    assert "data" in topics


def test_get_all_memory_topics_with_user_id_filter(oracle_db_real):
    """Test get_all_memory_topics filters correctly by user_id"""
    memories = [
        UserMemory(memory_id="alice_m1", memory="Alice memory 1", user_id="alice", topics=["work", "python"]),
        UserMemory(memory_id="alice_m2", memory="Alice memory 2", user_id="alice", topics=["travel"]),
        UserMemory(memory_id="bob_m1", memory="Bob memory", user_id="bob", topics=["gaming", "rust"]),
    ]

    for memory in memories:
        oracle_db_real.upsert_user_memory(memory)

    alice_topics = oracle_db_real.get_all_memory_topics(user_id="alice")
    assert set(alice_topics) == {"work", "python", "travel"}

    bob_topics = oracle_db_real.get_all_memory_topics(user_id="bob")
    assert set(bob_topics) == {"gaming", "rust"}

    all_topics = oracle_db_real.get_all_memory_topics()
    for topic in ["work", "python", "travel", "gaming", "rust"]:
        assert topic in all_topics


def test_get_all_memory_topics_unknown_user_returns_empty(oracle_db_real):
    """Test get_all_memory_topics returns empty list for unknown user"""
    memory = UserMemory(memory_id="existing_m", memory="Existing", user_id="existing_user", topics=["topic1"])
    oracle_db_real.upsert_user_memory(memory)

    unknown_topics = oracle_db_real.get_all_memory_topics(user_id="unknown_user")
    assert unknown_topics == []


def test_get_all_memory_topics_tenant_isolation(oracle_db_real):
    """Test that user_id filtering provides proper tenant isolation"""
    memories = [
        UserMemory(
            memory_id="iso_a", memory="Alice secret", user_id="alice_iso", topics=["confidential", "alice_only"]
        ),
        UserMemory(memory_id="iso_b", memory="Bob secret", user_id="bob_iso", topics=["confidential", "bob_only"]),
    ]

    for memory in memories:
        oracle_db_real.upsert_user_memory(memory)

    alice_topics = set(oracle_db_real.get_all_memory_topics(user_id="alice_iso"))
    bob_topics = set(oracle_db_real.get_all_memory_topics(user_id="bob_iso"))

    assert "alice_only" in alice_topics
    assert "alice_only" not in bob_topics
    assert "bob_only" in bob_topics
    assert "bob_only" not in alice_topics


def test_get_user_memory_stats(oracle_db_real):
    """Test getting user memory statistics"""
    # Create memories for different users
    for i in range(5):
        memory = UserMemory(
            memory_id=f"test-stats-memory-{i}",
            memory=f"Memory {i}",
            user_id=f"user-{i % 2}",
        )
        oracle_db_real.upsert_user_memory(memory)

    # Get stats
    stats, total = oracle_db_real.get_user_memory_stats()
    assert total >= 2  # At least 2 users
    assert len(stats) >= 2


def test_upsert_memories(oracle_db_real):
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
    results = oracle_db_real.upsert_memories(memories)

    # Verify results
    assert len(results) == 5
    for i, result in enumerate(results):
        assert isinstance(result, UserMemory)
        assert result.memory_id == f"bulk_memory_{i}"
        assert result.user_id == "bulk_user"
        assert "bulk" in result.topics


def test_upsert_memories_update(oracle_db_real):
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
    oracle_db_real.upsert_memories(initial_memories)

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
    results = oracle_db_real.upsert_memories(updated_memories)

    # Verify updates
    assert len(results) == 3
    for i, result in enumerate(results):
        assert isinstance(result, UserMemory)
        assert result.memory == f"Updated content {i}"
        assert "updated" in result.topics
        assert "original" not in result.topics


# -- Oracle-specific extra cases --


def test_upsert_user_memory_merge_is_idempotent(oracle_db_real):
    """Upserting the exact same memory twice via MERGE must not duplicate the row."""
    memory = UserMemory(
        memory_id="test-merge-idempotent-memory",
        memory="Idempotency check",
        user_id="test-user",
        topics=["idempotent"],
    )

    oracle_db_real.upsert_user_memory(memory)
    oracle_db_real.upsert_user_memory(memory)

    memories_raw, total_count = oracle_db_real.get_user_memories(user_id="test-user", deserialize=False)
    matching = [m for m in memories_raw if m["memory_id"] == "test-merge-idempotent-memory"]
    assert len(matching) == 1
