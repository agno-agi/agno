import uuid
from unittest.mock import MagicMock, patch

import pytest
from cassandra.cluster import Session

from agno.document import Document
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
    vector_db.insert(docs)

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
    vector_db.insert(docs)

    # Configure mock responses
    mock_session.execute.return_value.one.return_value = [1]  # Document exists

    # Test by document object
    assert vector_db.doc_exists(docs[0]) is True

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
    vector_db.insert(docs)
    assert mock_table.put_async.called

    # Modify document and upsert
    modified_doc = Document(
        id=docs[0].id, content="Modified content", meta_data={"type": "modified"}, name=docs[0].name
    )
    vector_db.upsert([modified_doc])

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
async def test_async_doc_exists(vector_db, mock_session):
    """Test async document existence checking."""
    doc = create_test_documents(1)[0]

    # Configure mock for existing document
    mock_session.execute.return_value.one.return_value = [1]  # Document exists
    exists = await vector_db.async_doc_exists(doc)
    assert exists is True

    # Configure mock for non-existent document
    mock_session.execute.return_value.one.return_value = [0]  # Document doesn't exist
    exists = await vector_db.async_doc_exists(doc)
    assert exists is False


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
    await vector_db.async_insert(docs)
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
    await vector_db.async_upsert(docs)
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
    # Configure mock for existing table
    mock_session.execute.return_value.one.return_value = True
    exists = await vector_db.async_exists()
    assert exists is True

    # Configure mock for non-existent table
    mock_session.execute.return_value.one.return_value = None
    exists = await vector_db.async_exists()
    assert exists is False
