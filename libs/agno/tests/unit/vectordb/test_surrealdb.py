from typing import List
from unittest.mock import Mock, patch

import pytest

from agno.document import Document
from agno.vectordb.distance import Distance
from agno.vectordb.surrealdb import SurrealVectorDb


@pytest.fixture
def mock_surrealdb_client():
    """Fixture to create a mock SurrealDB client"""
    with patch("surrealdb.SurrealDB") as mock_client_class:
        client = Mock()

        # Mock methods
        client.connect = Mock()
        client.sign_in = Mock()
        client.use = Mock()
        client.close = Mock()
        client.query = Mock()
        client.create = Mock()

        # Mock query responses
        client.query.return_value = [{"result": []}]

        mock_client_class.return_value = client
        yield client


@pytest.fixture
def mock_async_surrealdb_client():
    """Fixture to create a mock AsyncSurrealDB client"""
    with patch("surrealdb.AsyncSurrealDB") as mock_async_client_class:
        client = Mock()

        # Mock methods
        client.connect = Mock(return_value=None)
        client.sign_in = Mock(return_value=None)
        client.use = Mock(return_value=None)
        client.close = Mock(return_value=None)
        client.query = Mock(return_value=[{"result": []}])
        client.create = Mock(return_value=None)

        mock_async_client_class.return_value = client
        yield client


@pytest.fixture
def surrealdb_vector(mock_surrealdb_client, mock_embedder):
    """Fixture to create a SurrealVectorDb instance with mocked client"""
    db = SurrealVectorDb(
        url="ws://localhost:8000/rpc",
        namespace="test",
        database="test",
        username="root",
        password="root",
        collection="test_collection",
        embedder=mock_embedder,
    )
    return db


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


def test_init_params(mock_embedder):
    """Test initialization parameters"""
    db = SurrealVectorDb(
        url="ws://localhost:8000/rpc",
        namespace="test",
        database="test",
        username="root",
        password="root",
        collection="custom_collection",
        distance=Distance.cosine,
        efc=200,
        m=16,
        search_ef=60,
        embedder=mock_embedder,
    )

    assert db.url == "ws://localhost:8000/rpc"
    assert db.namespace == "test"
    assert db.database == "test"
    assert db.username == "root"
    assert db.password == "root"
    assert db.collection == "custom_collection"
    assert db.distance == "COSINE"
    assert db.efc == 200
    assert db.m == 16
    assert db.search_ef == 60
    assert db.embedder == mock_embedder
    assert db.dimensions == mock_embedder.dimensions


def test_connect_context_manager(surrealdb_vector, mock_surrealdb_client):
    """Test connect context manager"""
    with surrealdb_vector.connect():
        pass

    mock_surrealdb_client.connect.assert_called_once()
    mock_surrealdb_client.sign_in.assert_called_once_with(surrealdb_vector.username, surrealdb_vector.password)
    mock_surrealdb_client.use.assert_called_once_with(surrealdb_vector.namespace, surrealdb_vector.database)
    mock_surrealdb_client.close.assert_called_once()


def test_build_filter_condition(surrealdb_vector):
    """Test filter condition builder"""
    # Test with no filters
    result = surrealdb_vector._build_filter_condition(None)
    assert result == ""

    # Test with filters
    filters = {"cuisine": "Thai", "type": "soup"}
    result = surrealdb_vector._build_filter_condition(filters)
    assert "AND meta_data.cuisine = $cuisine" in result
    assert "AND meta_data.type = $type" in result


def test_create(surrealdb_vector, mock_surrealdb_client):
    """Test create collection"""
    # Mock exists to return False
    with patch.object(surrealdb_vector, "exists", return_value=False):
        surrealdb_vector.create()

        # Verify query was called with correct parameters
        mock_surrealdb_client.query.assert_called_once()
        args = mock_surrealdb_client.query.call_args[0][0]
        assert "DEFINE TABLE IF NOT EXISTS test_collection" in args
        assert "DEFINE INDEX IF NOT EXISTS vector_idx" in args
        assert f"DIMENSION {surrealdb_vector.dimensions}" in args


def test_exists(surrealdb_vector, mock_surrealdb_client):
    """Test exists method"""
    # Test when collection exists
    mock_surrealdb_client.query.return_value = [{"result": {"tables": {"test_collection": {}}}}]

    assert surrealdb_vector.exists() is True

    # Test when collection doesn't exist
    mock_surrealdb_client.query.return_value = [{"result": {"tables": {}}}]

    assert surrealdb_vector.exists() is False


def test_doc_exists(surrealdb_vector, mock_surrealdb_client, sample_documents):
    """Test document existence check"""
    # Test when document exists
    mock_surrealdb_client.query.return_value = [{"result": [{"content": sample_documents[0].content}]}]

    assert surrealdb_vector.doc_exists(sample_documents[0]) is True

    # Test when document doesn't exist
    mock_surrealdb_client.query.return_value = [{"result": []}]

    assert surrealdb_vector.doc_exists(sample_documents[0]) is False


