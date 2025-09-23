from typing import Generator, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.surrealdb import SurrealDb

try:
    from surrealdb import Surreal
except ImportError:
    raise ImportError("surrealdb is not installed")


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Create a mock embedder."""
    embedder = MagicMock()
    embedder.dimensions = 384
    embedder.get_embedding.return_value = [0.1] * 384
    embedder.get_embedding_and_usage.return_value = [0.1] * 384, {}
    embedder.embedding_dim = 384
    return embedder


@pytest.fixture(scope="function")
def mock_surrealdb_client() -> Generator[MagicMock, None, None]:
    """Fixture to create a mock SurrealDB client"""
    with patch("surrealdb.Surreal") as mock_client_class:
        client = MagicMock(spec=Surreal)

        # Mock methods
        client.query = MagicMock(return_value=[])
        client.create = MagicMock(return_value=[])

        mock_client_class.return_value = client
        yield client


@pytest.fixture(scope="function")
def mock_async_surrealdb_client() -> Generator[AsyncMock, None, None]:
    """Create a mock Async SurrealDB client"""
    with patch("surrealdb.AsyncSurreal") as mock_async_client_class:
        client = AsyncMock(spec=Surreal)

        # Mock methods
        client.query = AsyncMock(return_value=[])
        client.create = AsyncMock(return_value=[])

        mock_async_client_class.return_value = client
        yield client


@pytest.fixture
def surrealdb_vector(mock_surrealdb_client: MagicMock, mock_embedder: MagicMock) -> SurrealDb:
    """Fixture to create a SurrealVectorDb instance with mocked client"""
    db = SurrealDb(
        collection="test_collection",
        embedder=mock_embedder,
        client=mock_surrealdb_client,
    )
    return db


@pytest.fixture
def async_surrealdb_vector(
    mock_surrealdb_client: MagicMock, mock_async_surrealdb_client: MagicMock, mock_embedder: MagicMock
) -> SurrealDb:
    """Fixture to create a SurrealVectorDb instance with mocked client"""
    db = SurrealDb(
        collection="test_collection",
        embedder=mock_embedder,
        client=mock_surrealdb_client,
        async_client=mock_async_surrealdb_client,
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
    surrealdb_vector.insert(content_hash="test_hash", documents=sample_documents)

    # Verify create was called for each document
    assert mock_surrealdb_client.create.call_count == 3

    # Check args for first document
    args, _ = mock_surrealdb_client.create.call_args_list[0]
    assert args[0] == "test_collection"
    assert "content" in args[1]
    assert "embedding" in args[1]
    assert "meta_data" in args[1]


def test_upsert(surrealdb_vector, mock_surrealdb_client, sample_documents):
    surrealdb_vector.upsert(content_hash="test_hash", documents=sample_documents)

    # Verify query was called for each document
    assert mock_surrealdb_client.query.call_count == 3

    # Check args for first call
    args, _ = mock_surrealdb_client.query.call_args_list[0]
    assert "UPSERT test_collection" in args[0]
    assert "SET content = $content" in args[0]
    assert "content" in args[1]
    assert "embedding" in args[1]
    assert "meta_data" in args[1]


def test_search(surrealdb_vector: SurrealDb, mock_surrealdb_client: MagicMock) -> None:
    """Test search functionality"""
    assert surrealdb_vector.client is mock_surrealdb_client
    # Set up mock search results
    mock_surrealdb_client.query.return_value = [
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
    assert "WHERE embedding <|2, 40|>" in args[0]
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
async def test_async_create(async_surrealdb_vector, mock_async_surrealdb_client):
    """Test async create collection"""
    await async_surrealdb_vector.async_create()

    # Verify query was called
    mock_async_surrealdb_client.query.assert_awaited_once()
    args = mock_async_surrealdb_client.query.await_args[0][0]
    assert "DEFINE TABLE IF NOT EXISTS test_collection" in args
    assert "DEFINE INDEX IF NOT EXISTS vector_idx" in args
    assert f"DIMENSION {async_surrealdb_vector.embedder.dimensions}" in args


@pytest.mark.asyncio
async def test_async_name_exists(async_surrealdb_vector, mock_async_surrealdb_client):
    """Test async name existence check"""
    # Test when name exists
    mock_async_surrealdb_client.query.return_value = [{"result": [{"name": "tom_kha"}]}]

    result = await async_surrealdb_vector.async_name_exists("tom_kha")
    assert result is True

    # Test when name doesn't exist
    mock_async_surrealdb_client.query.return_value = [{"result": []}]

    result = await async_surrealdb_vector.async_name_exists("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_async_insert(async_surrealdb_vector, mock_async_surrealdb_client, sample_documents):
    """Test async inserting documents"""
    await async_surrealdb_vector.async_insert(content_hash="test_hash", documents=sample_documents)

    # Verify create was called for each document
    assert mock_async_surrealdb_client.create.await_count == 3

    # Check args for first document
    args, kwargs = mock_async_surrealdb_client.create.await_args_list[0]
    assert args[0] == "test_collection"
    assert "content" in args[1]
    assert "embedding" in args[1]
    assert "meta_data" in args[1]


@pytest.mark.asyncio
async def test_async_upsert(async_surrealdb_vector, mock_async_surrealdb_client, sample_documents):
    """Test async upserting documents"""
    await async_surrealdb_vector.async_upsert(content_hash="test_hash", documents=sample_documents)

    # Verify query was called for each document
    assert mock_async_surrealdb_client.query.await_count == 3

    # Check args for first call
    args, kwargs = mock_async_surrealdb_client.query.await_args_list[0]
    assert "UPSERT test_collection" in args[0]
    assert "SET content = $content" in args[0]
    assert "content" in args[1]
    assert "embedding" in args[1]
    assert "meta_data" in args[1]


@pytest.mark.asyncio
async def test_async_search(async_surrealdb_vector: SurrealDb, mock_async_surrealdb_client: MagicMock) -> None:
    """Test async search functionality"""
    # Set up mock search results
    mock_async_surrealdb_client.query.return_value = [
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

    # Test search
    results = await async_surrealdb_vector.async_search("Thai food", limit=2)
    assert len(results) == 2
    assert results[0].content == "Tom Kha Gai is a Thai coconut soup with chicken"
    assert results[1].content == "Green curry is a spicy Thai curry with coconut milk"

    # Verify search query
    mock_async_surrealdb_client.query.assert_awaited_once()
    args, kwargs = mock_async_surrealdb_client.query.await_args
    assert "SELECT" in args[0]
    assert "FROM test_collection" in args[0]
    assert "WHERE embedding <|2, 40|>" in args[0]
    assert "LIMIT 2" in args[0]


@pytest.mark.asyncio
async def test_async_drop(async_surrealdb_vector, mock_async_surrealdb_client):
    """Test async dropping a collection"""
    await async_surrealdb_vector.async_drop()

    # Verify query was called
    mock_async_surrealdb_client.query.assert_awaited_once()
    args = mock_async_surrealdb_client.query.await_args[0][0]
    assert "REMOVE TABLE test_collection" in args


@pytest.mark.asyncio
async def test_async_exists(async_surrealdb_vector: SurrealDb, mock_async_surrealdb_client: MagicMock) -> None:
    """Test async exists method"""
    # Test when collection exists
    mock_async_surrealdb_client.query.return_value = [{"result": {"tables": {"test_collection": {}}}}]

    result = await async_surrealdb_vector.async_exists()
    assert result is True

    # Test when collection doesn't exist
    mock_async_surrealdb_client.query.return_value = [{"result": {"tables": {}}}]

    result = await async_surrealdb_vector.async_exists()
    assert result is False
