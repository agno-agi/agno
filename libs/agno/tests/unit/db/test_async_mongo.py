import asyncio
from unittest.mock import Mock, patch

import pytest
from pymongo import AsyncMongoClient

from agno.db.mongo import AsyncMongoDb


def test_id_is_deterministic():
    """Test that two db instances with same URL have same ID"""
    db1 = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    db2 = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    assert db1.id == db2.id


def test_id_different_for_different_configs():
    """Test that different configs produce different IDs"""
    db1 = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db1")
    db2 = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db2")

    assert db1.id != db2.id


def test_init_with_url():
    """Test initialization with database URL"""
    db = AsyncMongoDb(
        db_url="mongodb://localhost:27017",
        db_name="test_db",
        session_collection="sessions",
        memory_collection="memories",
    )

    assert db.db_url == "mongodb://localhost:27017"
    assert db.db_name == "test_db"
    assert db.session_table_name == "sessions"
    assert db.memory_table_name == "memories"


def test_init_with_client():
    """Test initialization with provided client"""
    test_client = AsyncMongoClient()
    db = AsyncMongoDb(db_client=test_client, db_name="test_db", session_collection="sessions")

    assert db._provided_client == test_client
    assert db.db_name == "test_db"
    assert db.session_table_name == "sessions"


def test_init_no_url_or_client():
    """Test initialization fails without URL or client"""
    with pytest.raises(ValueError, match="One of db_url or db_client must be provided"):
        AsyncMongoDb(db_name="test_db")


def test_init_defaults():
    """Test initialization with defaults"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017")

    assert db.db_name == "agno"
    assert db._client is None
    assert db._database is None
    assert db._event_loop is None


def test_init_with_all_collections():
    """Test initialization with all collection names"""
    db = AsyncMongoDb(
        db_url="mongodb://localhost:27017",
        db_name="test_db",
        session_collection="sessions",
        memory_collection="memories",
        metrics_collection="metrics",
        eval_collection="evals",
        knowledge_collection="knowledge",
        culture_collection="culture",
    )

    assert db.session_table_name == "sessions"
    assert db.memory_table_name == "memories"
    assert db.metrics_table_name == "metrics"
    assert db.eval_table_name == "evals"
    assert db.knowledge_table_name == "knowledge"
    assert db.culture_table_name == "culture"


@pytest.mark.asyncio
async def test_initialization_flags_cleared_on_event_loop_change():
    """Test that _initialized flags are cleared when event loop changes.

    This is the primary fix for the bug. When the event loop changes,
    both collection caches AND initialization flags must be cleared.

    Bug context: After upgrading from 2.2.7 to 2.2.9, users experienced
    "Event loop is closed" errors when calling aupsert_session in custom
    situations with subagents, particularly when multiple asyncio.run()
    calls were made.
    """
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_event_loop_fix")

    # First operation - create collections
    await db._get_collection("sessions", create_collection_if_not_found=True)
    await db._get_collection("memories", create_collection_if_not_found=True)

    # Should have collections cached
    assert hasattr(db, "session_collection")
    assert hasattr(db, "memory_collection")

    # Should have initialized flags
    initialized_flags_before = [attr for attr in vars(db).keys() if attr.endswith("_initialized")]
    assert len(initialized_flags_before) >= 2, "Should have initialized flags"

    # Manually simulate event loop change (what _ensure_client does)
    db._event_loop = None  # Force it to detect a "new" loop next time
    _ = db.db_client  # This should trigger cleanup

    # After loop change, collections AND initialized flags should be cleared
    assert not hasattr(db, "session_collection"), "session_collection should be cleared"
    assert not hasattr(db, "memory_collection"), "memory_collection should be cleared"

    # Check that ALL _initialized flags are cleared (this is the fix!)
    initialized_flags_after = [attr for attr in vars(db).keys() if attr.endswith("_initialized")]
    assert len(initialized_flags_after) == 0, (
        f"All _initialized flags should be cleared, but found: {initialized_flags_after}"
    )


@pytest.mark.asyncio
async def test_indexes_awaited_properly():
    """Test that index creation is properly awaited.

    The second part of the fix ensures create_collection_indexes_async
    properly awaits Motor's async create_index() calls, preventing
    unawaited futures from being left on the event loop.
    """
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_await_indexes")

    # This should complete without hanging or leaving pending futures
    collection = await db._get_collection("sessions", create_collection_if_not_found=True)
    assert collection is not None

    # Verify no pending tasks (excluding current task)
    pending = [task for task in asyncio.all_tasks() if not task.done()]
    current_task = asyncio.current_task()
    pending = [task for task in pending if task != current_task]

    assert len(pending) == 0, f"Should have no pending tasks, but found: {pending}"


@pytest.mark.asyncio
async def test_collection_cache_reset_on_event_loop_change():
    """Test that all collection caches are reset on event loop change"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_cache_reset")

    # Create collections
    await db._get_collection("sessions", create_collection_if_not_found=True)
    await db._get_collection("memories", create_collection_if_not_found=True)
    await db._get_collection("metrics", create_collection_if_not_found=True)

    # Should have multiple collections cached
    collections_before = [attr for attr in vars(db).keys() if attr.endswith("_collection")]
    assert len(collections_before) >= 3

    # Force event loop change
    db._event_loop = None
    _ = db.db_client

    # All collections should be cleared
    collections_after = [attr for attr in vars(db).keys() if attr.endswith("_collection")]
    assert len(collections_after) == 0, f"All collections should be cleared, found: {collections_after}"


