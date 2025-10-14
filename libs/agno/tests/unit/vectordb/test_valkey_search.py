import os
from typing import List
from unittest.mock import Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.distance import Distance
from agno.vectordb.valkey import ValkeySearch

TEST_COLLECTION = "test_collection"


@pytest.fixture
def mock_valkey_client():
    """Mock Valkey client for testing without requiring a real Valkey server"""
    with patch("agno.vectordb.valkey.valkey_search.valkey") as mock_valkey:
        # Create mock client instance
        mock_client = Mock()
        mock_valkey.Valkey.return_value = mock_client

        # Mock common operations
        mock_client.execute_command.return_value = "OK"
        mock_client.keys.return_value = []
        mock_client.exists.return_value = False
        mock_client.delete.return_value = 1
        mock_client.hset.return_value = 1
        mock_client.hget.return_value = None

        yield mock_client


@pytest.fixture
def mock_async_valkey_client():
    """Mock async Valkey client for testing without requiring a real Valkey server"""
    with patch("agno.vectordb.valkey.valkey_search.aio_valkey") as mock_aio_valkey:
        # Create mock async client instance
        mock_async_client = Mock()
        mock_aio_valkey.Valkey.return_value = mock_async_client

        # Mock common async operations
        async def mock_execute_command(*args, **kwargs):
            return "OK"

        async def mock_exists(*args, **kwargs):
            return False

        async def mock_hset(*args, **kwargs):
            return 1

        mock_async_client.execute_command = mock_execute_command
        mock_async_client.exists = mock_exists
        mock_async_client.hset = mock_hset

        yield mock_async_client


@pytest.fixture
def valkey_search(mock_embedder, mock_valkey_client):
    """Fixture to create and clean up a ValkeySearch instance"""
    db = ValkeySearch(
        collection=TEST_COLLECTION,
        embedder=mock_embedder,
        host="localhost",
        port=6379,
    )
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


def test_create_collection(valkey_search, mock_valkey_client):
    """Test creating a collection"""
    # Mock exists to return False initially
    mock_valkey_client.execute_command.side_effect = [
        Exception("Unknown index name"),  # For exists check (FT.INFO)
        "OK",  # For FT.CREATE
    ]

    valkey_search.create()

    # Verify FT.CREATE was called
    mock_valkey_client.execute_command.assert_called()
    calls = mock_valkey_client.execute_command.call_args_list
    assert any("FT.CREATE" in str(call) for call in calls)


def test_insert_documents(valkey_search, sample_documents, mock_valkey_client):
    """Test inserting documents"""
    # Mock successful insert operations
    mock_valkey_client.hset.return_value = 1

    valkey_search.insert(content_hash="test_hash", documents=sample_documents)

    # Verify hset was called for each document
    assert mock_valkey_client.hset.call_count >= len(sample_documents)


def test_search_documents(valkey_search, sample_documents, mock_valkey_client):
    """Test searching documents"""
    # Mock search result format: [count, doc_key1, fields1, doc_key2, fields2, ...]
    mock_search_result = [
        2,  # count
        b"doc:test_collection:tom_kha",  # doc key 1
        [
            b"content",
            b"Tom Kha Gai is a Thai coconut soup with chicken",
            b"metadata",
            b'{"cuisine": "Thai", "type": "soup"}',
            b"id",
            b"tom_kha",
            b"__vector_score",
            b"0.1234",
        ],
        b"doc:test_collection:green_curry",  # doc key 2
        [
            b"content",
            b"Green curry is a spicy Thai curry with coconut milk",
            b"metadata",
            b'{"cuisine": "Thai", "type": "curry"}',
            b"id",
            b"green_curry",
            b"__vector_score",
            b"0.2345",
        ],
    ]

    # Mock the binary_client property to return a mock with execute_command
    mock_binary_client = Mock()
    mock_binary_client.execute_command.return_value = mock_search_result

    # Patch the binary_client property directly on the instance
    with patch.object(type(valkey_search), "binary_client", new_callable=lambda: mock_binary_client):
        results = valkey_search.search("coconut dishes", limit=2)

        # Verify search was executed
        mock_binary_client.execute_command.assert_called()

        # Verify results
        assert len(results) == 2
        assert any("coconut" in doc.content.lower() for doc in results)
        assert all(hasattr(doc, "reranking_score") for doc in results)


def test_upsert_documents(valkey_search, sample_documents, mock_valkey_client):
    """Test upserting documents"""
    # Mock successful upsert operations (same as insert for Valkey)
    mock_valkey_client.hset.return_value = 1

    valkey_search.upsert(content_hash="test_hash", documents=[sample_documents[0]])

    # Verify hset was called
    assert mock_valkey_client.hset.call_count >= 1


