import uuid
from unittest.mock import MagicMock, patch

import pytest
from cassandra.cluster import Session

from agno.knowledge.document import Document
from agno.vectordb.cassandra import Cassandra
from agno.vectordb.cassandra.index import AgnoMetadataVectorCassandraTable


@pytest.fixture
def mock_session():
    """Create a mocked Cassandra session."""
    session = MagicMock(spec=Session)

    # Mock common session operations
    session.execute.return_value = MagicMock()
    session.execute.return_value.one.return_value = [1]  # For count queries

    return session


@pytest.fixture
def mock_table():
    """Create a mock table with all necessary methods."""
    mock_table = MagicMock()
    mock_table.metric_ann_search = MagicMock(return_value=[])
    mock_table.put_async = MagicMock()
    mock_table.put_async.return_value = MagicMock()
    mock_table.put_async.return_value.result = MagicMock(return_value=None)
    mock_table.clear = MagicMock()
    return mock_table


@pytest.fixture
def vector_db(mock_session, mock_embedder, mock_table):
    """Create a VectorDB instance with mocked session and table."""
    table_name = f"test_vectors_{uuid.uuid4().hex[:8]}"

    with patch.object(AgnoMetadataVectorCassandraTable, "__new__", return_value=mock_table):
        db = Cassandra(table_name=table_name, keyspace="test_vectordb", embedder=mock_embedder, session=mock_session)
        db.create()

        # Verify the mock table was properly set
        assert hasattr(db, "table")
        assert isinstance(db.table, MagicMock)

        yield db


def create_test_documents(num_docs: int = 3) -> list[Document]:
    """Helper function to create test documents."""
    return [
        Document(
            id=f"doc_{i}",
            content=f"This is test document {i}",
            meta_data={"type": "test", "index": str(i)},
            name=f"test_doc_{i}",
        )
        for i in range(num_docs)
    ]


def test_initialization(mock_session):
    """Test VectorDB initialization."""
    # Test successful initialization
    db = Cassandra(table_name="test_vectors", keyspace="test_vectordb", session=mock_session)
    assert db.table_name == "test_vectors"
    assert db.keyspace == "test_vectordb"

    # Test initialization failures
    with pytest.raises(ValueError):
        Cassandra(table_name="", keyspace="test_vectordb", session=mock_session)

    with pytest.raises(ValueError):
        Cassandra(table_name="test_vectors", keyspace="", session=mock_session)

    with pytest.raises(ValueError):
        Cassandra(table_name="test_vectors", keyspace="test_vectordb", session=None)


def test_insert_and_search(vector_db, mock_table):
    """Test document insertion and search functionality."""
    docs = create_test_documents(1)

    # Configure mock for search results
    mock_hit = {
        "row_id": "doc_0",
        "body_blob": "This is test document 0",
        "metadata": {"type": "test", "index": "0"},
        "vector": [0.1] * 1024,
        "document_name": "test_doc_0",
    }
    mock_table.metric_ann_search.return_value = [mock_hit]

    # Test insert
    vector_db.insert(documents=docs, content_hash="test_content_hash")

    # Verify insert was called
    assert mock_table.put_async.called

    # Test search
    results = vector_db.search("test document", limit=1)
    assert len(results) == 1
    assert all(isinstance(doc, Document) for doc in results)
    assert mock_table.metric_ann_search.called

    # Test vector search
    results = vector_db.vector_search("test document 1", limit=1)
    assert len(results) == 1


def test_document_existence(vector_db, mock_session):
    """Test document existence checking methods."""
    docs = create_test_documents(1)
    vector_db.insert(documents=docs, content_hash="test_content_hash")

    # Configure mock responses
    mock_session.execute.return_value.one.return_value = [1]  # Document exists

    # Test by name
    assert vector_db.name_exists("test_doc_0") is True

    # Configure mock for non-existent document
    mock_session.execute.return_value.one.return_value = [0]
    assert vector_db.name_exists("nonexistent") is False

    # Reset mock for ID tests
    mock_session.execute.return_value.one.return_value = [1]
    assert vector_db.id_exists("doc_0") is True

    mock_session.execute.return_value.one.return_value = [0]
    assert vector_db.id_exists("nonexistent") is False


