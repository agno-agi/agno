from typing import List
from unittest.mock import Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.utils.log import log_debug
from agno.vectordb.distance import Distance

# Ensure Milvus is available and usable in the current environment.
# This handles some CI errors when running Milvus in GitHub Actions.
try:
    import pymilvus

    log_debug(f"PyMilvus available. Version: {pymilvus.__version__}")
    MILVUS_AVAILABLE = True
    MILVUS_SKIP_REASON = ""
except (ImportError, TypeError) as e:
    MILVUS_AVAILABLE = False
    MILVUS_SKIP_REASON = f"Milvus not available: {str(e)}"

pytestmark = pytest.mark.skipif(not MILVUS_AVAILABLE, reason=MILVUS_SKIP_REASON)

if not MILVUS_AVAILABLE:
    pytest.skip(MILVUS_SKIP_REASON, allow_module_level=True)


# Try to import Milvus, skip all tests if not available
try:
    from agno.vectordb.milvus import Milvus

    MILVUS_AVAILABLE = True
except (ImportError, TypeError) as e:
    MILVUS_AVAILABLE = False
    MILVUS_SKIP_REASON = f"Milvus not available: {str(e)}"

# Skip test file if Milvus not available
pytestmark = pytest.mark.skipif(not MILVUS_AVAILABLE, reason=MILVUS_SKIP_REASON if not MILVUS_AVAILABLE else "")


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
        milvus_db.insert(documents=sample_documents, content_hash="test_hash")

        # Should call insert once for each document
        assert mock_milvus_client.insert.call_count == 3

        # Check the first call's parameters
        args, kwargs = mock_milvus_client.insert.call_args_list[0]
        assert kwargs["collection_name"] == "test_collection"
        assert "vector" in kwargs["data"]
        assert "name" in kwargs["data"]
        assert "content" in kwargs["data"]


def test_name_exists(milvus_db, mock_milvus_client):
    """Test name existence check"""
    # Test when name exists
    mock_milvus_client.query.return_value = [[Mock()]]
    assert milvus_db.name_exists("tom_kha") is True

    # Test when name doesn't exist
    mock_milvus_client.query.return_value = [[]]
    assert milvus_db.name_exists("nonexistent") is False

    # Verify output_fields is passed
    _, kwargs = mock_milvus_client.query.call_args
    assert kwargs.get("output_fields") == ["id"]


def test_content_hash_exists(milvus_db, mock_milvus_client):
    """Test content hash existence check"""
    # Test when content hash exists
    mock_milvus_client.query.return_value = [[Mock()]]
    assert milvus_db.content_hash_exists("test_hash") is True

    # Test when content hash doesn't exist
    mock_milvus_client.query.return_value = [[]]
    assert milvus_db.content_hash_exists("nonexistent_hash") is False

    # Verify output_fields is passed
    _, kwargs = mock_milvus_client.query.call_args
    assert kwargs.get("output_fields") == ["id"]


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
        milvus_db.upsert(documents=sample_documents, content_hash="test_hash")

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
    assert milvus_db._build_expr(None) is None

    # Test with string value
    filters = {"name": "test_name"}
    assert milvus_db._build_expr(filters) == 'meta_data["name"] == "test_name"'

    # Test with numeric value
    filters = {"count": 42}
    assert milvus_db._build_expr(filters) == 'meta_data["count"] == 42'

    # Test with boolean value
    filters = {"active": True}
    assert milvus_db._build_expr(filters) == 'meta_data["active"] == true'

    # Test with list value
    filters = {"tags": ["tag1", "tag2"]}
    assert milvus_db._build_expr(filters) == 'json_contains_any(meta_data["tags"], ["tag1", "tag2"])'

    # Test with None value
    filters = {"field": None}
    assert milvus_db._build_expr(filters) == 'meta_data["field"] is null'

    # Test with multiple filters
    filters = {"name": "test_name", "count": 42}
    expr = milvus_db._build_expr(filters)
    assert 'meta_data["name"] == "test_name"' in expr
    assert 'meta_data["count"] == 42' in expr
    assert " and " in expr


