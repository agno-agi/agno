import asyncio
from typing import List
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.qdrant import Qdrant


@pytest.fixture
def mock_qdrant_client():
    """Fixture to create a mock Qdrant client"""
    with patch("qdrant_client.QdrantClient") as mock_client_class:
        client = Mock()

        # Mock collection operations
        collection_info = Mock()
        collection_info.status = "green"
        collection_info.name = "test_collection"

        collections_response = Mock()
        collections_response.collections = [collection_info]
        client.get_collections.return_value = collections_response

        # Mock search/retrieve operations
        client.search.return_value = []
        client.retrieve.return_value = []
        client.scroll.return_value = ([], None)
        client.count.return_value = Mock(count=0)

        # Set up mock methods
        client.create_collection = Mock()
        client.delete_collection = Mock()
        client.upsert = Mock()
        client.delete = Mock()

        mock_client_class.return_value = client
        yield client


@pytest.fixture
def mock_qdrant_async_client():
    """Fixture to create a mock Qdrant async client"""
    with patch("qdrant_client.AsyncQdrantClient") as mock_async_client_class:
        client = Mock()

        # Mock collection operations
        collection_info = Mock()
        collection_info.status = "green"
        collection_info.name = "test_collection"

        collections_response = Mock()
        collections_response.collections = [collection_info]
        client.get_collections.return_value = collections_response

        # Mock search/retrieve operations
        client.search.return_value = []
        client.retrieve.return_value = []

        # Set up mock methods
        client.create_collection = Mock()
        client.delete_collection = Mock()
        client.upsert = Mock()
        client.delete = Mock()

        mock_async_client_class.return_value = client
        yield client


@pytest.fixture
def qdrant_db(mock_qdrant_client, mock_embedder):
    """Fixture to create a Qdrant instance with mocked client"""
    db = Qdrant(embedder=mock_embedder, collection="test_collection")
    db._client = mock_qdrant_client
    yield db


@pytest.fixture
def sample_documents() -> List[Document]:
    """Fixture to create sample documents"""
    return [
        Document(
            content="Tom Kha Gai is a Thai coconut soup with chicken",
            meta_data={"cuisine": "Thai", "type": "soup"},
            name="tom_kha",
        ),
        Document(
            content="Pad Thai is a stir-fried rice noodle dish",
            meta_data={"cuisine": "Thai", "type": "noodles"},
            name="pad_thai",
        ),
        Document(
            content="Green curry is a spicy Thai curry with coconut milk",
            meta_data={"cuisine": "Thai", "type": "curry"},
            name="green_curry",
        ),
    ]


def test_create_collection(qdrant_db, mock_qdrant_client):
    """Test creating a collection"""
    # Mock exists to return False to ensure create is called
    with patch.object(qdrant_db, "exists", return_value=False):
        qdrant_db.create()
        mock_qdrant_client.create_collection.assert_called_once()


def test_exists(qdrant_db, mock_qdrant_client):
    """Test checking if collection exists"""
    mock_qdrant_client.collection_exists.return_value = True
    assert qdrant_db.exists() is True

    mock_qdrant_client.collection_exists.return_value = False
    assert qdrant_db.exists() is False


def test_drop(qdrant_db, mock_qdrant_client):
    """Test dropping a collection"""
    # Mock exists to return True to ensure delete is called
    with patch.object(qdrant_db, "exists", return_value=True):
        qdrant_db.drop()
        mock_qdrant_client.delete_collection.assert_called_once_with("test_collection")


def test_insert_documents(qdrant_db, sample_documents, mock_qdrant_client):
    """Test inserting documents"""
    with patch.object(qdrant_db.embedder, "get_embedding", return_value=[0.1] * 768):
        qdrant_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_qdrant_client.upsert.assert_called_once()

        # Verify the right number of points are created
        args, kwargs = mock_qdrant_client.upsert.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert kwargs["wait"] is False
        assert len(kwargs["points"]) == 3


def test_name_exists(qdrant_db, mock_qdrant_client):
    """Test name existence check"""
    # Test when name exists
    mock_qdrant_client.scroll.return_value = ([Mock()], None)
    assert qdrant_db.name_exists("tom_kha") is True

    # Test when name doesn't exist
    mock_qdrant_client.scroll.return_value = ([], None)
    assert qdrant_db.name_exists("nonexistent") is False