def test_upsert(vector_db, mock_table):
    """Test upsert functionality."""
    docs = create_test_documents(1)

    # Mock search result for verification
    mock_hit = {
        "row_id": "doc_0",
        "body_blob": "Modified content",
        "metadata": {"type": "modified"},
        "vector": [0.1] * 1024,
        "document_name": "test_doc_0",
    }
    mock_table.metric_ann_search.return_value = [mock_hit]

    # Initial insert
    vector_db.insert(documents=docs, content_hash="test_content_hash")
    assert mock_table.put_async.called

    # Modify document and upsert
    modified_doc = Document(
        id=docs[0].id, content="Modified content", meta_data={"type": "modified"}, name=docs[0].name
    )
    vector_db.upsert(documents=[modified_doc], content_hash="test_content_hash")

    # Verify modification
    results = vector_db.search("Modified content", limit=1)
    assert len(results) == 1
    assert results[0].content == "Modified content"
    assert results[0].meta_data["type"] == "modified"


def test_delete_and_drop(vector_db, mock_table, mock_session):
    """Test delete and drop functionality."""
    # Test delete
    assert vector_db.delete() is True
    assert mock_table.clear.called

    # Test drop
    vector_db.drop()
    mock_session.execute.assert_called_with(
        "DROP TABLE IF EXISTS test_vectordb.test_vectors_" + vector_db.table_name.split("_")[-1]
    )


def test_exists(vector_db, mock_session):
    """Test table existence checking."""
    mock_session.execute.return_value.one.return_value = True
    assert vector_db.exists() is True

    mock_session.execute.return_value.one.return_value = None
    assert vector_db.exists() is False


@pytest.mark.asyncio
async def test_async_create(vector_db, mock_session):
    """Test async table creation."""
    # Set up mock session return values
    mock_session.execute.return_value.one.return_value = None  # Table doesn't exist

    # Mock the initialize_table method to track if it was called
    with patch.object(vector_db, "initialize_table") as mock_initialize:
        # Test async create
        await vector_db.async_create()
        assert mock_initialize.called


@pytest.mark.asyncio
async def test_async_name_exists(vector_db, mock_session):
    """Test async name existence checking."""
    # Configure mock for existing name
    mock_session.execute.return_value.one.return_value = [1]  # Name exists
    exists = await vector_db.async_name_exists("test_doc_0")
    assert exists is True

    # Configure mock for non-existent name
    mock_session.execute.return_value.one.return_value = [0]  # Name doesn't exist
    exists = await vector_db.async_name_exists("nonexistent")
    assert exists is False


@pytest.mark.asyncio
async def test_async_insert_and_search(vector_db, mock_table):
    """Test async document insertion and search."""
    docs = create_test_documents(2)

    # Configure mock for search results
    mock_hit = {
        "row_id": "doc_0",
        "body_blob": "This is test document 0",
        "metadata": {"type": "test", "index": "0"},
        "vector": [0.1] * 1024,
        "document_name": "test_doc_0",
    }
    mock_table.metric_ann_search.return_value = [mock_hit]

    # Test async insert
    await vector_db.async_insert(documents=docs, content_hash="test_content_hash")
    assert mock_table.put_async.called

    # Test async search
    results = await vector_db.async_search("test document", limit=1)
    assert len(results) == 1
    assert all(isinstance(doc, Document) for doc in results)
    assert mock_table.metric_ann_search.called


@pytest.mark.asyncio
async def test_async_upsert(vector_db, mock_table):
    """Test async upsert functionality."""
    docs = create_test_documents(1)

    # Configure mock for search result
    mock_hit = {
        "row_id": "doc_0",
        "body_blob": "Updated content",
        "metadata": {"type": "updated"},
        "vector": [0.1] * 1024,
        "document_name": "test_doc_0",
    }
    mock_table.metric_ann_search.return_value = [mock_hit]

    # Test async upsert
    await vector_db.async_upsert(documents=docs, content_hash="test_content_hash")
    assert mock_table.put_async.called

    # Check results with async search
    results = await vector_db.async_search("test", limit=1)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_async_drop(vector_db, mock_session):
    """Test async drop functionality."""
    await vector_db.async_drop()
    mock_session.execute.assert_called_with(
        "DROP TABLE IF EXISTS test_vectordb.test_vectors_" + vector_db.table_name.split("_")[-1]
    )


@pytest.mark.asyncio
async def test_async_exists(vector_db, mock_session):
    """Test async exists functionality."""
    mock_session.execute.return_value.one.return_value = True
    result = await vector_db.async_exists()
    assert result is True