@pytest.mark.asyncio
async def test_get_collection_invalid_type():
    """Test getting collection with invalid type raises error"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_invalid_type")

    with pytest.raises(ValueError, match="Unknown table type"):
        await db._get_collection("invalid_type")


@pytest.mark.asyncio
async def test_get_collection_without_table_name():
    """Test that _get_collection raises error if table name not configured"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_no_table_name")

    # Manually clear the table name to simulate not being configured
    db.session_table_name = None  # type: ignore

    with pytest.raises(ValueError, match="Session collection was not provided"):
        await db._get_collection("sessions", create_collection_if_not_found=True)


def test_db_client_property():
    """Test db_client property calls _ensure_client"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_client_property")

    with patch.object(db, "_ensure_client", return_value=Mock()) as mock_ensure:
        client = db.db_client
        assert client is not None
        mock_ensure.assert_called_once()


def test_should_reset_collection_cache():
    """Test _should_reset_collection_cache method"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_should_reset")

    # Before any event loop is set
    assert db._should_reset_collection_cache() is False

    # After setting event loop
    db._event_loop = asyncio.get_event_loop()
    # Should return False when same loop
    assert db._should_reset_collection_cache() is False


def test_client_type_constants():
    """Test that client type constants are defined correctly"""
    assert AsyncMongoDb.CLIENT_TYPE_MOTOR == "motor"
    assert AsyncMongoDb.CLIENT_TYPE_PYMONGO_ASYNC == "pymongo_async"
    assert AsyncMongoDb.CLIENT_TYPE_UNKNOWN == "unknown"


def test_detect_motor_client_type():
    """Test that Motor client is correctly detected"""
    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        mock_client = Mock(spec=AsyncIOMotorClient)
        db = AsyncMongoDb(db_client=mock_client, db_name="test_db")
        assert db._client_type == AsyncMongoDb.CLIENT_TYPE_MOTOR
    except ImportError:
        pytest.skip("Motor not available")


def test_detect_pymongo_async_client_type():
    """Test that PyMongo async client is correctly detected"""
    # Check if PyMongo async is available
    try:
        import pymongo  # noqa: F401

        # Verify AsyncMongoClient exists
        if not hasattr(pymongo, "AsyncMongoClient"):
            pytest.skip("PyMongo async not available")
    except ImportError:
        pytest.skip("PyMongo async not available")

    # Create a mock that will pass isinstance check
    # We need to make the mock actually be an instance of AsyncMongoClient
    # or use a real instance if possible, or patch the detection
    mock_client = Mock()
    # Set the class name and module to help with fallback detection
    mock_client.__class__.__name__ = "AsyncMongoClient"
    mock_client.__class__.__module__ = "pymongo"
    db = AsyncMongoDb(db_client=mock_client, db_name="test_db")
    assert db._client_type == AsyncMongoDb.CLIENT_TYPE_PYMONGO_ASYNC


def test_auto_select_preferred_client_from_url():
    """Test that preferred client is auto-selected when creating from URL"""
    # Import availability flags from the module
    from agno.db.mongo.async_mongo import MOTOR_AVAILABLE, PYMONGO_ASYNC_AVAILABLE

    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    # Should prefer PyMongo async if available, else Motor
    if PYMONGO_ASYNC_AVAILABLE:
        assert db._client_type == AsyncMongoDb.CLIENT_TYPE_PYMONGO_ASYNC
    elif MOTOR_AVAILABLE:
        assert db._client_type == AsyncMongoDb.CLIENT_TYPE_MOTOR
    else:
        pytest.fail("Neither client type available")