def test_upsert_documents(qdrant_db, sample_documents, mock_qdrant_client):
    """Test upserting documents"""
    # Since upsert calls insert, just ensure insert is called
    with patch.object(qdrant_db, "insert") as mock_insert:
        qdrant_db.upsert(documents=sample_documents, content_hash="test_hash")
        mock_insert.assert_called_once()


def test_search(qdrant_db, mock_qdrant_client):
    """Test search functionality"""
    # Set up mock embedding
    with patch.object(qdrant_db.embedder, "get_embedding", return_value=[0.1] * 768):
        # Set up mock search results
        result1 = Mock()
        result1.payload = {
            "name": "tom_kha",
            "meta_data": {"cuisine": "Thai", "type": "soup"},
            "content": "Tom Kha Gai is a Thai coconut soup with chicken",
            "usage": {"prompt_tokens": 10, "total_tokens": 10},
        }
        result1.vector = [0.1] * 768

        result2 = Mock()
        result2.payload = {
            "name": "green_curry",
            "meta_data": {"cuisine": "Thai", "type": "curry"},
            "content": "Green curry is a spicy Thai curry with coconut milk",
            "usage": {"prompt_tokens": 10, "total_tokens": 10},
        }
        result2.vector = [0.2] * 768

        query_response = Mock()
        query_response.points = [result1, result2]
        mock_qdrant_client.query_points.return_value = query_response

        # Test search
        results = qdrant_db.search("Thai food", limit=2)
        assert len(results) == 2
        assert results[0].name == "tom_kha"
        assert results[1].name == "green_curry"

        # Verify search was called with correct parameters
        mock_qdrant_client.query_points.assert_called_once()
        args, kwargs = mock_qdrant_client.query_points.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert kwargs["query"] == [0.1] * 768
        assert kwargs["limit"] == 2


def test_get_count(qdrant_db, mock_qdrant_client):
    """Test getting count of documents"""
    count_result = Mock()
    count_result.count = 42
    mock_qdrant_client.count.return_value = count_result

    assert qdrant_db.get_count() == 42
    mock_qdrant_client.count.assert_called_once_with(collection_name="test_collection", exact=True)


@pytest.mark.asyncio
async def test_async_create(mock_embedder):
    """Test async collection creation"""
    db = Qdrant(embedder=mock_embedder, collection="test_collection")

    with patch.object(db, "async_create", return_value=None):
        await db.async_create()


@pytest.mark.asyncio
async def test_async_exists(mock_embedder):
    """Test async exists check"""
    db = Qdrant(embedder=mock_embedder, collection="test_collection")

    # Mock the async_exists method directly
    with patch.object(db, "async_exists", return_value=True):
        result = await db.async_exists()
        assert result is True


@pytest.mark.asyncio
async def test_async_search(mock_embedder):
    """Test async search"""
    db = Qdrant(embedder=mock_embedder, collection="test_collection")

    mock_results = [Document(name="test_doc", content="Test content", meta_data={"key": "value"})]

    with patch.object(db, "async_search", return_value=mock_results):
        results = await db.async_search("test query", limit=1)
        assert len(results) == 1
        assert results[0].name == "test_doc"


def test_delete_by_id(qdrant_db, sample_documents, mock_qdrant_client):
    """Test deleting documents by ID"""
    # Mock insert and get_count
    with patch.object(qdrant_db, "insert"), patch.object(qdrant_db, "get_count") as mock_get_count:
        qdrant_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_id method
    with patch.object(qdrant_db, "delete_by_id") as mock_delete_by_id:
        mock_delete_by_id.return_value = True

        # Get the actual ID that would be generated for the first document
        from hashlib import md5

        cleaned_content = sample_documents[0].content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode()).hexdigest()

        # Test delete by ID
        result = qdrant_db.delete_by_id(doc_id)
        assert result is True
        mock_delete_by_id.assert_called_once_with(doc_id)

        # Test delete non-existent ID
        mock_delete_by_id.reset_mock()
        mock_delete_by_id.return_value = True
        result = qdrant_db.delete_by_id("nonexistent_id")
        assert result is True


def test_delete_by_name(qdrant_db, sample_documents, mock_qdrant_client):
    """Test deleting documents by name"""
    # Mock insert and get_count
    with patch.object(qdrant_db, "insert"), patch.object(qdrant_db, "get_count") as mock_get_count:
        qdrant_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_name method
    with patch.object(qdrant_db, "delete_by_name") as mock_delete_by_name:
        mock_delete_by_name.return_value = True
        # Test delete by name
        result = qdrant_db.delete_by_name("tom_kha")
        assert result is True
        mock_delete_by_name.assert_called_once_with("tom_kha")

        # Test delete non-existent name
        mock_delete_by_name.reset_mock()
        mock_delete_by_name.return_value = False
        result = qdrant_db.delete_by_name("nonexistent")
        assert result is False


