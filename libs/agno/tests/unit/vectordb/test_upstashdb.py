import os
from typing import List
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.upstashdb import UpstashVectorDb


@pytest.fixture
def mock_embedder():
    """Fixture to create a mock embedder"""
    embedder = MagicMock()
    embedder.dimensions = 384
    embedder.get_embedding.return_value = [0.1] * 384
    embedder.embedding_dim = 384
    return embedder


@pytest.fixture
def mock_upstash_index():
    """Fixture to create a mock Upstash index"""
    with patch("upstash_vector.Index") as mock_index_class:
        mock_index = Mock()
        mock_index_class.return_value = mock_index

        # Mock info response
        mock_info = Mock()
        mock_info.vector_count = 0
        mock_info.dimension = 384
        mock_index.info.return_value = mock_info

        # Mock upsert response
        mock_index.upsert.return_value = "Success"

        # Mock query response
        mock_index.query.return_value = []

        # Mock delete response
        mock_delete_result = Mock()
        mock_delete_result.deleted = 0
        mock_index.delete.return_value = mock_delete_result

        # Mock fetch response
        mock_index.fetch.return_value = []

        # Mock reset response
        mock_index.reset.return_value = "Success"

        yield mock_index


@pytest.fixture
def upstash_db(mock_upstash_index):
    """Fixture to create an UpstashVectorDb instance with mocked dependencies"""
    with patch.dict(
        os.environ,
        {"UPSTASH_VECTOR_REST_URL": "https://test-url.upstash.io", "UPSTASH_VECTOR_REST_TOKEN": "test-token"},
    ):
        db = UpstashVectorDb(
            url="https://test-url.upstash.io",
            token="test-token",
            embedder=None,  # Use Upstash embeddings
        )
        db._index = mock_upstash_index
        yield db


@pytest.fixture
def upstash_db_with_custom_embedder(mock_upstash_index, mock_embedder):
    """Fixture to create an UpstashVectorDb instance with custom embedder"""
    with patch.dict(
        os.environ,
        {"UPSTASH_VECTOR_REST_URL": "https://test-url.upstash.io", "UPSTASH_VECTOR_REST_TOKEN": "test-token"},
    ):
        db = UpstashVectorDb(url="https://test-url.upstash.io", token="test-token", embedder=mock_embedder)
        db._index = mock_upstash_index
        yield db


@pytest.fixture
def sample_documents() -> List[Document]:
    """Fixture to create sample documents"""
    return [
        Document(
            content="Tom Kha Gai is a Thai coconut soup with chicken",
            meta_data={"cuisine": "Thai", "type": "soup"},
            name="tom_kha",
            id="doc_1",
        ),
        Document(
            content="Pad Thai is a stir-fried rice noodle dish",
            meta_data={"cuisine": "Thai", "type": "noodles"},
            name="pad_thai",
            id="doc_2",
        ),
        Document(
            content="Green curry is a spicy Thai curry with coconut milk",
            meta_data={"cuisine": "Thai", "type": "curry"},
            name="green_curry",
            id="doc_3",
        ),
    ]


def test_initialization_with_embedder(mock_embedder):
    """Test UpstashVectorDb initialization with custom embedder"""
    db = UpstashVectorDb(url="https://test-url.upstash.io", token="test-token", embedder=mock_embedder)
    assert db.url == "https://test-url.upstash.io"
    assert db.token == "test-token"
    assert db.embedder == mock_embedder
    assert db.use_upstash_embeddings is False


def test_initialization_without_embedder():
    """Test UpstashVectorDb initialization without embedder (Upstash embeddings)"""
    db = UpstashVectorDb(url="https://test-url.upstash.io", token="test-token")
    assert db.url == "https://test-url.upstash.io"
    assert db.token == "test-token"
    assert db.embedder is None
    assert db.use_upstash_embeddings is True


def test_exists(upstash_db):
    """Test index existence check"""
    assert upstash_db.exists() is True

    # Test when index doesn't exist
    upstash_db.index.info.side_effect = Exception("Index not found")
    assert upstash_db.exists() is False


def test_upsert_with_upstash_embeddings(upstash_db, sample_documents):
    """Test upserting documents with Upstash embeddings"""
    upstash_db.upsert(documents=sample_documents, content_hash="test_hash")

    # Verify upsert was called
    upstash_db.index.upsert.assert_called_once()

    # Check the vectors passed to upsert
    call_args = upstash_db.index.upsert.call_args
    vectors = call_args[0][0]  # First positional argument

    assert len(vectors) == 3
    for i, vector in enumerate(vectors):
        assert vector.id == sample_documents[i].id
        assert vector.data == sample_documents[i].content
        assert vector.metadata["name"] == sample_documents[i].name
        assert vector.metadata["cuisine"] == sample_documents[i].meta_data["cuisine"]


def test_upsert_with_filters(upstash_db, sample_documents):
    """Test upserting documents with filters"""
    filters = {"source": "test", "version": "1.0"}
    upstash_db.upsert(documents=sample_documents, content_hash="test_hash", filters=filters)

    # Check that filters were added to metadata
    call_args = upstash_db.index.upsert.call_args
    vectors = call_args[0][0]

    for vector in vectors:
        assert vector.metadata["source"] == "test"
        assert vector.metadata["version"] == "1.0"


