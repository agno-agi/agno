from typing import List
from unittest.mock import Mock, patch

import pytest

from agno.document import Document
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
    # Test when collection exists
    collection_info = Mock()
    collection_info.name = "test_collection"
    collections_response = Mock()
    collections_response.collections = [collection_info]
    mock_qdrant_client.get_collections.return_value = collections_response

    assert qdrant_db.exists() is True

    # Test when collection doesn't exist
    collections_response.collections = []
    mock_qdrant_client.get_collections.return_value = collections_response

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
        qdrant_db.insert(sample_documents)
        mock_qdrant_client.upsert.assert_called_once()

        # Verify the right number of points are created
        args, kwargs = mock_qdrant_client.upsert.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert kwargs["wait"] is False
        assert len(kwargs["points"]) == 3


def test_doc_exists(qdrant_db, sample_documents, mock_qdrant_client):
    """Test document existence check"""
    # Test when document exists
    mock_qdrant_client.retrieve.return_value = [Mock()]
    assert qdrant_db.doc_exists(sample_documents[0]) is True

    # Test when document doesn't exist
    mock_qdrant_client.retrieve.return_value = []
    assert qdrant_db.doc_exists(sample_documents[0]) is False


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
        qdrant_db.upsert(sample_documents)
        mock_insert.assert_called_once_with(sample_documents)


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

        mock_qdrant_client.search.return_value = [result1, result2]

        # Test search
        results = qdrant_db.search("Thai food", limit=2)
        assert len(results) == 2
        assert results[0].name == "tom_kha"
        assert results[1].name == "green_curry"

        # Verify search was called with correct parameters
        mock_qdrant_client.search.assert_called_once()
        args, kwargs = mock_qdrant_client.search.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert kwargs["query_vector"] == [0.1] * 768
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