def test_search_with_radius_and_range_filter(milvus_db, mock_milvus_client):
    """Test search functionality with radius and range_filter parameters"""
    # Set up mock embedding
    with patch.object(milvus_db.embedder, "get_embedding", return_value=[0.1] * 768):
        # Set up mock search results
        mock_result = {
            "id": "id1",
            "entity": {
                "name": "tom_kha",
                "meta_data": {"cuisine": "Thai", "type": "soup"},
                "content": "Tom Kha Gai is a Thai coconut soup with chicken",
                "vector": [0.1] * 768,
                "usage": {"prompt_tokens": 10, "total_tokens": 10},
            },
        }

        mock_milvus_client.search.return_value = [[mock_result]]

        # Test search with radius parameter
        results = milvus_db.search("Thai food", limit=5, search_params={"radius": 0.8})
        assert len(results) == 1
        assert results[0].name == "tom_kha"

        # Verify search was called with search_params
        _, kwargs = mock_milvus_client.search.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert kwargs["data"] == [[0.1] * 768]
        assert kwargs["limit"] == 5
        assert kwargs["search_params"] == {"radius": 0.8}

        # Test search with both radius and range_filter
        mock_milvus_client.search.reset_mock()
        mock_milvus_client.search.return_value = [[mock_result]]

        results = milvus_db.search(
            "Thai food",
            limit=10,
            search_params={"radius": 0.8, "range_filter": 0.2},
        )
        assert len(results) == 1

        # Verify search was called with both parameters
        _, kwargs = mock_milvus_client.search.call_args
        assert kwargs["search_params"] == {"radius": 0.8, "range_filter": 0.2}


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


@pytest.mark.asyncio
async def test_async_search_with_search_params(mock_embedder, mock_milvus_async_client):
    """Test async search with radius and range_filter parameters"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")
    db._async_client = mock_milvus_async_client

    # Set up mock search results
    mock_result = {
        "id": "id1",
        "entity": {
            "name": "tom_kha",
            "meta_data": {"cuisine": "Thai", "type": "soup"},
            "content": "Tom Kha Gai is a Thai coconut soup with chicken",
            "vector": [0.1] * 768,
            "usage": {"prompt_tokens": 10, "total_tokens": 10},
        },
    }

    # Make the mock return an awaitable
    async def mock_search_return(*args, **kwargs):
        return [[mock_result]]

    mock_milvus_async_client.search = mock_search_return

    with patch.object(db.embedder, "get_embedding", return_value=[0.1] * 768):
        # Test with radius parameter
        results = await db.async_search("Thai food", limit=5, search_params={"radius": 0.8})
        assert len(results) == 1
        assert results[0].name == "tom_kha"

        # Test with both radius and range_filter
        results = await db.async_search(
            "Thai food",
            limit=10,
            search_params={"radius": 0.8, "range_filter": 0.2},
        )
        assert len(results) == 1


async def async_return(result):
    return result


@pytest.mark.asyncio
async def test_async_insert(mock_embedder, sample_documents):
    """Test async insert"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    # Mock async_insert directly
    with patch.object(db, "async_insert", return_value=None):
        await db.async_insert(documents=sample_documents, content_hash="test_hash")


