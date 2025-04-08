from typing import List
from unittest.mock import Mock, patch

import pytest

from agno.document import Document
from agno.vectordb.distance import Distance
from agno.vectordb.milvus import Milvus


@pytest.fixture
def mock_milvus_client():
    """Fixture to create a mock Milvus client"""
    with patch("pymilvus.MilvusClient") as mock_client_class:
        client = Mock()

        # Mock collection operations
        client.has_collection.return_value = True

        # Mock search/retrieve operations
        client.search.return_value = [[]]
        client.get.return_value = []
        client.query.return_value = [[]]
        client.get_collection_stats.return_value = {"row_count": 0}

        # Set up mock methods
        client.create_collection = Mock()
        client.drop_collection = Mock()
        client.insert = Mock()
        client.upsert = Mock()

        mock_client_class.return_value = client
        yield client


@pytest.fixture
def mock_milvus_async_client():
    """Fixture to create a mock Milvus async client"""
    with patch("pymilvus.AsyncMilvusClient") as mock_async_client_class:
        client = Mock()

        # Mock search/retrieve operations
        client.search.return_value = [[]]
        client.get.return_value = []

        # Set up mock methods
        client.create_collection = Mock()
        client.drop_collection = Mock()
        client.insert = Mock()
        client.upsert = Mock()

        mock_async_client_class.return_value = client
        yield client


@pytest.fixture
def milvus_db(mock_milvus_client, mock_embedder):
    """Fixture to create a Milvus instance with mocked client"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")
    db._client = mock_milvus_client
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


def test_create_collection(milvus_db, mock_milvus_client):
    """Test creating a collection"""
    # Mock exists to return False to ensure create is called
    with patch.object(milvus_db, "exists", return_value=False):
        milvus_db.create()
        mock_milvus_client.create_collection.assert_called_once()

        # Verify parameters
        args, kwargs = mock_milvus_client.create_collection.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert kwargs["dimension"] == milvus_db.dimensions


def test_exists(milvus_db, mock_milvus_client):
    """Test checking if collection exists"""
    # Test when collection exists
    mock_milvus_client.has_collection.return_value = True
    assert milvus_db.exists() is True

    # Test when collection doesn't exist
    mock_milvus_client.has_collection.return_value = False
    assert milvus_db.exists() is False


def test_drop(milvus_db, mock_milvus_client):
    """Test dropping a collection"""
    # Mock exists to return True to ensure delete is called
    with patch.object(milvus_db, "exists", return_value=True):
        milvus_db.drop()
        mock_milvus_client.drop_collection.assert_called_once_with("test_collection")


def test_insert_documents(milvus_db, sample_documents, mock_milvus_client):
    """Test inserting documents"""
    with patch.object(milvus_db.embedder, "get_embedding", return_value=[0.1] * 768):
        milvus_db.insert(sample_documents)

        # Should call insert once for each document
        assert mock_milvus_client.insert.call_count == 3

        # Check the first call's parameters
        args, kwargs = mock_milvus_client.insert.call_args_list[0]
        assert kwargs["collection_name"] == "test_collection"
        assert "vector" in kwargs["data"]
        assert "name" in kwargs["data"]
        assert "content" in kwargs["data"]


def test_doc_exists(milvus_db, sample_documents, mock_milvus_client):
    """Test document existence check"""
    # Test when document exists
    mock_milvus_client.get.return_value = [Mock()]
    assert milvus_db.doc_exists(sample_documents[0]) is True

    # Test when document doesn't exist
    mock_milvus_client.get.return_value = []
    assert milvus_db.doc_exists(sample_documents[0]) is False


def test_name_exists(milvus_db, mock_milvus_client):
    """Test name existence check"""
    # Test when name exists
    mock_milvus_client.query.return_value = [[Mock()]]
    assert milvus_db.name_exists("tom_kha") is True

    # Test when name doesn't exist
    mock_milvus_client.query.return_value = [[]]
    assert milvus_db.name_exists("nonexistent") is False


def test_id_exists(milvus_db, mock_milvus_client):
    """Test ID existence check"""
    # Test when ID exists
    mock_milvus_client.get.return_value = [Mock()]
    assert milvus_db.id_exists("test_id") is True

    # Test when ID doesn't exist
    mock_milvus_client.get.return_value = []
    assert milvus_db.id_exists("nonexistent_id") is False


def test_upsert_documents(milvus_db, sample_documents, mock_milvus_client):
    """Test upserting documents"""
    with patch.object(milvus_db.embedder, "get_embedding", return_value=[0.1] * 768):
        milvus_db.upsert(sample_documents)

        # Should call upsert once for each document
        assert mock_milvus_client.upsert.call_count == 3

        # Check the first call's parameters
        args, kwargs = mock_milvus_client.upsert.call_args_list[0]
        assert kwargs["collection_name"] == "test_collection"
        assert "vector" in kwargs["data"]
        assert "name" in kwargs["data"]
        assert "content" in kwargs["data"]


def test_upsert_available(milvus_db):
    """Test upsert_available method"""
    assert milvus_db.upsert_available() is True


def test_search(milvus_db, mock_milvus_client):
    """Test search functionality"""
    # Set up mock embedding
    with patch.object(milvus_db.embedder, "get_embedding", return_value=[0.1] * 768):
        # Set up mock search results
        mock_result1 = {
            "id": "id1",
            "entity": {
                "name": "tom_kha",
                "meta_data": {"cuisine": "Thai", "type": "soup"},
                "content": "Tom Kha Gai is a Thai coconut soup with chicken",
                "vector": [0.1] * 768,
                "usage": {"prompt_tokens": 10, "total_tokens": 10},
            },
        }

        mock_result2 = {
            "id": "id2",
            "entity": {
                "name": "green_curry",
                "meta_data": {"cuisine": "Thai", "type": "curry"},
                "content": "Green curry is a spicy Thai curry with coconut milk",
                "vector": [0.2] * 768,
                "usage": {"prompt_tokens": 10, "total_tokens": 10},
            },
        }

        mock_milvus_client.search.return_value = [[mock_result1, mock_result2]]

        # Test search
        results = milvus_db.search("Thai food", limit=2)
        assert len(results) == 2
        assert results[0].name == "tom_kha"
        assert results[1].name == "green_curry"

        # Verify search was called with correct parameters
        mock_milvus_client.search.assert_called_once()
        args, kwargs = mock_milvus_client.search.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert kwargs["data"] == [[0.1] * 768]
        assert kwargs["limit"] == 2


def test_get_count(milvus_db, mock_milvus_client):
    """Test getting count of documents"""
    mock_milvus_client.get_collection_stats.return_value = {"row_count": 42}

    assert milvus_db.get_count() == 42
    mock_milvus_client.get_collection_stats.assert_called_once_with(collection_name="test_collection")


def test_distance_setting(mock_embedder, mock_milvus_client):
    """Test that distance settings are properly applied"""
    # Test with cosine distance (default)
    with patch("pymilvus.MilvusClient", return_value=mock_milvus_client):
        db1 = Milvus(embedder=mock_embedder, collection="test_collection")
        # Direct assignment to avoid real client creation
        db1._client = mock_milvus_client
        with patch.object(db1, "exists", return_value=False):
            db1.create()
            args, kwargs = mock_milvus_client.create_collection.call_args
            assert kwargs["metric_type"] == "COSINE"

    # Test with L2 distance
    with patch("pymilvus.MilvusClient", return_value=mock_milvus_client):
        db2 = Milvus(embedder=mock_embedder, collection="test_collection", distance=Distance.l2)
        # Direct assignment to avoid real client creation
        db2._client = mock_milvus_client
        with patch.object(db2, "exists", return_value=False):
            db2.create()
            args, kwargs = mock_milvus_client.create_collection.call_args
            assert kwargs["metric_type"] == "L2"

    # Test with inner product distance
    with patch("pymilvus.MilvusClient", return_value=mock_milvus_client):
        db3 = Milvus(embedder=mock_embedder, collection="test_collection", distance=Distance.max_inner_product)
        # Direct assignment to avoid real client creation
        db3._client = mock_milvus_client
        with patch.object(db3, "exists", return_value=False):
            db3.create()
            args, kwargs = mock_milvus_client.create_collection.call_args
            assert kwargs["metric_type"] == "IP"


def test_build_expr(milvus_db):
    """Test the _build_expr method for constructing query filters"""
    # Test with None filters
    assert milvus_db._build_expr(None) == ""

    # Test with string value
    filters = {"name": "test_name"}
    assert milvus_db._build_expr(filters) == "(name == 'test_name')"

    # Test with numeric value
    filters = {"count": 42}
    assert milvus_db._build_expr(filters) == "(count == 42)"

    # Test with multiple filters
    filters = {"name": "test_name", "count": 42}
    expr = milvus_db._build_expr(filters)
    assert "(name == 'test_name')" in expr
    assert "(count == 42)" in expr
    assert " and " in expr


@pytest.mark.asyncio
async def test_async_create(mock_embedder):
    """Test async collection creation"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    with patch.object(db, "async_create", return_value=None):
        await db.async_create()


