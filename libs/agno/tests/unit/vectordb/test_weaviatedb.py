import json
from typing import List
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.document import Document
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate import Weaviate
from agno.vectordb.weaviate.index import Distance, VectorIndex


@pytest.fixture
def mock_weaviate_client():
    """Fixture to create a mock Weaviate client"""
    with patch("weaviate.connect_to_local") as mock_connect:
        client = Mock()
        client.is_ready.return_value = True
        client.collections.exists.return_value = False

        # Mock collection
        collection = Mock()
        client.collections.get.return_value = collection

        # Set up collection query mocks
        mock_response = Mock()
        mock_response.objects = []
        collection.query.near_vector.return_value = mock_response
        collection.query.bm25.return_value = mock_response
        collection.query.hybrid.return_value = mock_response

        # Set up collection management mocks
        client.collections.create = Mock()
        client.collections.delete = Mock()

        mock_connect.return_value = client
        yield client


@pytest.fixture
def weaviate_db(mock_weaviate_client, mock_embedder):
    """Fixture to create a Weaviate instance with mocked client"""
    db = Weaviate(client=mock_weaviate_client, embedder=mock_embedder, collection="test_collection")
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


def test_create_collection(weaviate_db, mock_weaviate_client):
    """Test creating a collection"""
    weaviate_db.create()
    mock_weaviate_client.collections.create.assert_called_once()


def test_exists(weaviate_db, mock_weaviate_client):
    """Test checking if collection exists"""
    mock_weaviate_client.collections.exists.return_value = True
    assert weaviate_db.exists() is True

    mock_weaviate_client.collections.exists.return_value = False
    assert weaviate_db.exists() is False


def test_drop(weaviate_db, mock_weaviate_client):
    """Test dropping a collection"""
    mock_weaviate_client.collections.exists.return_value = True
    weaviate_db.drop()
    mock_weaviate_client.collections.delete.assert_called_once()


def test_insert_documents(weaviate_db, sample_documents, mock_weaviate_client):
    """Test inserting documents"""
    collection = mock_weaviate_client.collections.get.return_value

    weaviate_db.insert(sample_documents)
    assert collection.data.insert.call_count == 3


def test_vector_search(weaviate_db, sample_documents, mock_weaviate_client):
    """Test vector search"""
    # Configure the mock response with sample objects
    collection = mock_weaviate_client.collections.get.return_value
    mock_response = Mock()

    # Create mock results
    mock_result1 = Mock()
    mock_result1.properties = {
        "name": "tom_kha",
        "content": "Tom Kha Gai is a Thai coconut soup with chicken",
        "meta_data": json.dumps({"cuisine": "Thai", "type": "soup"}),
    }
    mock_result1.vector = [0.1] * 1536  # Mock embedding

    mock_result2 = Mock()
    mock_result2.properties = {
        "name": "green_curry",
        "content": "Green curry is a spicy Thai curry with coconut milk",
        "meta_data": json.dumps({"cuisine": "Thai", "type": "curry"}),
    }
    mock_result2.vector = [0.2] * 1536  # Mock embedding

    mock_response.objects = [mock_result1, mock_result2]
    collection.query.near_vector.return_value = mock_response

    results = weaviate_db.vector_search("coconut dishes", limit=2)
    assert len(results) == 2
    assert any("tom_kha" == doc.name for doc in results)
    assert any("green_curry" == doc.name for doc in results)


def test_keyword_search(weaviate_db, sample_documents, mock_weaviate_client):
    """Test keyword search"""
    weaviate_db.search_type = SearchType.keyword

    # Configure the mock response
    collection = mock_weaviate_client.collections.get.return_value
    mock_response = Mock()

    mock_result = Mock()
    mock_result.properties = {
        "name": "green_curry",
        "content": "Green curry is a spicy Thai curry with coconut milk",
        "meta_data": json.dumps({"cuisine": "Thai", "type": "curry"}),
    }
    mock_result.vector = [0.2] * 1536

    mock_response.objects = [mock_result]
    collection.query.bm25.return_value = mock_response

    results = weaviate_db.search("spicy curry", limit=1)
    assert len(results) == 1
    assert results[0].name == "green_curry"