def test_delete_by_metadata(qdrant_db, sample_documents, mock_qdrant_client):
    """Test deleting documents by metadata"""
    # Mock insert and get_count
    with patch.object(qdrant_db, "insert"), patch.object(qdrant_db, "get_count") as mock_get_count:
        qdrant_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_metadata method
    with patch.object(qdrant_db, "delete_by_metadata") as mock_delete_by_metadata:
        # Test delete all Thai cuisine documents
        mock_delete_by_metadata.return_value = True
        result = qdrant_db.delete_by_metadata({"cuisine": "Thai"})
        assert result is True
        mock_delete_by_metadata.assert_called_once_with({"cuisine": "Thai"})

        # Test delete by specific metadata combination
        mock_delete_by_metadata.reset_mock()
        mock_delete_by_metadata.return_value = True
        result = qdrant_db.delete_by_metadata({"cuisine": "Thai", "type": "soup"})
        assert result is True
        mock_delete_by_metadata.assert_called_once_with({"cuisine": "Thai", "type": "soup"})

        # Test delete by non-existent metadata
        mock_delete_by_metadata.reset_mock()
        mock_delete_by_metadata.return_value = False
        result = qdrant_db.delete_by_metadata({"cuisine": "Italian"})
        assert result is False


def test_delete_by_content_id(qdrant_db, sample_documents, mock_qdrant_client):
    """Test deleting documents by content ID"""
    # Add content_id to sample documents
    sample_documents[0].content_id = "recipe_1"
    sample_documents[1].content_id = "recipe_2"
    sample_documents[2].content_id = "recipe_3"

    # Mock insert and get_count
    with patch.object(qdrant_db, "insert"), patch.object(qdrant_db, "get_count") as mock_get_count:
        qdrant_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_content_id method
    with patch.object(qdrant_db, "delete_by_content_id") as mock_delete_by_content_id:
        # Test delete by content_id
        mock_delete_by_content_id.return_value = True
        result = qdrant_db.delete_by_content_id("recipe_1")
        assert result is True
        mock_delete_by_content_id.assert_called_once_with("recipe_1")

        # Test delete non-existent content_id
        mock_delete_by_content_id.reset_mock()
        mock_delete_by_content_id.return_value = False
        result = qdrant_db.delete_by_content_id("nonexistent_content_id")
        assert result is False