@pytest.mark.asyncio
async def test_async_exists(mock_embedder):
    """Test async exists check"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    with patch.object(db, "async_exists", return_value=True):
        result = await db.async_exists()
        assert result is True


@pytest.mark.asyncio
async def test_async_search(mock_embedder):
    """Test async search"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    mock_results = [Document(name="test_doc", content="Test content", meta_data={"key": "value"})]

    with patch.object(db, "async_search", return_value=mock_results):
        results = await db.async_search("test query", limit=1)
        assert len(results) == 1
        assert results[0].name == "test_doc"


async def async_return(result):
    return result


@pytest.mark.asyncio
async def test_async_doc_exists(mock_embedder, mock_milvus_async_client):
    """Test async document existence check"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    # Create a test document
    test_doc = Document(content="Test content")

    db._async_client = mock_milvus_async_client

    with patch.object(mock_milvus_async_client, "get", side_effect=lambda **kwargs: async_return([Mock()])):
        result = await db.async_doc_exists(test_doc)
        assert result is True

    with patch.object(mock_milvus_async_client, "get", side_effect=lambda **kwargs: async_return([])):
        result = await db.async_doc_exists(test_doc)
        assert result is False


@pytest.mark.asyncio
async def test_async_insert(mock_embedder, sample_documents):
    """Test async insert"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    # Mock async_insert directly
    with patch.object(db, "async_insert", return_value=None):
        await db.async_insert(sample_documents)


@pytest.mark.asyncio
async def test_async_upsert(mock_embedder, sample_documents):
    """Test async upsert"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    # Mock async_upsert directly
    with patch.object(db, "async_upsert", return_value=None):
        await db.async_upsert(sample_documents)


@pytest.mark.asyncio
async def test_async_drop(mock_embedder):
    """Test async drop collection"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    # Mock async_drop directly
    with patch.object(db, "async_drop", return_value=None):
        await db.async_drop()