def test_name_exists(valkey_search, mock_valkey_client):
    """Test name existence check"""
    # Mock search result for existing name
    mock_valkey_client.execute_command.return_value = [1, "doc_key", "fields"]

    result = valkey_search.name_exists("tom_kha")
    assert result is True

    # Mock search result for non-existing name
    mock_valkey_client.execute_command.return_value = [0]

    result = valkey_search.name_exists("nonexistent")
    assert result is False


def test_content_hash_exists(valkey_search, mock_valkey_client):
    """Test content hash existence check"""
    # Mock keys and hget operations
    mock_valkey_client.keys.return_value = [b"doc:test_collection:doc1", b"doc:test_collection:doc2"]
    mock_valkey_client.hget.side_effect = ["test_hash", "other_hash"]

    result = valkey_search.content_hash_exists("test_hash")
    assert result is True

    # Test non-existing hash
    mock_valkey_client.hget.side_effect = ["other_hash1", "other_hash2"]

    result = valkey_search.content_hash_exists("nonexistent_hash")
    assert result is False


def test_delete_by_id(valkey_search, mock_valkey_client):
    """Test deleting documents by ID"""
    # Mock successful deletion
    mock_valkey_client.delete.return_value = 1

    result = valkey_search.delete_by_id("tom_kha")
    assert result is True

    # Mock failed deletion (document not found)
    mock_valkey_client.delete.return_value = 0

    result = valkey_search.delete_by_id("nonexistent")
    assert result is False


def test_delete_by_name(valkey_search, mock_valkey_client):
    """Test deleting documents by name"""
    # Mock successful deletion
    mock_valkey_client.delete.return_value = 1

    result = valkey_search.delete_by_name("tom_kha")
    assert result is True

    # Verify delete was called with correct key format
    mock_valkey_client.delete.assert_called_with(f"doc:{TEST_COLLECTION}:tom_kha")


def test_delete_by_metadata(valkey_search, mock_valkey_client):
    """Test deleting documents by metadata"""
    # Mock search result with documents to delete
    mock_search_result = [
        1,  # count
        {valkey_search.id_field: "tom_kha"},  # document data
    ]
    mock_valkey_client.execute_command.return_value = mock_search_result
    mock_valkey_client.delete.return_value = 1

    result = valkey_search.delete_by_metadata({"cuisine": "Thai"})
    assert result is True

    # Test with no matching documents
    mock_valkey_client.execute_command.return_value = [0]

    result = valkey_search.delete_by_metadata({"cuisine": "Italian"})
    assert result is False


def test_delete_by_content_id(valkey_search, mock_valkey_client):
    """Test deleting documents by content ID"""
    # Mock successful deletion
    mock_valkey_client.delete.return_value = 1

    result = valkey_search.delete_by_content_id("recipe_1")
    assert result is True

    # Verify delete was called with correct key format
    mock_valkey_client.delete.assert_called_with(f"doc:{TEST_COLLECTION}:recipe_1")


def test_update_metadata(valkey_search, mock_valkey_client):
    """Test updating metadata"""
    # Mock document exists
    mock_valkey_client.exists.return_value = True
    mock_valkey_client.hset.return_value = 1

    metadata = {"doc_type": "recipe_book", "updated": True}
    valkey_search.update_metadata("test_content_id", metadata)

    # Verify hset was called to update metadata
    mock_valkey_client.hset.assert_called()

    # Test with non-existent document
    mock_valkey_client.exists.return_value = False

    # Should not raise an exception for non-existent document
    valkey_search.update_metadata("nonexistent_id", metadata)


def test_drop_collection(valkey_search, mock_valkey_client):
    """Test dropping collection"""
    mock_valkey_client.execute_command.return_value = "OK"

    valkey_search.drop()

    # Verify FT.DROPINDEX was called
    mock_valkey_client.execute_command.assert_called_with("FT.DROPINDEX", TEST_COLLECTION)


def test_exists(valkey_search, mock_valkey_client):
    """Test index existence check"""
    # Mock existing index
    mock_valkey_client.execute_command.return_value = {"index_name": TEST_COLLECTION}

    result = valkey_search.exists()
    assert result is True

    # Mock non-existing index
    mock_valkey_client.execute_command.side_effect = Exception("Unknown index name")

    result = valkey_search.exists()
    assert result is False


def test_delete_all_documents(valkey_search, mock_valkey_client):
    """Test deleting all documents in the index"""
    # Mock keys and delete operations
    mock_valkey_client.keys.return_value = [
        b"doc:test_collection:doc1",
        b"doc:test_collection:doc2",
        b"doc:test_collection:doc3",
    ]
    mock_valkey_client.delete.return_value = 3

    result = valkey_search.delete()
    assert result is True

    # Verify delete was called with all keys
    mock_valkey_client.delete.assert_called()