@pytest.fixture
def sample_documents() -> list[Document]:
    """Fixture to create sample documents for delete tests."""
    return [
        Document(
            content="Tom Kha Gai is a Thai coconut soup with chicken",
            meta_data={"cuisine": "Thai", "type": "soup"},
            name="tom_kha",
            content_id="recipe_1",
        ),
        Document(
            content="Pad Thai is a stir-fried rice noodle dish",
            meta_data={"cuisine": "Thai", "type": "noodles"},
            name="pad_thai",
            content_id="recipe_2",
        ),
        Document(
            content="Green curry is a spicy Thai curry with coconut milk",
            meta_data={"cuisine": "Thai", "type": "curry", "spicy": True},
            name="green_curry",
            content_id="recipe_3",
        ),
    ]


def test_delete_by_id(vector_db, mock_session, sample_documents):
    """Test deleting documents by ID."""
    # Mock id_exists method directly
    with patch.object(vector_db, "id_exists") as mock_id_exists:
        # Document exists, so deletion should succeed
        mock_id_exists.return_value = True

        # Test successful deletion
        result = vector_db.delete_by_id("doc_1")
        assert result is True

        # Verify the delete query was executed
        mock_session.execute.assert_called_with(
            f"DELETE FROM {vector_db.keyspace}.{vector_db.table_name} WHERE row_id = %s", ("doc_1",)
        )

        # Test deletion of non-existent document
        mock_id_exists.reset_mock()
        mock_id_exists.return_value = False  # Document doesn't exist
        result = vector_db.delete_by_id("nonexistent_id")
        assert result is False


def test_delete_by_name(vector_db, mock_session, sample_documents):
    """Test deleting documents by name."""
    # Mock name_exists to return True (document exists)
    with patch.object(vector_db, "name_exists") as mock_name_exists:
        mock_name_exists.return_value = True

        # Mock session.execute to return rows with matching names
        mock_rows = [
            MagicMock(row_id="doc_1", document_name="tom_kha"),
            MagicMock(row_id="doc_2", document_name="pad_thai"),
        ]

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter(mock_rows))
        mock_session.execute.return_value = mock_result

        # Test successful deletion
        result = vector_db.delete_by_name("tom_kha")
        assert result is True

        # Verify the SELECT query was executed to find matching documents
        mock_session.execute.assert_any_call(
            f"SELECT row_id, document_name FROM {vector_db.keyspace}.{vector_db.table_name} ALLOW FILTERING"
        )

        # Test deletion of non-existent name
        mock_name_exists.reset_mock()
        mock_name_exists.return_value = False  # Name doesn't exist
        result = vector_db.delete_by_name("nonexistent")
        assert result is False


def test_delete_by_metadata(vector_db, mock_session, sample_documents):
    """Test deleting documents by metadata."""
    # Mock session.execute to return rows with metadata
    mock_rows = [
        MagicMock(row_id="doc_1", metadata_s={"cuisine": "Thai", "type": "soup"}),
        MagicMock(row_id="doc_2", metadata_s={"cuisine": "Thai", "type": "noodles"}),
        MagicMock(row_id="doc_3", metadata_s={"cuisine": "Thai", "type": "curry", "spicy": True}),
    ]

    # Configure mock to return different results for different calls
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(mock_rows))
    mock_session.execute.return_value = mock_result

    # Test successful deletion
    result = vector_db.delete_by_metadata({"cuisine": "Thai", "type": "soup"})
    assert result is True

    # Verify the query was executed to find matching documents
    # The first call should be the SELECT query
    mock_session.execute.assert_any_call(
        f"SELECT row_id, metadata_s FROM {vector_db.keyspace}.{vector_db.table_name} ALLOW FILTERING"
    )

    # Test deletion with non-matching metadata
    mock_result.__iter__ = MagicMock(return_value=iter([]))
    result = vector_db.delete_by_metadata({"cuisine": "Italian"})
    assert result is False


