"""Fixtures for AsyncMongoDb integration tests"""

from unittest.mock import Mock

import pytest
import pytest_asyncio

from agno.db.mongo import AsyncMongoDb

# Try to import Motor
try:
    from motor.motor_asyncio import AsyncIOMotorClient

    MOTOR_AVAILABLE = True
except ImportError:
    MOTOR_AVAILABLE = False
    AsyncIOMotorClient = None  # type: ignore

# Try to import PyMongo async
try:
    from pymongo import AsyncMongoClient

    PYMONGO_ASYNC_AVAILABLE = True
except ImportError:
    PYMONGO_ASYNC_AVAILABLE = False
    AsyncMongoClient = None  # type: ignore

# Require at least one library
if not MOTOR_AVAILABLE and not PYMONGO_ASYNC_AVAILABLE:
    pytest.skip("Neither motor nor pymongo async installed", allow_module_level=True)


@pytest.fixture
def mock_async_mongo_client():
    """Create a mock async MongoDB client (Motor)"""
    if MOTOR_AVAILABLE:
        client = Mock(spec=AsyncIOMotorClient)
        return client
    else:
        pytest.skip("Motor not available for mock client")


@pytest.fixture
def mock_pymongo_async_client():
    """Create a mock async MongoDB client (PyMongo async)"""
    if PYMONGO_ASYNC_AVAILABLE:
        client = Mock(spec=AsyncMongoClient)
        return client
    else:
        pytest.skip("PyMongo async not available for mock client")


@pytest.fixture
def async_mongo_db(mock_async_mongo_client) -> AsyncMongoDb:
    """Create an AsyncMongoDb instance with mock client"""
    return AsyncMongoDb(
        db_client=mock_async_mongo_client,
        db_name="test_db",
        session_collection="test_sessions",
        memory_collection="test_memories",
        metrics_collection="test_metrics",
        eval_collection="test_evals",
        knowledge_collection="test_knowledge",
        culture_collection="test_culture",
    )


@pytest_asyncio.fixture
async def async_mongo_db_real():
    """Create AsyncMongoDb with real MongoDB connection

    This fixture connects to a real MongoDB instance running on localhost:27017.
    Make sure MongoDB is running before running these integration tests.
    These tests assume:
    - Username=mongoadmin
    - Password=secret
    Uses auto-selected client type (prefers PyMongo async if available).
    """
    # Use local MongoDB
    db_url = "mongodb://mongoadmin:secret@localhost:27017"

    db = AsyncMongoDb(
        db_url=db_url,
        db_name="test_agno_async_mongo",
        session_collection="test_sessions",
        memory_collection="test_memories",
        metrics_collection="test_metrics",
        eval_collection="test_evals",
        knowledge_collection="test_knowledge",
        culture_collection="test_culture",
    )

    yield db

    # Cleanup: Drop the test database after tests
    try:
        await db.database.client.drop_database("test_agno_async_mongo")
    except Exception:
        pass  # Ignore cleanup errors

    # Close the client (handle both Motor and PyMongo async)
    if db._client:
        if db._client_type == AsyncMongoDb.CLIENT_TYPE_PYMONGO_ASYNC:
            await db._client.close()
        else:
            db._client.close()