def test_name_exists(surrealdb_vector, mock_surrealdb_client):
    """Test name existence check"""
    # Test when name exists
    mock_surrealdb_client.query.return_value = [{"result": [{"name": "tom_kha"}]}]

    assert surrealdb_vector.name_exists("tom_kha") is True

    # Test when name doesn't exist
    mock_surrealdb_client.query.return_value = [{"result": []}]

    assert surrealdb_vector.name_exists("nonexistent") is False


def test_insert(surrealdb_vector, mock_surrealdb_client, sample_documents):
    """Test inserting documents"""
    with patch.object(surrealdb_vector.embedder, "get_embedding", return_value=[0.1] * 1024):
        surrealdb_vector.insert(sample_documents)

        # Verify create was called for each document
        assert mock_surrealdb_client.create.call_count == 3

        # Check args for first document
        args, kwargs = mock_surrealdb_client.create.call_args_list[0]
        assert args[0] == "test_collection"
        assert "content" in args[1]
        assert "embedding" in args[1]
        assert "meta_data" in args[1]


def test_upsert(surrealdb_vector, mock_surrealdb_client, sample_documents):
    """Test upserting documents"""
    with patch.object(surrealdb_vector.embedder, "get_embedding", return_value=[0.1] * 1024):
        surrealdb_vector.upsert(sample_documents)

        # Verify query was called for each document
        assert mock_surrealdb_client.query.call_count == 3

        # Check args for first call
        args, kwargs = mock_surrealdb_client.query.call_args_list[0]
        assert "INSERT INTO test_collection" in args[0]
        assert "ON DUPLICATE KEY UPDATE" in args[0]
        assert "content" in args[1]
        assert "embedding" in args[1]
        assert "meta_data" in args[1]


def test_search(surrealdb_vector, mock_surrealdb_client):
    """Test search functionality"""
    # Set up mock embedding
    with patch.object(surrealdb_vector.embedder, "get_embedding", return_value=[0.1] * 1024):
        # Set up mock search results
        mock_surrealdb_client.query.return_value = [
            {
                "result": [
                    {
                        "content": "Tom Kha Gai is a Thai coconut soup with chicken",
                        "meta_data": {"cuisine": "Thai", "type": "soup", "name": "tom_kha"},
                        "distance": 0.1,
                    },
                    {
                        "content": "Green curry is a spicy Thai curry with coconut milk",
                        "meta_data": {"cuisine": "Thai", "type": "curry", "name": "green_curry"},
                        "distance": 0.2,
                    },
                ]
            }
        ]

        # Test search
        results = surrealdb_vector.search("Thai food", limit=2)
        assert len(results) == 2
        assert results[0].content == "Tom Kha Gai is a Thai coconut soup with chicken"
        assert results[1].content == "Green curry is a spicy Thai curry with coconut milk"

        # Verify search query
        mock_surrealdb_client.query.assert_called_once()
        args, kwargs = mock_surrealdb_client.query.call_args
        assert "SELECT" in args[0]
        assert "FROM test_collection" in args[0]
        assert "WHERE embedding <|2," in args[0]
        assert "LIMIT 2" in args[0]


def test_drop(surrealdb_vector, mock_surrealdb_client):
    """Test dropping a collection"""
    surrealdb_vector.drop()

    # Verify query was called
    mock_surrealdb_client.query.assert_called_once()
    args = mock_surrealdb_client.query.call_args[0][0]
    assert "REMOVE TABLE test_collection" in args


def test_delete(surrealdb_vector, mock_surrealdb_client):
    """Test deleting all documents"""
    result = surrealdb_vector.delete()

    # Verify query was called and result is True
    mock_surrealdb_client.query.assert_called_once()
    args = mock_surrealdb_client.query.call_args[0][0]
    assert "DELETE test_collection" in args
    assert result is True


def test_extract_result(surrealdb_vector):
    """Test extract result method"""
    query_result = [{"result": [{"id": 1}, {"id": 2}]}]
    result = surrealdb_vector._extract_result(query_result)
    assert result == [{"id": 1}, {"id": 2}]


def test_upsert_available(surrealdb_vector):
    """Test upsert_available method"""
    assert surrealdb_vector.upsert_available() is True


@pytest.mark.asyncio
async def test_async_connect_context_manager(surrealdb_vector, mock_async_surrealdb_client):
    """Test async connect context manager"""
    async with surrealdb_vector.async_connect():
        pass

    mock_async_surrealdb_client.connect.assert_awaited_once()
    mock_async_surrealdb_client.sign_in.assert_awaited_once_with(surrealdb_vector.username, surrealdb_vector.password)
    mock_async_surrealdb_client.use.assert_awaited_once_with(surrealdb_vector.namespace, surrealdb_vector.database)
    mock_async_surrealdb_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_create(surrealdb_vector, mock_async_surrealdb_client):
    """Test async create collection"""
    await surrealdb_vector.async_create()

    # Verify query was called
    mock_async_surrealdb_client.query.assert_awaited_once()
    args = mock_async_surrealdb_client.query.await_args[0][0]
    assert "DEFINE TABLE IF NOT EXISTS test_collection" in args
    assert "DEFINE INDEX IF NOT EXISTS vector_idx" in args
    assert f"DIMENSION {surrealdb_vector.dimensions}" in args