def test_delete_by_content_id(vector_db, mock_session, sample_documents):
    """Test deleting documents by content ID."""
    # Mock session.execute to return rows with content_id in metadata
    mock_rows = [
        MagicMock(row_id="doc_1", metadata_s={"content_id": "recipe_1"}),
        MagicMock(row_id="doc_2", metadata_s={"content_id": "recipe_2"}),
    ]

    # Configure mock to return different results for different calls
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(mock_rows))
    mock_session.execute.return_value = mock_result

    # Test successful deletion
    result = vector_db.delete_by_content_id("recipe_1")
    assert result is True

    # Verify the query was executed to find matching documents
    # The first call should be the SELECT query
    mock_session.execute.assert_any_call(
        f"SELECT row_id, metadata_s FROM {vector_db.keyspace}.{vector_db.table_name} ALLOW FILTERING"
    )

    # Test deletion with non-existent content_id
    mock_result.__iter__ = MagicMock(return_value=iter([]))
    result = vector_db.delete_by_content_id("nonexistent_content_id")
    assert result is False


def test_delete_by_name_multiple_documents(vector_db, mock_session):
    """Test deleting multiple documents with the same name."""
    # Mock name_exists to return True (documents exist)
    with patch.object(vector_db, "name_exists") as mock_name_exists:
        mock_name_exists.return_value = True

        # Mock session.execute to return rows with matching names
        mock_rows = [
            MagicMock(row_id="doc_1", document_name="tom_kha"),
            MagicMock(row_id="doc_2", document_name="tom_kha"),
            MagicMock(row_id="doc_3", document_name="pad_thai"),
        ]

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter(mock_rows))
        mock_session.execute.return_value = mock_result

        # Test delete all documents with name "tom_kha"
        result = vector_db.delete_by_name("tom_kha")
        assert result is True

        # Verify the SELECT query was executed to find matching documents
        mock_session.execute.assert_any_call(
            f"SELECT row_id, document_name FROM {vector_db.keyspace}.{vector_db.table_name} ALLOW FILTERING"
        )


def test_delete_by_metadata_complex(vector_db, mock_session):
    """Test deleting documents with complex metadata matching."""
    # Mock session.execute to return rows with complex metadata
    mock_rows = [
        MagicMock(row_id="doc_1", metadata_s={"cuisine": "Thai", "type": "soup", "spicy": True}),
        MagicMock(row_id="doc_2", metadata_s={"cuisine": "Thai", "type": "noodles", "spicy": False}),
        MagicMock(row_id="doc_3", metadata_s={"cuisine": "Italian", "type": "pasta", "spicy": False}),
    ]

    # First call returns rows for query, subsequent calls are for deletion
    mock_session.execute.return_value = MagicMock()
    mock_session.execute.return_value.__iter__ = MagicMock(return_value=iter(mock_rows))

    # Test delete only spicy Thai dishes
    result = vector_db.delete_by_metadata({"cuisine": "Thai", "spicy": True})
    assert result is True

    # Test delete all non-spicy dishes
    mock_session.execute.return_value.__iter__ = MagicMock(return_value=iter(mock_rows[1:3]))  # Only non-spicy dishes
    result = vector_db.delete_by_metadata({"spicy": False})
    assert result is True


def test_delete_methods_error_handling(vector_db, mock_session):
    """Test error handling in delete methods."""
    # Mock session.execute to raise an exception
    mock_session.execute.side_effect = Exception("Database error")

    # Test all delete methods handle exceptions gracefully
    assert vector_db.delete_by_id("doc_1") is False
    assert vector_db.delete_by_name("test_name") is False
    assert vector_db.delete_by_metadata({"type": "test"}) is False
    assert vector_db.delete_by_content_id("test_content_id") is False


def test_metadata_matches_helper(vector_db):
    """Test the _metadata_matches helper method."""
    # Test exact match
    row_metadata = {"cuisine": "Thai", "type": "soup", "spicy": "True"}
    target_metadata = {"cuisine": "Thai", "type": "soup"}
    assert vector_db._metadata_matches(row_metadata, target_metadata) is True

    # Test partial match
    target_metadata = {"cuisine": "Thai"}
    assert vector_db._metadata_matches(row_metadata, target_metadata) is True

    # Test no match
    target_metadata = {"cuisine": "Italian"}
    assert vector_db._metadata_matches(row_metadata, target_metadata) is False

    # Test missing key
    target_metadata = {"cuisine": "Thai", "missing_key": "value"}
    assert vector_db._metadata_matches(row_metadata, target_metadata) is False

    # Test value mismatch
    target_metadata = {"cuisine": "Thai", "type": "curry"}
    assert vector_db._metadata_matches(row_metadata, target_metadata) is False
