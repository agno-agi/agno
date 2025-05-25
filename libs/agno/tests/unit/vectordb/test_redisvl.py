import pytest
import redis
import redis.asyncio as redis_async
from typing import Any, Dict, Generator, List
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from libs.agno.agno.vectordb.redisvl.redisvl import RedisVL
from agno.document import Document
import numpy as np
from redisvl.exceptions import RedisSearchError
import types


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Create a mock embedder."""
    embedder = MagicMock()
    embedder.dimensions = 384
    embedder.get_embedding.return_value = [0.1] * 384
    embedder.embedding_dim = 384
    return embedder

@pytest.fixture(scope="function")
def mock_redisvl_client() -> Generator[MagicMock, None, None]:
    """Create a mock RedisVector client."""
    with patch("redis.Redis") as mock_redis_class:
        # Create mock instance for Redis client
        mock_redis_instance = MagicMock(spec=redis.Redis)
        
        # Setup the mock class to return the mock instance
        mock_redis_class.return_value = mock_redis_instance

        # Mock Redis commands used in RedisVector context
        mock_redis_instance.ping = MagicMock(return_value=True)
        mock_redis_instance.ft = MagicMock()  # For Redisearch module commands
        
        # Mock FT.CREATE, FT.DROPINDEX, FT.SEARCH, etc.
        mock_redis_instance.ft.create_index = MagicMock(return_value=None)
        mock_redis_instance.ft.drop_index = MagicMock(return_value=None)
        mock_redis_instance.ft.search = MagicMock(return_value={"total": 0, "documents": []})
        mock_redis_instance.ft.aggregate = MagicMock(return_value=[])
        mock_redis_instance.ft.info = MagicMock(return_value={"index_name": "test_index"})

        # Mock common vector commands, e.g., for adding vectors
        mock_redis_instance.hset = MagicMock(return_value=True)
        mock_redis_instance.hgetall = MagicMock(return_value={})
        mock_redis_instance.delete = MagicMock(return_value=1)

        yield mock_redis_instance

class AsyncCursor:
    """Helper async iterator for mocking async cursor results."""
    def __init__(self, items):
        self._items = items
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item

@pytest.fixture(scope="function")
def mock_async_redisvl_client() -> Generator[AsyncMock, None, None]:
    """Create a mock async RedisVector client."""
    with patch("redis.asyncio.Redis") as mock_redis_class:
        mock_redis_instance = AsyncMock(spec=redis_async.Redis)

        # Setup the patched class to return the async mock instance
        mock_redis_class.return_value = mock_redis_instance

        # Mock async ping method
        mock_redis_instance.ping = AsyncMock(return_value=True)

        # Mock the Redisearch FT sub-client as an AsyncMock with async methods
        mock_redis_instance.ft = AsyncMock()

        # Async mocks for Redisearch FT commands
        mock_redis_instance.ft.create_index = AsyncMock(return_value=None)
        mock_redis_instance.ft.drop_index = AsyncMock(return_value=None)
        
        # Simulate async search returning a dict with total and documents
        mock_redis_instance.ft.search = AsyncMock(return_value={"total": 0, "documents": []})

        # Mock an async aggregate cursor
        sample_aggregate_result = [
            {"id": "doc_0", "content": "Test document 0", "score": 0.95},
        ]
        mock_redis_instance.ft.aggregate = AsyncMock(return_value=AsyncCursor(sample_aggregate_result))

        mock_redis_instance.ft.info = AsyncMock(return_value={"index_name": "test_index"})

        # Mock common Redis vector commands async style
        mock_redis_instance.hset = AsyncMock(return_value=True)
        mock_redis_instance.hgetall = AsyncMock(return_value={})
        mock_redis_instance.delete = AsyncMock(return_value=1)

        yield mock_redis_instance

    
@pytest.fixture(scope="function")
def vector_db(mock_redisvl_client: MagicMock, mock_embedder: MagicMock) -> RedisVL:
    """Create a RedisVL instance."""
    index_name = f"test_vectors_{uuid.uuid4().hex[:8]}"
    db = RedisVL(
        index_name=index_name,
        embedder=mock_embedder,
        client=mock_redisvl_client,
        namespace="test_vectordb",
    )

    # Setup specific mocks or attributes for this instance
    # If your RedisVL uses a client attribute or similar, assign mocks here
    db._client = mock_redisvl_client
    db._index_name = index_name

    return db


@pytest.fixture(scope="function")
def async_vector_db(mock_async_redisvl_client: AsyncMock, mock_embedder: MagicMock) -> RedisVL:
    """Create an async RedisVL instance for tests."""
    index_name = f"test_vectors_{uuid.uuid4().hex[:8]}"

    with patch("redis.asyncio.Redis", return_value=mock_async_redisvl_client):
        db = RedisVL(
            index_name=index_name,
            embedder=mock_embedder,
            namespace="test_vectordb",
        )

        # Setup async client and index for this instance
        db._async_client = mock_async_redisvl_client
        db._async_index_name = index_name

        yield db
    

@pytest.fixture
def mock_document():
    return {"content": "This is a test document."}

@pytest.fixture
def mock_query():
    return "test"

# --------------------------
# Synchronous Tests
# --------------------------

def test_insert_document():
    # Create a RedisVL instance with mocks
    mock_client = MagicMock()
    mock_embedder = MagicMock()
    db = RedisVL(index_name="test_index", embedder=mock_embedder, client=mock_client, db_url="redis://localhost:6379")

    # Mock get_index to return a mock index
    mock_index = MagicMock()
    db.get_index = MagicMock(return_value=mock_index)

    # Mock prepare_doc to return a dict with "_id"
    def prepare_doc_side_effect(doc, filters=None):
        return {"_id": doc.name, "content": doc.content, "filters": filters}
    db.prepare_doc = MagicMock(side_effect=prepare_doc_side_effect)

    # Mock index.load method to just return a string (simulate loaded data)
    mock_index.load = MagicMock(return_value="loaded_data")

    # Create some sample Document objects
    documents = [
        Document(name="doc1", content="This is doc 1"),
        Document(name="doc2", content="This is doc 2"),
    ]

    # Call the insert method
    db.insert(documents)

    # Assert get_index was called once
    db.get_index.assert_called_once()

    # Assert prepare_doc was called once per document, with no filters
    assert db.prepare_doc.call_count == 2
    db.prepare_doc.assert_any_call(documents[0], None)
    db.prepare_doc.assert_any_call(documents[1], None)

    # Assert index.load was called once with the list of prepared documents
    mock_index.load.assert_called_once()
    called_args, called_kwargs = mock_index.load.call_args
    inserted_docs = called_kwargs.get("data") or (called_args[0] if called_args else None)

    # Check inserted_docs is a list of dicts with expected _id values
    assert isinstance(inserted_docs, list)
    assert inserted_docs[0]["_id"] == "doc1"
    assert inserted_docs[1]["_id"] == "doc2"


def test_search_method():
    # Setup the RedisVL instance with mocks
    mock_embedder = MagicMock()
    mock_embedder.get_embedding = MagicMock(return_value=[0.1, 0.2, 0.3, 0.4])  # dummy embedding

    db = RedisVL(
        index_name="test_index",
        embedder=mock_embedder,
        db_url="redis://localhost:6379",
    )

    # Patch the _search_index_exists method to return True
    db._search_index_exists = MagicMock(return_value=True)

    # Patch SearchIndex.from_existing to return a mock index object
    mock_index = MagicMock()
    with patch("libs.agno.agno.vectordb.redisvl.redisvl.SearchIndex.from_existing", return_value=mock_index):
        # Mock the index.query method to return sample Documents or results
        expected_results = [
            Document(name="doc1", content="test content 1"),
            Document(name="doc2", content="test content 2"),
        ]
        mock_index.query = MagicMock(return_value=expected_results)

        # Set attributes used by the search method
        db.search_index_name = "test_index"
        db.embedding_name = "embedding_vector"
        db.return_fields = ["name", "content"]
        db.distance_threshold = None  # test path without distance threshold

        # Run search
        query = "example query"
        results = db.search(query, limit=2)

        # Assertions
        mock_embedder.get_embedding.assert_called_once_with(query)
        mock_index.query.assert_called_once()
        assert results == expected_results

        # Test with distance_threshold set to trigger RangeQuery path
        db.distance_threshold = 0.8
        mock_index.query.reset_mock()
        results = db.search(query, limit=2)
        mock_index.query.assert_called_once()

def test_search_embedding_none():
    # Setup RedisVL with embedder that returns None embedding
    mock_embedder = MagicMock()
    mock_embedder.get_embedding = MagicMock(return_value=None)
    db = RedisVL(index_name="test_index", embedder=mock_embedder, db_url="redis://localhost:6379")

    # Call search, expect empty list returned due to None embedding
    results = db.search("some query")
    assert results == []

@patch("redisvl.index.SearchIndex")  # Patch the SearchIndex class
@patch("time.sleep", return_value=None)  # Patch time.sleep to skip real delays
def test_drop_success(mock_sleep, mock_search_index):
    # Setup
    mock_index_instance = MagicMock()
    mock_search_index.from_existing.return_value = mock_index_instance

    db = RedisVL(index_name="test_index", embedder=MagicMock(), db_url="redis://localhost:6379")
    db.search_index_name = "test_index"
    db._search_index_exists = MagicMock(return_value=True)

    # Act
    db.drop()

    # Assert
    mock_search_index.from_existing.assert_called_once
    mock_index_instance.delete.assert_called_once

@patch("redisvl.index.SearchIndex")
@patch("time.sleep", return_value=None)
def test_drop_index_does_not_exist(mock_sleep, mock_search_index):
    db = RedisVL(index_name="test_index", embedder=MagicMock(), db_url="redis://localhost:6379")
    db.search_index_name = "test_index"
    db._search_index_exists = MagicMock(return_value=False)

    db.drop()

    mock_search_index.from_existing.assert_not_called()
    assert mock_sleep.call_count == 1  # Final sleep still occurs

# --------------------------
# Async Tests
# --------------------------

@pytest.mark.asyncio
@patch("redisvl.index.AsyncSearchIndex.from_existing")
async def test_async_search_success(mock_from_existing):
    # Prepare mocks
    mock_index = AsyncMock()
    mock_query_result = [
        Document(
            id="doc_1",
            content="This is a test document",
            meta_data={"type": "test"},
            name="test_doc"
        )
    ]
    mock_index.query = AsyncMock(return_value=mock_query_result)
    mock_from_existing.return_value = mock_index

    # Create instance of the class you're testing
    db = RedisVL(
        embedder=AsyncMock(),
        db_url="redis://localhost:6379",
        search_index_name="test_index"
    )

    # Mock embedding
    fake_embedding = np.random.rand(1536).tolist()
    db.embedder.get_embedding = AsyncMock(return_value=fake_embedding)

    # Mock _async_search_index_exists to return True
    db._async_search_index_exists = AsyncMock(return_value=True)

    # Optionally, patch _get_async_client if used
    db._get_async_client = AsyncMock(return_value=AsyncMock())
    db._async_client = await db._get_async_client()

    # Run async_search
    results = await db.async_search("test query", limit=1)

    # Assertions
    assert isinstance(results, list)
    if results:
        assert len(results) == 1
        assert results[0].id == "doc_1"
    mock_index.query.assert_awaited_once()

@pytest.mark.asyncio
@patch("redisvl.index.AsyncSearchIndex.from_existing")
async def test_async_drop_success(mock_from_existing, caplog):
    # Setup mocks
    mock_index = AsyncMock()
    mock_index.delete = AsyncMock()
    mock_from_existing.return_value = mock_index

    # Create instance of the class under test
    db = RedisVL(
        db_url="redis://localhost:6379",
        search_index_name="test_index"
    )

    # Mock _async_search_index_exists to True
    db._async_search_index_exists = AsyncMock(return_value=True)

    # Patch time.sleep to avoid actual delay
    with patch("time.sleep", return_value=None):
        await db.async_drop()

    # Assert index.from_existing and delete called
    mock_from_existing.assert_awaited_once_with("test_index", redis_url=db.db_url)
    mock_index.delete.assert_awaited_once_with(drop=True)


@pytest.mark.asyncio
@patch("redisvl.index.AsyncSearchIndex.from_existing")
async def test_async_drop_index_not_exists(mock_from_existing, caplog):
    # Create instance
    db = RedisVL(
        db_url="redis://localhost:6379",
        search_index_name="test_index"
    )
    # Return False to simulate index doesn't exist
    db._async_search_index_exists = AsyncMock(return_value=False)

    with patch("time.sleep", return_value=None):
        await db.async_drop()

    # from_existing should never be called if index does not exist
    mock_from_existing.assert_not_called()