def test_upsert_with_content_id(upstash_db, sample_documents):
    """Test upserting documents with content_id"""
    # Add content_id to documents
    for i, doc in enumerate(sample_documents):
        doc.content_id = f"content_{i + 1}"

    upstash_db.upsert(documents=sample_documents, content_hash="test_hash")

    call_args = upstash_db.index.upsert.call_args
    vectors = call_args[0][0]

    for i, vector in enumerate(vectors):
        assert vector.metadata["content_id"] == f"content_{i + 1}"


def test_search_with_upstash_embeddings(upstash_db):
    """Test search with Upstash embeddings"""
    # Mock query response
    mock_result = Mock()
    mock_result.id = "doc_1"
    mock_result.data = "Tom Kha Gai is a Thai coconut soup"
    mock_result.metadata = {"cuisine": "Thai"}
    mock_result.vector = [0.1] * 384
    upstash_db.index.query.return_value = [mock_result]

    results = upstash_db.search("Thai soup", limit=5)

    assert len(results) == 1
    assert results[0].id == "doc_1"
    assert results[0].content == "Tom Kha Gai is a Thai coconut soup"
    assert results[0].meta_data["cuisine"] == "Thai"

    # Verify query was called with correct parameters
    upstash_db.index.query.assert_called_once_with(
        data="Thai soup",
        namespace="",
        top_k=5,
        filter="",
        include_data=True,
        include_metadata=True,
        include_vectors=True,
    )


def test_search_with_custom_embeddings(upstash_db_with_custom_embedder):
    """Test search with custom embeddings"""
    # Mock query response
    mock_result = Mock()
    mock_result.id = "doc_1"
    mock_result.data = "Tom Kha Gai is a Thai coconut soup"
    mock_result.metadata = {"cuisine": "Thai"}
    mock_result.vector = [0.1] * 384
    upstash_db_with_custom_embedder.index.query.return_value = [mock_result]

    results = upstash_db_with_custom_embedder.search("Thai soup", limit=5)

    assert len(results) == 1
    # Verify embedder was called
    upstash_db_with_custom_embedder.embedder.get_embedding.assert_called_once_with("Thai soup")


def test_delete_by_id(upstash_db):
    """Test deleting documents by ID"""
    # Mock successful deletion
    mock_delete_result = Mock()
    mock_delete_result.deleted = 1
    upstash_db.index.delete.return_value = mock_delete_result

    result = upstash_db.delete_by_id("doc_1")
    assert result is True

    upstash_db.index.delete.assert_called_once_with(ids=["doc_1"], namespace="")


def test_delete_by_name(upstash_db):
    """Test deleting documents by name"""
    # Mock successful deletion
    mock_delete_result = Mock()
    mock_delete_result.deleted = 2
    upstash_db.index.delete.return_value = mock_delete_result

    result = upstash_db.delete_by_name("tom_kha")
    assert result is True

    upstash_db.index.delete.assert_called_once_with(filter='name = "tom_kha"', namespace="")


def test_delete_by_metadata(upstash_db):
    """Test deleting documents by metadata"""
    # Mock successful deletion
    mock_delete_result = Mock()
    mock_delete_result.deleted = 3
    upstash_db.index.delete.return_value = mock_delete_result

    metadata = {"cuisine": "Thai", "type": "soup"}
    result = upstash_db.delete_by_metadata(metadata)
    assert result is True

    upstash_db.index.delete.assert_called_once_with(filter='cuisine = "Thai" AND type = "soup"', namespace="")


def test_delete_by_metadata_with_numbers(upstash_db):
    """Test deleting documents by metadata with numeric values"""
    # Mock successful deletion
    mock_delete_result = Mock()
    mock_delete_result.deleted = 1
    upstash_db.index.delete.return_value = mock_delete_result

    metadata = {"rating": 5, "spicy": True}
    result = upstash_db.delete_by_metadata(metadata)
    assert result is True

    upstash_db.index.delete.assert_called_once_with(filter="rating = 5 AND spicy = True", namespace="")


def test_delete_by_content_id(upstash_db):
    """Test deleting documents by content_id"""
    # Mock successful deletion
    mock_delete_result = Mock()
    mock_delete_result.deleted = 1
    upstash_db.index.delete.return_value = mock_delete_result

    result = upstash_db.delete_by_content_id("content_123")
    assert result is True

    upstash_db.index.delete.assert_called_once_with(filter='content_id = "content_123"', namespace="")


def test_delete_all(upstash_db):
    """Test deleting all documents"""
    upstash_db.index.reset.return_value = "Success"

    result = upstash_db.delete(delete_all=True)
    assert result is True

    upstash_db.index.reset.assert_called_once_with(namespace="", all=True)


def test_delete_namespace(upstash_db):
    """Test deleting documents in a namespace"""
    upstash_db.index.reset.return_value = "Success"

    result = upstash_db.delete(namespace="test_namespace")
    assert result is True

    upstash_db.index.reset.assert_called_once_with(namespace="test_namespace", all=False)


def test_get_index_info(upstash_db):
    """Test getting index information"""
    mock_info = Mock()
    mock_info.vector_count = 100
    mock_info.dimension = 384
    upstash_db.index.info.return_value = mock_info

    info = upstash_db.get_index_info()
    assert info.vector_count == 100
    assert info.dimension == 384
