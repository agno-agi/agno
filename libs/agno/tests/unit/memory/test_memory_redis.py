from typing import Dict
from unittest.mock import ANY, MagicMock, patch

import pytest
from redis import ConnectionError

from agno.memory.v2.db.redis import RedisMemoryDb
from agno.memory.v2.db.schema import MemoryRow


@pytest.fixture
def mock_redis_client():
    """Mock Redis client with in-memory storage for testing."""
    with patch("agno.memory.v2.db.redis.Redis") as mock_redis:
        # Create a mock Redis client
        client = MagicMock()

        # Create an in-memory store to simulate Redis
        mock_data: Dict[str, str] = {}

        # Mock Redis client methods
        client.get.side_effect = lambda key: mock_data.get(key)
        client.set.side_effect = lambda key, value: mock_data.update({key: value})
        client.exists.side_effect = lambda key: key in mock_data

        # Make delete actually work correctly
        def mock_delete(*keys):
            deleted = 0
            for key in keys:
                if key in mock_data:
                    del mock_data[key]
                    deleted += 1
            return deleted

        client.delete.side_effect = mock_delete
        client.ping.return_value = True

        # Mock scan_iter to return keys
        client.scan_iter.side_effect = lambda match, count=None: [
            k for k in mock_data.keys() if k.startswith(match.replace("*", ""))
        ]

        # Return the mock Redis instance when Redis.Redis() is called
        mock_redis.return_value = client
        yield client


@pytest.fixture
def memory_db(mock_redis_client):
    """Create memory database with mock Redis client."""
    return RedisMemoryDb(prefix="test_memory")


def test_create_connection(mock_redis_client):
    """Test that create() tests Redis connection."""
    db = RedisMemoryDb(prefix="test")
    db.create()
    mock_redis_client.ping.assert_called_once()


def test_connection_error(mock_redis_client):
    """Test that create() raises exception on connection error."""
    mock_redis_client.ping.side_effect = ConnectionError("Connection refused")
    db = RedisMemoryDb(prefix="test")

    with pytest.raises(ConnectionError):
        db.create()


def test_memory_exists(memory_db, mock_redis_client):
    """Test checking if memory exists."""
    # Create a test memory
    memory = MemoryRow(id="test-id-1", user_id="test-user", memory={"text": "Test memory"})

    # Mock that memory doesn't exist initially
    assert not memory_db.memory_exists(memory)

    # Set the memory in Redis
    key = "test_memory:test-id-1"
    mock_redis_client.set(key, '{"id": "test-id-1", "user_id": "test-user", "memory": {"text": "Test memory"}}')

    # Now it should exist
    assert memory_db.memory_exists(memory)


def test_upsert_memory(memory_db, mock_redis_client):
    """Test upserting a memory."""
    # Create a test memory
    memory = MemoryRow(id="test-id-1", user_id="test-user", memory={"text": "Test memory"})

    # Upsert memory
    with patch("time.time", return_value=12345):
        result = memory_db.upsert_memory(memory)

    # Verify result
    assert result is not None
    assert result.id == memory.id

    # Verify Redis was called with correct data
    mock_redis_client.set.assert_called_with(
        "test_memory:test-id-1",
        ANY,  # We don't care about exact JSON, just that it was called
    )

    # Verify memory now exists
    assert memory_db.memory_exists(memory)