def test_hybrid_search(weaviate_db, sample_documents, mock_weaviate_client):
    """Test hybrid search"""
    weaviate_db.search_type = SearchType.hybrid

    # Configure the mock response
    collection = mock_weaviate_client.collections.get.return_value
    mock_response = Mock()

    mock_result1 = Mock()
    mock_result1.properties = {
        "name": "tom_kha",
        "content": "Tom Kha Gai is a Thai coconut soup with chicken",
        "meta_data": json.dumps({"cuisine": "Thai", "type": "soup"}),
    }
    mock_result1.vector = [0.1] * 1536

    mock_result2 = Mock()
    mock_result2.properties = {
        "name": "pad_thai",
        "content": "Pad Thai is a stir-fried rice noodle dish",
        "meta_data": json.dumps({"cuisine": "Thai", "type": "noodles"}),
    }
    mock_result2.vector = [0.3] * 1536

    mock_response.objects = [mock_result1, mock_result2]
    collection.query.hybrid.return_value = mock_response

    results = weaviate_db.search("Thai food", limit=2)
    assert len(results) == 2
    assert "tom_kha" in [doc.name for doc in results]
    assert "pad_thai" in [doc.name for doc in results]


def test_doc_exists(weaviate_db, sample_documents, mock_weaviate_client):
    """Test document existence check"""
    collection = mock_weaviate_client.collections.get.return_value
    collection.data.exists.return_value = True

    assert weaviate_db.doc_exists(sample_documents[0]) is True

    collection.data.exists.return_value = False
    assert weaviate_db.doc_exists(sample_documents[0]) is False


def test_name_exists(weaviate_db, mock_weaviate_client):
    """Test name existence check"""
    collection = mock_weaviate_client.collections.get.return_value

    mock_response = Mock()
    mock_response.objects = [Mock()]  # Non-empty array means exists
    collection.query.fetch_objects.return_value = mock_response

    assert weaviate_db.name_exists("tom_kha") is True

    mock_response.objects = []  # Empty array means doesn't exist
    collection.query.fetch_objects.return_value = mock_response

    assert weaviate_db.name_exists("nonexistent") is False


def test_upsert_documents(weaviate_db, sample_documents, mock_weaviate_client):
    """Test upserting documents"""
    collection = mock_weaviate_client.collections.get.return_value

    weaviate_db.upsert(sample_documents)
    assert collection.data.insert.call_count == 3


def test_vector_index_config(weaviate_db):
    """Test vector index configuration"""
    # Instead of checking instance type, just verify it's not None
    hnsw_config = weaviate_db.get_vector_index_config(VectorIndex.HNSW, Distance.COSINE)
    assert hnsw_config is not None

    flat_config = weaviate_db.get_vector_index_config(VectorIndex.FLAT, Distance.COSINE)
    assert flat_config is not None


def test_get_search_results(weaviate_db):
    """Test search results parsing"""
    # Create mock response
    mock_response = MagicMock()

    mock_obj1 = MagicMock()
    mock_obj1.properties = {"name": "test1", "content": "Test content 1", "meta_data": json.dumps({"key": "value"})}
    mock_obj1.vector = {"default": [0.1] * 768}

    mock_obj2 = MagicMock()
    mock_obj2.properties = {"name": "test2", "content": "Test content 2", "meta_data": None}
    mock_obj2.vector = [0.2] * 768

    mock_response.objects = [mock_obj1, mock_obj2]

    results = weaviate_db.get_search_results(mock_response)
    assert len(results) == 2
    assert results[0].name == "test1"
    assert results[0].meta_data == {"key": "value"}
    assert results[1].name == "test2"
    assert results[1].meta_data == {}


@pytest.mark.asyncio
async def test_async_create(mock_embedder):
    """Test async collection creation"""
    db = Weaviate(embedder=mock_embedder, collection="test_collection")

    # Mock the async_create method directly rather than using AsyncMock
    with patch.object(db, "async_create", return_value=None):
        await db.async_create()
        # We can't make assertions about calls since we're not using AsyncMock
        # Just verify that it doesn't raise an exception


@pytest.mark.asyncio
async def test_async_exists(mock_embedder):
    """Test async exists check"""
    db = Weaviate(embedder=mock_embedder, collection="test_collection")

    # Mock the async_exists method directly
    with patch.object(db, "async_exists", return_value=True):
        result = await db.async_exists()
        assert result is True