@pytest.mark.asyncio
async def test_async_doc_exists(surrealdb_vector, mock_async_surrealdb_client, sample_documents):
    """Test async document existence check"""
    # Test when document exists
    mock_async_surrealdb_client.query.return_value = [{"result": [{"content": sample_documents[0].content}]}]

    result = await surrealdb_vector.async_doc_exists(sample_documents[0])
    assert result is True

    # Test when document doesn't exist
    mock_async_surrealdb_client.query.return_value = [{"result": []}]

    result = await surrealdb_vector.async_doc_exists(sample_documents[0])
    assert result is False


@pytest.mark.asyncio
async def test_async_name_exists(surrealdb_vector, mock_async_surrealdb_client):
    """Test async name existence check"""
    # Test when name exists
    mock_async_surrealdb_client.query.return_value = [{"result": [{"name": "tom_kha"}]}]

    result = await surrealdb_vector.async_name_exists("tom_kha")
    assert result is True

    # Test when name doesn't exist
    mock_async_surrealdb_client.query.return_value = [{"result": []}]

    result = await surrealdb_vector.async_name_exists("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_async_insert(surrealdb_vector, mock_async_surrealdb_client, sample_documents):
    """Test async inserting documents"""
    with patch.object(surrealdb_vector.embedder, "get_embedding", return_value=[0.1] * 1024):
        await surrealdb_vector.async_insert(sample_documents)

        # Verify create was called for each document
        assert mock_async_surrealdb_client.create.await_count == 3

        # Check args for first document
        args, kwargs = mock_async_surrealdb_client.create.await_args_list[0]
        assert args[0] == "test_collection"
        assert "content" in args[1]
        assert "embedding" in args[1]
        assert "meta_data" in args[1]


@pytest.mark.asyncio
async def test_async_upsert(surrealdb_vector, mock_async_surrealdb_client, sample_documents):
    """Test async upserting documents"""
    with patch.object(surrealdb_vector.embedder, "get_embedding", return_value=[0.1] * 1024):
        await surrealdb_vector.async_upsert(sample_documents)

        # Verify query was called for each document
        assert mock_async_surrealdb_client.query.await_count == 3

        # Check args for first call
        args, kwargs = mock_async_surrealdb_client.query.await_args_list[0]
        assert "INSERT INTO test_collection" in args[0]
        assert "ON DUPLICATE KEY UPDATE" in args[0]
        assert "content" in args[1]
        assert "embedding" in args[1]
        assert "meta_data" in args[1]


@pytest.mark.asyncio
async def test_async_search(surrealdb_vector, mock_async_surrealdb_client):
    """Test async search functionality"""
    # Set up mock embedding
    with patch.object(surrealdb_vector.embedder, "get_embedding", return_value=[0.1] * 1024):
        # Set up mock search results
        mock_async_surrealdb_client.query.return_value = [
            {
                "result": [
                    {
                        "content": "Tom Kha Gai is a Thai coconut soup with chicken",
                        "meta_data": {"cuisine": "Thai", "type": "soup", "name": "tom_kha"},
                        "distance": 0.1,
                    },
                    {
                        "content": "Green curry is a spicy Thai curry with coconut milk",
                        "meta_data": {"cuisine": "Thai", "type": "curry", "name": "green_curry"},
                        "distance": 0.2,
                    },
                ]
            }
        ]

        # Test search
        results = await surrealdb_vector.async_search("Thai food", limit=2)
        assert len(results) == 2
        assert results[0].content == "Tom Kha Gai is a Thai coconut soup with chicken"
        assert results[1].content == "Green curry is a spicy Thai curry with coconut milk"

        # Verify search query
        mock_async_surrealdb_client.query.assert_awaited_once()
        args, kwargs = mock_async_surrealdb_client.query.await_args
        assert "SELECT" in args[0]
        assert "FROM test_collection" in args[0]
        assert "WHERE embedding <|2," in args[0]
        assert "LIMIT 2" in args[0]


@pytest.mark.asyncio
async def test_async_drop(surrealdb_vector, mock_async_surrealdb_client):
    """Test async dropping a collection"""
    await surrealdb_vector.async_drop()

    # Verify query was called
    mock_async_surrealdb_client.query.assert_awaited_once()
    args = mock_async_surrealdb_client.query.await_args[0][0]
    assert "REMOVE TABLE test_collection" in args


@pytest.mark.asyncio
async def test_async_exists(surrealdb_vector, mock_async_surrealdb_client):
    """Test async exists method"""
    # Test when collection exists
    mock_async_surrealdb_client.query.return_value = [{"result": {"tables": {"test_collection": {}}}}]

    result = await surrealdb_vector.async_exists()
    assert result is True

    # Test when collection doesn't exist
    mock_async_surrealdb_client.query.return_value = [{"result": {"tables": {}}}]

    result = await surrealdb_vector.async_exists()
    assert result is False