def test_read_memories(memory_db, mock_redis_client):
    """Test reading memories from Redis."""
    # Set up test data
    mock_redis_client.set(
        "test_memory:1", '{"id": "1", "user_id": "user1", "memory": {"text": "Memory 1"}, "created_at": 1000}'
    )
    mock_redis_client.set(
        "test_memory:2", '{"id": "2", "user_id": "user1", "memory": {"text": "Memory 2"}, "created_at": 2000}'
    )
    mock_redis_client.set(
        "test_memory:3", '{"id": "3", "user_id": "user2", "memory": {"text": "Memory 3"}, "created_at": 3000}'
    )

    # Test reading all memories
    all_memories = memory_db.read_memories()
    assert len(all_memories) == 3

    # Test filtering by user_id
    user1_memories = memory_db.read_memories(user_id="user1")
    assert len(user1_memories) == 2
    assert all(m.user_id == "user1" for m in user1_memories)

    # Test limit
    limited_memories = memory_db.read_memories(limit=2)
    assert len(limited_memories) == 2

    # Test sorting (default is descending by created_at)
    sorted_desc = memory_db.read_memories()
    assert sorted_desc[0].id == "3"  # Newest first

    # Test sorting ascending
    sorted_asc = memory_db.read_memories(sort="asc")
    assert sorted_asc[0].id == "1"  # Oldest first


def test_delete_memory(memory_db, mock_redis_client):
    """Test deleting a memory."""
    # Set up test data
    mock_redis_client.set(
        "test_memory:to-delete", '{"id": "to-delete", "user_id": "user1", "memory": {"text": "Delete me"}}'
    )

    # Verify memory exists
    assert mock_redis_client.exists("test_memory:to-delete")

    # Delete memory
    memory_db.delete_memory("to-delete")

    # Verify it was deleted
    assert not mock_redis_client.exists("test_memory:to-delete")

    # Delete non-existent memory (should not raise)
    memory_db.delete_memory("does-not-exist")


def test_drop_table(memory_db, mock_redis_client):
    """Test dropping the table."""
    # Set up test data
    mock_redis_client.set("test_memory:1", "{}")
    mock_redis_client.set("test_memory:2", "{}")
    mock_redis_client.set("other_prefix:3", "{}")

    # Drop table
    memory_db.drop_table()

    # Verify only test_memory keys were deleted
    assert not mock_redis_client.exists("test_memory:1")
    assert not mock_redis_client.exists("test_memory:2")
    assert mock_redis_client.exists("other_prefix:3")


def test_table_exists(memory_db, mock_redis_client):
    """Test table_exists method."""
    # Initially no keys, so table doesn't exist
    assert not memory_db.table_exists()

    # Add a key
    mock_redis_client.set("test_memory:1", "{}")

    # Now table should exist
    assert memory_db.table_exists()

    # Delete the key
    mock_redis_client.delete("test_memory:1")

    # Table should not exist again
    assert not memory_db.table_exists()


def test_clear(memory_db, mock_redis_client):
    """Test clearing all memories."""
    # Set up test data
    mock_redis_client.set("test_memory:1", "{}")
    mock_redis_client.set("test_memory:2", "{}")
    mock_redis_client.set("other_prefix:3", "{}")

    # Clear table
    result = memory_db.clear()

    # Verify result and only test_memory keys were deleted
    assert result
    assert not mock_redis_client.exists("test_memory:1")
    assert not mock_redis_client.exists("test_memory:2")
    assert mock_redis_client.exists("other_prefix:3")


def test_error_handling(memory_db, mock_redis_client):
    """Test error handling in methods."""
    # Make Redis client raise an exception for various methods
    mock_redis_client.get.side_effect = Exception("Test error")
    mock_redis_client.scan_iter.side_effect = Exception("Test error")

    # Methods should handle errors gracefully
    assert memory_db.read_memories() == []
    assert not memory_db.table_exists()

    # Reset side effects
    mock_redis_client.get.side_effect = lambda key: None
    mock_redis_client.scan_iter.side_effect = lambda match, count=None: []

    # Test error in upsert
    mock_redis_client.set.side_effect = Exception("Test error")
    memory = MemoryRow(id="test-error", user_id="user", memory={"text": "Test"})
    result = memory_db.upsert_memory(memory)
    assert result is None

    # Test error in delete
    mock_redis_client.delete.side_effect = Exception("Test error")
    # Should not raise
    memory_db.delete_memory("test-id")

    # Test error in clear - set scan_iter to raise exception again
    mock_redis_client.scan_iter.side_effect = Exception("Test error")
    result = memory_db.clear()
    # The method should return False when there's an error
    assert result is False