def test_delete_by_name_multiple_documents(qdrant_db, mock_qdrant_client):
    """Test deleting multiple documents with the same name"""
    # Create multiple documents with the same name
    docs = [
        Document(
            content="First version of Tom Kha Gai",
            meta_data={"version": "1"},
            name="tom_kha",
            content_id="recipe_1_v1",
        ),
        Document(
            content="Second version of Tom Kha Gai",
            meta_data={"version": "2"},
            name="tom_kha",
            content_id="recipe_1_v2",
        ),
        Document(
            content="Pad Thai recipe",
            meta_data={"version": "1"},
            name="pad_thai",
            content_id="recipe_2_v1",
        ),
    ]

    # Mock insert and get_count
    with patch.object(qdrant_db, "insert"), patch.object(qdrant_db, "get_count") as mock_get_count:
        qdrant_db.insert(documents=docs, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_name and name_exists methods
    with (
        patch.object(qdrant_db, "delete_by_name") as mock_delete_by_name,
        patch.object(qdrant_db, "name_exists") as mock_name_exists,
    ):
        mock_delete_by_name.return_value = True
        mock_name_exists.side_effect = [False, True]  # tom_kha doesn't exist, pad_thai exists
        # Test delete all documents with name "tom_kha"
        result = qdrant_db.delete_by_name("tom_kha")
        assert result is True
        mock_delete_by_name.assert_called_once_with("tom_kha")
        # Verify name_exists behavior
        assert qdrant_db.name_exists("tom_kha") is False
        assert qdrant_db.name_exists("pad_thai") is True


def test_delete_by_metadata_complex(qdrant_db, mock_qdrant_client):
    """Test deleting documents with complex metadata matching"""
    docs = [
        Document(
            content="Thai soup recipe",
            meta_data={"cuisine": "Thai", "type": "soup", "spicy": True},
            name="recipe_1",
        ),
        Document(
            content="Thai noodle recipe",
            meta_data={"cuisine": "Thai", "type": "noodles", "spicy": False},
            name="recipe_2",
        ),
        Document(
            content="Italian pasta recipe",
            meta_data={"cuisine": "Italian", "type": "pasta", "spicy": False},
            name="recipe_3",
        ),
    ]

    # Mock insert and get_count
    with patch.object(qdrant_db, "insert"), patch.object(qdrant_db, "get_count") as mock_get_count:
        qdrant_db.insert(documents=docs, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_metadata method
    with patch.object(qdrant_db, "delete_by_metadata") as mock_delete_by_metadata:
        # Test delete only spicy Thai dishes
        mock_delete_by_metadata.return_value = True
        result = qdrant_db.delete_by_metadata({"cuisine": "Thai", "spicy": True})
        assert result is True
        mock_delete_by_metadata.assert_called_once_with({"cuisine": "Thai", "spicy": True})

        # Test delete all non-spicy dishes
        mock_delete_by_metadata.reset_mock()
        mock_delete_by_metadata.return_value = True
        result = qdrant_db.delete_by_metadata({"spicy": False})
        assert result is True
        mock_delete_by_metadata.assert_called_once_with({"spicy": False})


@pytest.fixture
def tracking_embedder():
    """
    Mock embedder that tracks whether sync or async methods are called.

    This is used to verify that async search methods properly use
    async_get_embedding() instead of blocking get_embedding().
    """
    mock = Mock()
    mock.dimensions = 1024
    mock_embedding = [0.1] * 1024

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
async def test_async_search_uses_async_embedder(tracking_embedder):
    """
    Verify async_search uses async embedder, not sync.
    """
    db = Qdrant(embedder=tracking_embedder, collection="test_collection")

    # Mock the async client
    mock_async_client = AsyncMock()
    query_response = Mock()
    query_response.points = []
    mock_async_client.query_points.return_value = query_response
    db._async_client = mock_async_client

    # Call the internal async vector search method
    await db._run_vector_search_async("test query", limit=5, formatted_filters=None)

    # Verify async embedder was called, not sync
    assert tracking_embedder.async_call_count == 1, "async_get_embedding should be called once"
    assert tracking_embedder.sync_call_count == 0, "sync get_embedding should NOT be called"


@pytest.mark.asyncio
async def test_async_hybrid_search_uses_async_embedder(tracking_embedder):
    """
    Verify async hybrid search uses async embedder, not sync.
    """
    db = Qdrant(embedder=tracking_embedder, collection="test_collection")

    # Mock the sparse encoder
    mock_sparse_embedding = Mock()
    mock_sparse_embedding.as_object.return_value = {"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}
    mock_sparse_encoder = Mock()
    mock_sparse_encoder.embed.return_value = iter([mock_sparse_embedding])
    db.sparse_encoder = mock_sparse_encoder
    db.sparse_vector_name = "sparse"
    db.dense_vector_name = "dense"

    # Mock the async client
    mock_async_client = AsyncMock()
    query_response = Mock()
    query_response.points = []
    mock_async_client.query_points.return_value = query_response
    db._async_client = mock_async_client

    # Call the internal async hybrid search method
    await db._run_hybrid_search_async("test query", limit=5, formatted_filters=None)

    # Verify async embedder was called, not sync
    assert tracking_embedder.async_call_count == 1, "async_get_embedding should be called once"
    assert tracking_embedder.sync_call_count == 0, "sync get_embedding should NOT be called"


@pytest.mark.asyncio
async def test_concurrent_async_searches_no_blocking(tracking_embedder):
    """
    Verify concurrent async searches don't block each other.

    When multiple async searches run concurrently, they should all use
    async embedder and not serialize due to blocking sync calls.
    """
    db = Qdrant(embedder=tracking_embedder, collection="test_collection")

    # Mock the async client
    mock_async_client = AsyncMock()
    query_response = Mock()
    query_response.points = []
    mock_async_client.query_points.return_value = query_response
    db._async_client = mock_async_client

    # Run multiple concurrent searches
    tasks = [db._run_vector_search_async(f"query {i}", limit=5, formatted_filters=None) for i in range(5)]
    await asyncio.gather(*tasks)

    # All should use async embedder
    assert tracking_embedder.async_call_count == 5, "async_get_embedding should be called 5 times"
    assert tracking_embedder.sync_call_count == 0, "sync get_embedding should NOT be called"