def test_distance_metrics(mock_embedder, mock_valkey_client):
    """Test different distance metrics"""
    # Test cosine distance (default)
    db_cosine = ValkeySearch(collection="test_cosine", embedder=mock_embedder, distance=Distance.cosine)
    assert db_cosine._get_distance_metric() == "COSINE"

    # Test L2 distance
    db_l2 = ValkeySearch(collection="test_l2", embedder=mock_embedder, distance=Distance.l2)
    assert db_l2._get_distance_metric() == "L2"

    # Test inner product distance
    db_ip = ValkeySearch(collection="test_ip", embedder=mock_embedder, distance=Distance.max_inner_product)
    assert db_ip._get_distance_metric() == "IP"


def test_vector_conversion(valkey_search):
    """Test vector to bytes conversion"""
    vector = [1.0, 2.0, 3.0, 4.0]
    vector_bytes = valkey_search._vector_to_bytes(vector)

    # Verify it's bytes
    assert isinstance(vector_bytes, bytes)

    # Verify round-trip conversion
    converted_back = valkey_search._bytes_to_vector(vector_bytes)
    assert len(converted_back) == len(vector)
    # Use approximate equality for floats
    for original, converted in zip(vector, converted_back):
        assert abs(original - converted) < 1e-6


def test_upsert_available(valkey_search):
    """Test upsert availability check"""
    assert valkey_search.upsert_available() is True


def test_optimize(valkey_search, mock_valkey_client):
    """Test index optimization"""
    mock_valkey_client.execute_command.return_value = "OK"

    # Should not raise an exception
    valkey_search.optimize()

    # Verify FT.OPTIMIZE was called
    mock_valkey_client.execute_command.assert_called_with("FT.OPTIMIZE", TEST_COLLECTION)


def test_error_handling(valkey_search, mock_valkey_client):
    """Test error handling scenarios"""
    # Test search with connection error - patch the binary client
    with patch("valkey.Valkey") as mock_binary_client_class:
        mock_binary_client = mock_binary_client_class.return_value
        mock_binary_client.execute_command.side_effect = Exception("Connection failed")

        results = valkey_search.search("test query")
        assert len(results) == 0

    # Test insert with connection error - this should raise an exception
    mock_valkey_client.hset.side_effect = Exception("Insert failed")

    with pytest.raises(Exception, match="Insert failed"):
        valkey_search.insert("test_hash", [Document(content="test", name="test", id="test")])


def test_custom_embedder(mock_embedder, mock_valkey_client):
    """Test using a custom embedder"""
    db = ValkeySearch(collection=TEST_COLLECTION, embedder=mock_embedder)
    assert db.embedder == mock_embedder


def test_search_with_filters(valkey_search, mock_valkey_client):
    """Test searching with metadata filters"""
    # Mock search result
    mock_search_result = [
        1,  # count
        b"doc:test_collection:tom_kha",
        [
            b"content",
            b"Tom Kha Gai is a Thai coconut soup",
            b"metadata",
            b'{"cuisine": "Thai", "type": "soup"}',
            b"id",
            b"tom_kha",
            b"__vector_score",
            b"0.1234",
        ],
    ]

    mock_binary_client = Mock()
    mock_binary_client.execute_command.return_value = mock_search_result

    with patch.object(type(valkey_search), "binary_client", new_callable=lambda: mock_binary_client):
        # Test with string filter
        results = valkey_search.search("soup", limit=1, filters={"cuisine": "Thai"})
        assert len(results) <= 1

        # Test with numeric filter
        results = valkey_search.search("soup", limit=1, filters={"rating": 4.5})
        assert len(results) <= 1

        # Test with list filter
        results = valkey_search.search("soup", limit=1, filters={"tags": ["spicy", "coconut"]})
        assert len(results) <= 1


# Async Tests
@pytest.mark.asyncio
async def test_async_create_collection(valkey_search, mock_async_valkey_client):
    """Test creating a collection asynchronously"""
    await valkey_search.async_create()
    # Verify async create was called (mocked)
    assert True  # If no exception, test passes


@pytest.mark.asyncio
async def test_async_insert_documents(valkey_search, sample_documents, mock_async_valkey_client):
    """Test inserting documents asynchronously"""

    # Mock async embedder - need to return a coroutine
    async def mock_async_embedding(content):
        return [0.1, 0.2, 0.3]

    with patch.object(valkey_search.embedder, "async_get_embedding", side_effect=mock_async_embedding):
        await valkey_search.async_insert(content_hash="test_hash", documents=sample_documents)

        # If we get here without error, async insert worked
        assert True


