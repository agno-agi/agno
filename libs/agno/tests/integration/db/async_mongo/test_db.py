"""Integration tests for the setup and main methods of the AsyncMongoDb class

Required to have a running MongoDB instance to run these tests.

These tests assume:
- Username=mongoadmin
- Password=secret
"""

from datetime import datetime, timezone

import pytest

try:
    from agno.db.mongo import AsyncMongoDb
except ImportError:
    pytest.skip(
        "Neither motor nor pymongo async installed, skipping AsyncMongoDb integration tests", allow_module_level=True
    )


@pytest.mark.asyncio
async def test_init_with_db_url():
    """Test initialization with actual database URL format"""
    db_url = "mongodb://mongoadmin:secret@localhost:27017"

    db = AsyncMongoDb(db_url=db_url, db_name="test_init_db", session_collection="test_async_mongo_sessions")
    assert db.db_url == db_url
    assert db.session_table_name == "test_async_mongo_sessions"
    assert db.db_name == "test_init_db"

    # Test connection
    collection_names = await db.database.list_collection_names()
    assert isinstance(collection_names, list)

    # Cleanup
    await db.database.client.drop_database("test_init_db")
    db._client.close()  # type: ignore


@pytest.mark.asyncio
async def test_table_exists(async_mongo_db_real):
    """Test checking if a collection exists in MongoDB"""
    # Create a test collection
    await async_mongo_db_real.database["test_collection"].insert_one({"test": "data"})

    # Check if it exists
    exists = await async_mongo_db_real.table_exists("test_collection")
    assert exists is True

    # Check non-existent collection
    exists = await async_mongo_db_real.table_exists("nonexistent_collection")
    assert exists is False


@pytest.mark.asyncio
async def test_create_session_collection_integration(async_mongo_db_real):
    """Test actual session collection creation with MongoDB"""
    # Get session collection (will create it)
    collection = await async_mongo_db_real._get_collection("sessions", create_collection_if_not_found=True)
    assert collection is not None

    # Verify collection exists in database
    collection_names = await async_mongo_db_real.database.list_collection_names()
    assert async_mongo_db_real.session_table_name in collection_names

    # Verify we can insert and query
    await collection.insert_one({"session_id": "test-123", "test": "data"})
    doc = await collection.find_one({"session_id": "test-123"})
    assert doc is not None
    assert doc["test"] == "data"


@pytest.mark.asyncio
async def test_create_collection_with_indexes(async_mongo_db_real):
    """Test that indexes are created correctly"""
    # Create sessions collection (should create indexes)
    await async_mongo_db_real._get_collection("sessions", create_collection_if_not_found=True)

    # Verify indexes exist
    collection = async_mongo_db_real.database[async_mongo_db_real.session_table_name]
    indexes = await collection.index_information()

    # Should have indexes (at minimum the default _id index)
    assert len(indexes) > 0
    assert "_id_" in indexes  # Default MongoDB index


@pytest.mark.asyncio
async def test_get_collection_caching(async_mongo_db_real):
    """Test that collections are cached after first retrieval"""
    # First call should create the collection
    collection1 = await async_mongo_db_real._get_collection("sessions", create_collection_if_not_found=True)
    assert hasattr(async_mongo_db_real, "session_collection")

    # Second call should use cached collection
    collection2 = await async_mongo_db_real._get_collection("sessions", create_collection_if_not_found=True)

    # Should be the same collection object
    assert collection1.name == collection2.name


@pytest.mark.asyncio
async def test_multiple_collections(async_mongo_db_real):
    """Test creating and using multiple collections"""
    # Create multiple collections
    sessions_coll = await async_mongo_db_real._get_collection("sessions", create_collection_if_not_found=True)
    memories_coll = await async_mongo_db_real._get_collection("memories", create_collection_if_not_found=True)
    metrics_coll = await async_mongo_db_real._get_collection("metrics", create_collection_if_not_found=True)

    assert sessions_coll is not None
    assert memories_coll is not None
    assert metrics_coll is not None

    # Verify all collections are cached
    assert hasattr(async_mongo_db_real, "session_collection")
    assert hasattr(async_mongo_db_real, "memory_collection")
    assert hasattr(async_mongo_db_real, "metrics_collection")

    # Verify they're different collections
    assert sessions_coll.name != memories_coll.name
    assert sessions_coll.name != metrics_coll.name


@pytest.mark.asyncio
async def test_full_workflow(async_mongo_db_real):
    """Test a complete workflow of creating and using collections"""
    # Get collections (will create them)
    session_collection = await async_mongo_db_real._get_collection("sessions", create_collection_if_not_found=True)
    await async_mongo_db_real._get_collection("memories", create_collection_if_not_found=True)

    # Verify collections are cached
    assert hasattr(async_mongo_db_real, "session_collection")
    assert hasattr(async_mongo_db_real, "memory_collection")

    # Verify we can insert and query data (basic smoke test)
    # Insert a test session
    await session_collection.insert_one(
        {
            "session_id": "test-session-123",
            "session_type": "agent",
            "created_at": int(datetime.now(timezone.utc).timestamp() * 1000),
            "session_data": {"test": "data"},
        }
    )

    # Query it back
    doc = await session_collection.find_one({"session_id": "test-session-123"})

    assert doc is not None
    assert doc["session_type"] == "agent"
    assert doc["session_data"]["test"] == "data"


@pytest.mark.asyncio
async def test_event_loop_handling_in_integration(async_mongo_db_real):
    """Test that event loop changes are handled correctly in real scenario

    This test verifies the fix for the 'Event loop is closed' bug.
    """
    # Create collections in current event loop
    await async_mongo_db_real._get_collection("sessions", create_collection_if_not_found=True)
    await async_mongo_db_real._get_collection("memories", create_collection_if_not_found=True)

    # Verify collections are cached
    assert hasattr(async_mongo_db_real, "session_collection")
    assert hasattr(async_mongo_db_real, "memory_collection")

    # Count initialized flags
    initialized_before = [attr for attr in vars(async_mongo_db_real).keys() if attr.endswith("_initialized")]
    assert len(initialized_before) >= 2

    # Simulate event loop change
    async_mongo_db_real._event_loop = None
    _ = async_mongo_db_real.db_client

    # Collections and flags should be cleared
    assert not hasattr(async_mongo_db_real, "session_collection")
    assert not hasattr(async_mongo_db_real, "memory_collection")

    # Initialized flags should be cleared (this is the fix!)
    initialized_after = [attr for attr in vars(async_mongo_db_real).keys() if attr.endswith("_initialized")]
    assert len(initialized_after) == 0, f"Expected 0 initialized flags, found: {initialized_after}"

    # Should be able to recreate collections without errors
    collection = await async_mongo_db_real._get_collection("sessions", create_collection_if_not_found=True)
    assert collection is not None
