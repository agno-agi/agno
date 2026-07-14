import uuid
from hashlib import md5
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from agno.knowledge.document import Document
from agno.vectordb.mongodb import MongoVectorDb


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Create a mock embedder."""
    embedder = MagicMock()
    embedder.dimensions = 384
    embedder.get_embedding.return_value = [0.1] * 384
    embedder.get_embedding_and_usage.return_value = ([0.1] * 384, None)  # (embedding, usage)
    embedder.embedding_dim = 384
    return embedder


@pytest.fixture(scope="function")
def mock_mongodb_client() -> Generator[MagicMock, None, None]:
    """Create a mock MongoDB client."""
    with patch("pymongo.MongoClient") as mock_client:
        # Create mock instances for client, db, and collection
        mock_collection = MagicMock(spec=Collection)
        mock_db = MagicMock(spec=Database)
        mock_client_instance = MagicMock(spec=MongoClient)

        # Setup the mock chain
        mock_client.return_value = mock_client_instance
        mock_client_instance.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_collection
        mock_db.list_collection_names = MagicMock(return_value=["test_vectors"])

        # Setup admin for ping
        mock_admin = MagicMock()
        mock_client_instance.admin = mock_admin
        mock_admin.command = MagicMock(return_value={"ok": 1})

        # Setup common collection methods
        mock_collection.create_search_index = MagicMock(return_value=None)
        mock_collection.list_search_indexes = MagicMock(return_value=[{"name": "vector_index_1"}])
        mock_collection.drop_search_index = MagicMock(return_value=None)
        mock_collection.aggregate = MagicMock(return_value=[])
        mock_collection.insert_many = MagicMock(return_value=None)
        mock_collection.find_one = MagicMock(return_value=None)
        mock_collection.delete_many = MagicMock(return_value=MagicMock(deleted_count=1))
        mock_collection.delete_one = MagicMock(return_value=MagicMock(deleted_count=1))
        mock_collection.drop = MagicMock()
        mock_collection.find = MagicMock(return_value=[])
        mock_collection.count_documents = MagicMock(return_value=0)

        yield mock_client_instance


class AsyncCursor:
    """Mock async cursor for MongoDB."""

    def __init__(self, data: List[Dict[str, Any]]):
        self.data = data
        self.current = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.current >= len(self.data):
            raise StopAsyncIteration
        value = self.data[self.current]
        self.current += 1
        return value


@pytest.fixture(scope="function")
def mock_async_mongodb_client() -> Generator[AsyncMock, None, None]:
    """Create a mock Async MongoDB client."""
    with patch("pymongo.AsyncMongoClient") as mock_client:
        # Create mock instances
        mock_collection = AsyncMock()
        mock_db = AsyncMock()
        mock_client_instance = AsyncMock()

        # Setup the mock chain
        mock_client.return_value = mock_client_instance
        mock_client_instance.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_collection
        mock_db.list_collection_names = AsyncMock(return_value=["test_vectors"])
        mock_db.create_collection = AsyncMock()

        # Setup admin for ping
        mock_admin = AsyncMock()
        mock_client_instance.admin = mock_admin
        mock_admin.command = AsyncMock(return_value={"ok": 1})

        # Setup collection methods
        mock_collection.create_search_index = AsyncMock()
        mock_collection.list_search_indexes = AsyncMock(return_value=[{"name": "vector_index_1"}])
        mock_collection.drop_search_index = AsyncMock()

        # Setup cursor for aggregate
        mock_result = [
            {
                "_id": "doc_0",
                "content": "This is test document 0",
                "meta_data": {"type": "test", "index": "0"},
                "name": "test_doc_0",
                "content_id": "content_0",
                "score": 0.95,
            }
        ]
        mock_cursor = AsyncCursor(mock_result)
        mock_collection.aggregate = AsyncMock(return_value=mock_cursor)

        mock_collection.insert_many = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.update_one = AsyncMock()
        mock_collection.delete_many = AsyncMock(return_value=AsyncMock(deleted_count=1))
        mock_collection.delete_one = AsyncMock(return_value=AsyncMock(deleted_count=1))
        mock_collection.drop = AsyncMock()

        yield mock_client_instance


@pytest.fixture(scope="function")
def vector_db(mock_mongodb_client: MagicMock, mock_embedder: MagicMock) -> MongoVectorDb:
    """Create a VectorDB instance."""
    collection_name = f"test_vectors_{uuid.uuid4().hex[:8]}"
    db = MongoVectorDb(
        collection_name=collection_name,
        embedder=mock_embedder,
        client=mock_mongodb_client,
        database="test_vectordb",
    )

    # Setup specific mocks for this instance
    db._db = mock_mongodb_client["test_vectordb"]
    db._collection = db._db[collection_name]

    # Mock the search index existence check to avoid tuple unpacking issues
    db._search_index_exists = MagicMock(return_value=True)

    # Mock _get_collection to ensure it returns the mocked collection
    db._get_collection = MagicMock(return_value=db._collection)

    return db


@pytest.fixture(scope="function")
def async_vector_db(mock_async_mongodb_client: AsyncMock, mock_embedder: MagicMock) -> MongoVectorDb:
    """Create a VectorDB instance for async tests."""
    collection_name = f"test_vectors_{uuid.uuid4().hex[:8]}"

    with patch("pymongo.AsyncMongoClient", return_value=mock_async_mongodb_client):
        db = MongoVectorDb(
            collection_name=collection_name,
            embedder=mock_embedder,
            database="test_vectordb",
        )

        # Setup the DB for async tests
        db._async_client = mock_async_mongodb_client
        db._async_db = mock_async_mongodb_client["test_vectordb"]
        db._async_collection = db._async_db[collection_name]

        yield db


def create_test_documents(num_docs: int = 3) -> List[Document]:
    """Helper function to create test documents."""
    return [
        Document(
            id=f"doc_{i}",
            content=f"This is test document {i}",
            meta_data={"type": "test", "index": str(i)},
            name=f"test_doc_{i}",
            content_id=f"content_{i}",
        )
        for i in range(num_docs)
    ]


def test_initialization(mock_mongodb_client: MagicMock, mock_embedder: MagicMock) -> None:
    """Test MongoDB VectorDB initialization."""
    # Test successful initialization
    db = MongoVectorDb(
        collection_name="test_vectors", database="test_vectordb", client=mock_mongodb_client, embedder=mock_embedder
    )
    assert db.collection_name == "test_vectors"
    assert db.database == "test_vectordb"

    # Test initialization failures for empty collection_name
    with pytest.raises(ValueError):
        MongoVectorDb(collection_name="", database="test_vectordb", client=mock_mongodb_client)

    with pytest.raises(ValueError):
        MongoVectorDb(collection_name="test_vectors", database="", client=mock_mongodb_client)


def test_insert_and_search(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock, mock_embedder: MagicMock) -> None:
    """Test document insertion and search functionality."""
    # Setup mock response for search
    mock_search_result = [
        {
            "_id": "doc_0",
            "content": "This is test document 0",
            "meta_data": {"type": "test", "index": "0"},
            "name": "test_doc_0",
            "content_id": "content_0",
            "score": 0.95,
        }
    ]

    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]
    collection.aggregate.return_value = mock_search_result

    # Insert test documents
    docs = create_test_documents(1)

    # Ensure documents have embeddings
    for doc in docs:
        doc.embedding = mock_embedder.get_embedding(doc.content)

    vector_db.insert(content_hash="test_hash", documents=docs)

    # Test search functionality
    results = vector_db.search("test document", limit=1)
    assert len(results) == 1
    assert all(isinstance(doc, Document) for doc in results)
    assert results[0].id == "doc_0"
    assert results[0].content_id == "content_0"

    # Verify the search pipeline was called correctly
    # Get the aggregate call args and handle potential typing issues
    args = collection.aggregate.call_args
    assert args is not None
    pipeline = args[0][0]
    assert isinstance(pipeline, list)

    # Check that the first pipeline stage is a vector search with the correct limit
    first_stage = pipeline[0]
    assert isinstance(first_stage, dict)
    assert "$vectorSearch" in first_stage
    vector_search = first_stage["$vectorSearch"]
    assert isinstance(vector_search, dict)
    assert "limit" in vector_search
    assert vector_search["limit"] == 1


def test_document_existence(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock) -> None:
    """Test document existence checking methods."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]

    # Setup mock responses for find_one
    def mock_find_one(query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # For name_exists
        if "name" in query and query["name"] == "test_doc_0":
            return {"_id": "doc_0", "content": "This is test document 0", "name": "test_doc_0"}
        # For id_exists
        if "_id" in query and query["_id"] == "doc_0":
            return {"_id": "doc_0", "content": "This is test document 0", "name": "test_doc_0"}
        return None

    collection.find_one.side_effect = mock_find_one

    # Test by name
    assert vector_db.name_exists("test_doc_0")
    assert not vector_db.name_exists("nonexistent")

    # Test by ID
    assert vector_db.id_exists("doc_0")
    assert not vector_db.id_exists("nonexistent")


def test_delete_by_id(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock) -> None:
    """Test deleting documents by ID."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]

    # Test successful deletion
    collection.delete_one.return_value = MagicMock(deleted_count=1)
    result = vector_db.delete_by_id("doc_0")
    assert result is True
    collection.delete_one.assert_called_with({"_id": "doc_0"})

    # Test deletion with no documents found
    collection.delete_one.return_value = MagicMock(deleted_count=0)
    result = vector_db.delete_by_id("nonexistent_id")
    assert result is True  # Should still return True for consistency


def test_delete_by_name(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock) -> None:
    """Test deleting documents by name."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]

    collection.delete_many.return_value = MagicMock(deleted_count=3)
    result = vector_db.delete_by_name("test_doc")

    assert result is True
    collection.delete_many.assert_called_with({"name": "test_doc"})


def test_delete_by_metadata(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock) -> None:
    """Test deleting documents by metadata."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]

    collection.delete_many.return_value = MagicMock(deleted_count=2)
    metadata = {"type": "test", "category": "sample"}
    result = vector_db.delete_by_metadata(metadata)

    assert result is True
    expected_query = {"meta_data.type": "test", "meta_data.category": "sample"}
    collection.delete_many.assert_called_with(expected_query)


def test_delete_by_content_id(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock) -> None:
    """Test deleting documents by content ID."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]

    collection.delete_many.return_value = MagicMock(deleted_count=5)
    result = vector_db.delete_by_content_id("content_123")

    assert result is True
    collection.delete_many.assert_called_with({"content_id": "content_123"})


def test_keyword_search_with_content_id(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock) -> None:
    """Test keyword search includes content_id field."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]

    # Setup mock cursor with content_id
    mock_results = [
        {
            "_id": "doc_0",
            "name": "test_doc_0",
            "content": "This contains the keyword test",
            "meta_data": {"type": "test"},
            "content_id": "content_0",
        }
    ]

    mock_cursor = MagicMock()
    mock_cursor.limit.return_value = mock_results
    mock_cursor.__iter__ = lambda x: iter(mock_results)
    collection.find.return_value = mock_cursor

    results = vector_db.keyword_search("test", limit=1)

    assert len(results) == 1
    assert results[0].content_id == "content_0"

    # Verify the find call included content_id in projection
    collection.find.assert_called_with(
        {"content": {"$regex": "test", "$options": "i"}},
        {"_id": 1, "name": 1, "content": 1, "meta_data": 1, "content_id": 1},
    )


def test_upsert(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock, mock_embedder: MagicMock) -> None:
    """Test upsert functionality."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]

    # Setup mock responses
    mock_doc = {"_id": "doc_0", "content": "Modified content", "name": "test_doc_0", "meta_data": {"type": "modified"}}
    collection.find_one.return_value = mock_doc
    collection.update_one = MagicMock(return_value=MagicMock(modified_count=1))

    # Modify document and upsert
    modified_doc = Document(
        id="doc_0",
        content="Modified content",
        meta_data={"type": "modified"},
        name="test_doc_0",
        content_id="content_0",
    )

    # Set the embedding for the document
    modified_doc.embedding = mock_embedder.get_embedding(modified_doc.content)

    # Mock the prepare_doc method to avoid embedding issues during test
    original_prepare_doc = vector_db.prepare_doc
    vector_db.prepare_doc = lambda content_hash, doc, filters=None: {
        "_id": md5(doc.content.encode("utf-8")).hexdigest(),
        "name": doc.name,
        "content": doc.content,
        "meta_data": doc.meta_data,
        "embedding": doc.embedding or [0.1] * 384,
        "content_id": doc.content_id,
        "content_hash": content_hash,
    }

    # Perform the upsert
    vector_db.upsert(content_hash="test_hash", documents=[modified_doc])

    # Verify the update was called
    collection.update_one.assert_called_once()

    # Restore original method
    vector_db.prepare_doc = original_prepare_doc


def test_delete(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock) -> None:
    """Test delete functionality."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]
    collection.delete_many = MagicMock(return_value=MagicMock(deleted_count=3))

    # Test delete
    assert vector_db.delete() is True


def test_exists(vector_db: MongoVectorDb, mock_mongodb_client: MagicMock) -> None:
    """Test collection existence checking."""
    db = mock_mongodb_client["test_vectordb"]

    # Setup mock responses for collection existence
    db.list_collection_names.return_value = [vector_db.collection_name]

    assert vector_db.exists() is True

    # Test non-existent collection
    db.list_collection_names.return_value = []
    assert vector_db.exists() is False


def test_search_with_filters(
    vector_db: MongoVectorDb, mock_mongodb_client: MagicMock, mock_embedder: MagicMock
) -> None:
    """Test search functionality with filters."""
    collection = mock_mongodb_client["test_vectordb"][vector_db.collection_name]

    # Setup mock response for filtered search
    mock_search_result = [
        {
            "_id": "doc_0",
            "content": "This is test document 0",
            "meta_data": {"type": "test", "index": "0"},
            "name": "test_doc_0",
            "content_id": "content_0",
            "score": 0.95,
        }
    ]
    collection.aggregate.return_value = mock_search_result

    # Test search with filters
    filters = {"meta_data.type": "test"}
    results = vector_db.search("test document", limit=1, filters=filters)

    # Verify results
    assert len(results) == 1
    assert results[0].meta_data["type"] == "test"

    # Verify the search pipeline included filters
    args = collection.aggregate.call_args[0][0]
    assert any("$match" in stage for stage in args)


@pytest.mark.asyncio
async def test_async_client(async_vector_db: MongoVectorDb) -> None:
    """Test that _get_async_client method creates and returns a client."""
    client = await async_vector_db._get_async_client()
    assert client is not None


@pytest.mark.asyncio
async def test_async_get_collection(async_vector_db: MongoVectorDb) -> None:
    """Test getting a collection asynchronously."""
    collection = await async_vector_db._get_async_collection()
    assert collection is not None


@pytest.mark.asyncio
async def test_async_insert(
    async_vector_db: MongoVectorDb, mock_async_mongodb_client: AsyncMock, mock_embedder: MagicMock
) -> None:
    """Test inserting documents asynchronously."""
    docs = create_test_documents(2)

    # Ensure the documents have embeddings
    for doc in docs:
        doc.embedding = mock_embedder.get_embedding(doc.content)

    # Mock the prepare_doc method to avoid embedding issues during test
    original_prepare_doc = async_vector_db.prepare_doc
    async_vector_db.prepare_doc = lambda content_hash, doc, filters=None: {
        "_id": md5(doc.content.encode("utf-8")).hexdigest(),
        "name": doc.name,
        "content": doc.content,
        "meta_data": doc.meta_data,
        "embedding": doc.embedding or [0.1] * 384,
        "content_id": doc.content_id,
        "content_hash": content_hash,
    }

    # Get reference to the mocked collection
    mock_db = mock_async_mongodb_client["test_vectordb"]
    mock_collection = mock_db[async_vector_db.collection_name]

    # Explicitly set the async_collection for the test
    async_vector_db._async_collection = mock_collection

    # Perform the insert
    await async_vector_db.async_insert(content_hash="test_hash", documents=docs)

    # Verify insert_many was called
    mock_collection.insert_many.assert_called_once()

    # Restore original method
    async_vector_db.prepare_doc = original_prepare_doc


@pytest.mark.asyncio
async def test_async_search(
    async_vector_db: MongoVectorDb, mock_async_mongodb_client: AsyncMock, mock_embedder: MagicMock
) -> None:
    """Test searching documents asynchronously."""
    # Get reference to the mocked collection
    mock_db = mock_async_mongodb_client["test_vectordb"]
    mock_collection = mock_db[async_vector_db.collection_name]

    # Explicitly set the async_collection for the test
    async_vector_db._async_collection = mock_collection

    # Create mock results for the cursor
    mock_results = [
        {
            "_id": "doc_0",
            "content": "This is test document 0",
            "meta_data": {"type": "test", "index": "0"},
            "name": "test_doc_0",
            "content_id": "content_0",
            "score": 0.95,
        }
    ]

    # Create and set up a proper async cursor
    mock_cursor = AsyncCursor(mock_results)
    mock_collection.aggregate = AsyncMock(return_value=mock_cursor)

    # Mock embedder.async_get_embedding to ensure it returns consistent results
    mock_embedder.async_get_embedding = AsyncMock(return_value=[0.1] * 384)

    # Perform the search
    results = await async_vector_db.async_search("test query", limit=5)

    # Verify results
    assert len(results) == 1
    assert results[0].content == "This is test document 0"
    assert results[0].id == "doc_0"
    assert results[0].content_id == "content_0"

    # Verify aggregate was called with expected pipeline
    call_args = mock_collection.aggregate.call_args[0][0]
    assert call_args[0]["$vectorSearch"]["limit"] == 5


@pytest.mark.asyncio
async def test_async_exists(async_vector_db: MongoVectorDb, mock_async_mongodb_client: AsyncMock) -> None:
    """Test checking if a collection exists asynchronously."""
    mock_db = mock_async_mongodb_client["test_vectordb"]

    # Test when collection exists
    mock_db.list_collection_names = AsyncMock(return_value=[async_vector_db.collection_name])
    exists = await async_vector_db.async_exists()
    assert exists is True

    # Test when collection doesn't exist
    mock_db.list_collection_names = AsyncMock(return_value=[])
    exists = await async_vector_db.async_exists()
    assert exists is False


@pytest.mark.asyncio
async def test_async_name_exists(async_vector_db: MongoVectorDb, mock_async_mongodb_client: AsyncMock) -> None:
    """Test checking if a document with a given name exists asynchronously."""
    # Get reference to the mocked collection
    mock_db = mock_async_mongodb_client["test_vectordb"]
    mock_collection = mock_db[async_vector_db.collection_name]

    # Explicitly set the async_collection for the test
    async_vector_db._async_collection = mock_collection

    # Setup for existing document
    async def mock_find_one(query):
        if query.get("name") == "test_doc_0":
            return {"_id": "doc_0", "name": "test_doc_0"}
        return None

    mock_collection.find_one = AsyncMock(side_effect=mock_find_one)

    # Test with existing document
    exists = await async_vector_db.async_name_exists("test_doc_0")
    assert exists is True

    # Test with non-existent document
    exists = await async_vector_db.async_name_exists("nonexistent")
    assert exists is False


@pytest.mark.asyncio
async def test_async_upsert(
    async_vector_db: MongoVectorDb, mock_async_mongodb_client: AsyncMock, mock_embedder: MagicMock
) -> None:
    """Test upserting documents asynchronously."""
    doc = create_test_documents(1)[0]

    # Ensure the document has an embedding
    doc.embedding = mock_embedder.get_embedding(doc.content)

    # Mock the prepare_doc method to avoid embedding issues during test
    original_prepare_doc = async_vector_db.prepare_doc
    async_vector_db.prepare_doc = lambda content_hash, doc, filters=None: {
        "_id": md5(doc.content.encode("utf-8")).hexdigest(),
        "name": doc.name,
        "content": doc.content,
        "meta_data": doc.meta_data,
        "embedding": doc.embedding or [0.1] * 384,
        "content_id": doc.content_id,
        "content_hash": content_hash,
    }

    # Get reference to the mocked collection
    mock_db = mock_async_mongodb_client["test_vectordb"]
    mock_collection = mock_db[async_vector_db.collection_name]

    # Explicitly set the async_collection for the test
    async_vector_db._async_collection = mock_collection

    # Perform the upsert
    await async_vector_db.async_upsert(content_hash="test_hash", documents=[doc])

    # Verify update_one was called
    mock_collection.update_one.assert_called_once()

    # Restore original method
    async_vector_db.prepare_doc = original_prepare_doc


@pytest.mark.asyncio
async def test_async_drop(async_vector_db: MongoVectorDb, mock_async_mongodb_client: AsyncMock) -> None:
    """Test dropping a collection asynchronously."""
    # Get reference to the mocked collection
    mock_db = mock_async_mongodb_client["test_vectordb"]
    mock_collection = mock_db[async_vector_db.collection_name]

    # Explicitly set the async_collection for the test
    async_vector_db._async_collection = mock_collection

    # Set up async_exists to return True
    async_vector_db.async_exists = AsyncMock(return_value=True)

    await async_vector_db.async_drop()

    mock_collection.drop.assert_called_once()


@pytest.fixture
def tracking_embedder() -> MagicMock:
    """
    Mock embedder that tracks whether sync or async methods are called.

    This is used to verify that async search methods properly use
    async_get_embedding() instead of blocking get_embedding().
    """
    mock = MagicMock()
    mock.dimensions = 384
    mock_embedding = [0.1] * 384

    # Track call counts
    mock.sync_call_count = 0
    mock.async_call_count = 0

    def sync_get_embedding(text: str):
        mock.sync_call_count += 1
        return mock_embedding

    mock.get_embedding = sync_get_embedding

    async def async_get_embedding(text: str):
        mock.async_call_count += 1
        return mock_embedding

    mock.async_get_embedding = async_get_embedding

    return mock


@pytest.mark.asyncio
async def test_async_search_uses_async_embedder(
    mock_async_mongodb_client: AsyncMock, tracking_embedder: MagicMock
) -> None:
    """
    Verify async_search uses async embedder, not sync.

    This test ensures that async search methods don't block the event loop
    by calling the synchronous get_embedding() method.
    """
    collection_name = f"test_vectors_{uuid.uuid4().hex[:8]}"

    with patch("pymongo.AsyncMongoClient", return_value=mock_async_mongodb_client):
        db = MongoVectorDb(
            collection_name=collection_name,
            embedder=tracking_embedder,
            database="test_vectordb",
        )

        # Setup the DB for async tests
        db._async_client = mock_async_mongodb_client
        db._async_db = mock_async_mongodb_client["test_vectordb"]
        db._async_collection = db._async_db[collection_name]

        # Create mock results for the cursor
        mock_results = [
            {
                "_id": "doc_0",
                "content": "Test content",
                "meta_data": {},
                "name": "test_doc",
                "content_id": "content_0",
                "score": 0.95,
            }
        ]

        # Create and set up a proper async cursor
        mock_cursor = AsyncCursor(mock_results)
        db._async_collection.aggregate = AsyncMock(return_value=mock_cursor)

        # Perform the search
        await db.async_search("test query", limit=5)

        # Verify async embedder was called, not sync
        assert tracking_embedder.async_call_count == 1, "async_get_embedding should be called once"
        assert tracking_embedder.sync_call_count == 0, "sync get_embedding should NOT be called"