@pytest.mark.asyncio
async def test_async_search_documents(valkey_search, mock_async_valkey_client):
    """Test searching documents asynchronously"""
    # Mock async search result
    mock_search_result = [
        1,  # count
        b"doc:test_collection:tom_kha",
        [
            b"content",
            b"Tom Kha Gai is a Thai coconut soup",
            b"metadata",
            b'{"cuisine": "Thai", "type": "soup"}',
            b"id",
            b"tom_kha",
            b"__vector_score",
            b"0.1234",
        ],
    ]

    # Mock async embedder - need to return a coroutine
    async def mock_async_embedding(content):
        return [0.1, 0.2, 0.3]

    # Create a mock async binary client
    mock_async_binary_client = Mock()

    async def mock_execute_command(*args, **kwargs):
        return mock_search_result

    mock_async_binary_client.execute_command = mock_execute_command

    with patch.object(type(valkey_search), "async_binary_client", new_callable=lambda: mock_async_binary_client):
        with patch.object(valkey_search.embedder, "async_get_embedding", side_effect=mock_async_embedding):
            results = await valkey_search.async_search("coconut dishes", limit=1)

            # Verify results
            assert len(results) == 1
            assert results[0].content == "Tom Kha Gai is a Thai coconut soup"


@pytest.mark.asyncio
async def test_async_upsert_documents(valkey_search, sample_documents, mock_async_valkey_client):
    """Test upserting documents asynchronously"""

    # Mock async embedder - need to return a coroutine
    async def mock_async_embedding(content):
        return [0.1, 0.2, 0.3]

    with patch.object(valkey_search.embedder, "async_get_embedding", side_effect=mock_async_embedding):
        await valkey_search.async_upsert(content_hash="test_hash", documents=[sample_documents[0]])

        # If we get here without error, async upsert worked
        assert True


@pytest.mark.asyncio
async def test_async_name_exists(valkey_search, mock_async_valkey_client):
    """Test document name existence check asynchronously"""

    # Mock async execute_command to return existing document
    async def mock_execute_command(*args, **kwargs):
        return [1, "doc_key", "fields"]  # Mock existing document

    mock_async_valkey_client.execute_command = mock_execute_command

    result = await valkey_search.async_name_exists("tom_kha")
    assert result is True


@pytest.mark.asyncio
async def test_async_drop_collection(valkey_search, mock_async_valkey_client):
    """Test dropping collection asynchronously"""
    await valkey_search.async_drop()
    # If no exception, test passes
    assert True


@pytest.mark.asyncio
async def test_async_exists(valkey_search, mock_async_valkey_client):
    """Test exists check asynchronously"""

    # Mock successful FT.INFO response
    async def mock_execute_command(*args, **kwargs):
        return {"index_name": TEST_COLLECTION}

    mock_async_valkey_client.execute_command = mock_execute_command

    result = await valkey_search.async_exists()
    assert result is True


@pytest.mark.asyncio
async def test_async_fallback_to_sync(valkey_search, sample_documents):
    """Test async operations falling back to sync when async fails"""

    # Mock async operation to fail with event loop error
    async def mock_failing_async_embed(*args, **kwargs):
        raise RuntimeError("Event loop is closed")

    with patch.object(valkey_search.embedder, "async_get_embedding", side_effect=mock_failing_async_embed):
        with patch.object(valkey_search, "insert") as mock_sync_insert:
            await valkey_search.async_insert(content_hash="test_hash", documents=sample_documents)

            # Verify sync fallback was called
            mock_sync_insert.assert_called()

            # Verify prefer_sync flag is set
            assert valkey_search._prefer_sync is True


def test_client_properties(valkey_search):
    """Test client property accessors"""
    # Test regular client
    client = valkey_search.client
    assert client is not None

    # Test binary client
    binary_client = valkey_search.binary_client
    assert binary_client is not None

    # Test async client
    async_client = valkey_search.async_client
    assert async_client is not None

    # Test async binary client
    async_binary_client = valkey_search.async_binary_client
    assert async_binary_client is not None


def test_get_count(valkey_search, sample_documents, mock_valkey_client):
    """Test document count"""
    # Mock empty collection
    mock_valkey_client.keys.return_value = []
    assert valkey_search.get_count() == 0

    # Mock collection with documents
    mock_valkey_client.keys.return_value = [
        b"doc:test_collection:doc1",
        b"doc:test_collection:doc2",
        b"doc:test_collection:doc3",
    ]
    assert valkey_search.get_count() == 3


def test_configuration_properties(valkey_search):
    """Test ValkeySearch configuration properties"""
    assert valkey_search.collection == TEST_COLLECTION
    assert valkey_search.host == "localhost"
    assert valkey_search.port == 6379
    assert valkey_search.db == 0
    assert valkey_search.decode_responses is True
    assert valkey_search.distance == Distance.cosine
    assert valkey_search.prefix == f"doc:{TEST_COLLECTION}:"
    assert valkey_search.vector_field == "vector"
    assert valkey_search.content_field == "content"
    assert valkey_search.metadata_field == "metadata"
    assert valkey_search.id_field == "id"
    assert valkey_search.content_hash_field == "content_hash"