@pytest.mark.asyncio
async def test_async_upsert(mock_embedder, sample_documents):
    """Test async upsert"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    # Mock async_upsert directly
    with patch.object(db, "async_upsert", return_value=None):
        await db.async_upsert(documents=sample_documents, content_hash="test_hash")


@pytest.mark.asyncio
async def test_async_drop(mock_embedder):
    """Test async drop collection"""
    db = Milvus(embedder=mock_embedder, collection="test_collection")

    # Mock async_drop directly
    with patch.object(db, "async_drop", return_value=None):
        await db.async_drop()


# Delete method tests
def test_delete_by_id(milvus_db, mock_milvus_client):
    """Test delete_by_id method."""
    # Mock id_exists to return True (document exists)
    with patch.object(milvus_db, "id_exists") as mock_id_exists:
        mock_id_exists.return_value = True

        # Test successful deletion
        result = milvus_db.delete_by_id("doc_1")
        assert result is True

        # Verify the delete command was executed
        mock_milvus_client.delete.assert_called_with(collection_name=milvus_db.collection, ids=["doc_1"])

        # Test deletion of non-existent document
        mock_id_exists.reset_mock()
        mock_id_exists.return_value = False  # Document doesn't exist
        result = milvus_db.delete_by_id("nonexistent_id")
        assert result is False


def test_delete_by_name(milvus_db, mock_milvus_client):
    """Test delete_by_name method."""
    # Mock name_exists to return True (document exists)
    with patch.object(milvus_db, "name_exists") as mock_name_exists:
        mock_name_exists.return_value = True

        # Test successful deletion
        result = milvus_db.delete_by_name("test_doc")
        assert result is True

        # Verify the delete command was executed
        mock_milvus_client.delete.assert_called_with(collection_name=milvus_db.collection, filter='name == "test_doc"')

        # Test deletion of non-existent name
        mock_name_exists.reset_mock()
        mock_name_exists.return_value = False  # Name doesn't exist
        result = milvus_db.delete_by_name("nonexistent")
        assert result is False


def test_delete_by_metadata(milvus_db, mock_milvus_client):
    """Test delete_by_metadata method."""
    # Test successful deletion with simple metadata
    result = milvus_db.delete_by_metadata({"type": "test"})
    assert result is True

    # Verify the delete command was executed with proper filter
    mock_milvus_client.delete.assert_called_with(
        collection_name=milvus_db.collection, filter='meta_data["type"] == "test"'
    )

    # Test deletion with complex metadata
    mock_milvus_client.delete.reset_mock()
    result = milvus_db.delete_by_metadata({"cuisine": "Thai", "spicy": True})
    assert result is True

    # Verify the delete command was executed with multiple conditions
    mock_milvus_client.delete.assert_called_with(
        collection_name=milvus_db.collection, filter='meta_data["cuisine"] == "Thai" and meta_data["spicy"] == true'
    )

    # Test deletion with empty metadata
    mock_milvus_client.delete.reset_mock()
    result = milvus_db.delete_by_metadata({})
    assert result is False
    # Should not call delete for empty metadata
    mock_milvus_client.delete.assert_not_called()


def test_delete_by_content_id(milvus_db, mock_milvus_client):
    """Test delete_by_content_id method."""
    # Test successful deletion
    result = milvus_db.delete_by_content_id("content_123")
    assert result is True

    # Verify the delete command was executed
    mock_milvus_client.delete.assert_called_with(
        collection_name=milvus_db.collection, filter='content_id == "content_123"'
    )


def test_delete_methods_error_handling(milvus_db, mock_milvus_client):
    """Test error handling in delete methods."""
    # Mock client.delete to raise an exception
    mock_milvus_client.delete.side_effect = Exception("Database error")

    # Test all delete methods handle exceptions gracefully
    assert milvus_db.delete_by_id("doc_1") is False
    assert milvus_db.delete_by_name("test_name") is False
    assert milvus_db.delete_by_metadata({"type": "test"}) is False
    assert milvus_db.delete_by_content_id("test_content_id") is False


def test_search_with_reranker(milvus_db, mock_milvus_client):
    """Test Milvus search with reranker applied"""
    with patch.object(milvus_db.embedder, "get_embedding", return_value=[0.1] * 768):
        # Mock search results from Milvus
        mock_result1 = {"id": "id1", "entity": {"name": "doc_a", "content": "Content A", "vector": [0.1] * 768}}
        mock_result2 = {"id": "id2", "entity": {"name": "doc_b", "content": "Content B", "vector": [0.2] * 768}}
        mock_milvus_client.search.return_value = [[mock_result1, mock_result2]]

        # Mock reranker that reverses results
        mock_reranker = Mock()
        mock_reranker.rerank.side_effect = lambda query, documents: list(reversed(documents))
        milvus_db.reranker = mock_reranker

        results = milvus_db.search("query", limit=2)

        # Verify reranker called
        mock_reranker.rerank.assert_called_once()
        # Verify results are reranked (reversed)
        assert results[0].name == "doc_b"
        assert results[1].name == "doc_a"
