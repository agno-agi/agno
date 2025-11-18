"""Fixtures for AsyncMongoDb integration tests"""

from unittest.mock import Mock

import pytest
import pytest_asyncio

from agno.db.mongo import AsyncMongoDb

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    pytest.skip("motor not installed", allow_module_level=True)


@pytest.fixture
def mock_async_mongo_client():
    """Create a mock async MongoDB client"""
    client = Mock(spec=AsyncIOMotorClient)
    return client


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
    """
    # Use local MongoDB
    db_url = "mongodb://localhost:27017"

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

    # Close the client
    if db._client:
        db._client.close()
