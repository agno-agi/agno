import time
import uuid
from typing import Generator

import pytest
from cassandra.cluster import Cluster, Session

from agno.document import Document


@pytest.fixture(scope="session")
def cassandra_session() -> Generator[Session, None, None]:
    """Create a session-scoped connection to Cassandra."""
    # Wait for Cassandra to be ready
    max_retries = 5
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            cluster = Cluster(["localhost"], port=9042)
            session = cluster.connect()
            print(f"Successfully connected to Cassandra on attempt {attempt + 1}")
            break
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(retry_delay)

    # Create test keyspace
    keyspace = "test_vectordb"
    session.execute(f"""
        CREATE KEYSPACE IF NOT EXISTS {keyspace}
        WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': '1'}}
    """)
    session.set_keyspace(keyspace)

    yield session

    # Cleanup after all tests
    session.execute(f"DROP KEYSPACE IF EXISTS {keyspace}")
    cluster.shutdown()


@pytest.fixture
def vector_db(cassandra_session, mock_embedder):
    """Create a fresh VectorDB instance for each test."""
    from agno.vectordb.cassandra import Cassandra

    table_name = f"test_vectors_{uuid.uuid4().hex[:8]}"
    db = Cassandra(table_name=table_name, keyspace="test_vectordb", embedder=mock_embedder, session=cassandra_session)
    db.create()

    assert db.exists(), "Table was not created successfully"

    yield db

    # Cleanup after each test
    db.drop()


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


def test_initialization(cassandra_session):
    """Test VectorDB initialization."""
    from agno.vectordb.cassandra import Cassandra

    # Test successful initialization
    db = Cassandra(table_name="test_vectors", keyspace="test_vectordb", session=cassandra_session)
    assert db.table_name == "test_vectors"
    assert db.keyspace == "test_vectordb"

    # Test initialization failures
    with pytest.raises(ValueError):
        Cassandra(table_name="", keyspace="test_vectordb", session=cassandra_session)

    with pytest.raises(ValueError):
        Cassandra(table_name="test_vectors", keyspace="", session=cassandra_session)

    with pytest.raises(ValueError):
        Cassandra(table_name="test_vectors", keyspace="test_vectordb", session=None)


def test_insert_and_search(vector_db):
    """Test document insertion and search functionality."""
    # Insert test documents
    docs = create_test_documents(1)
    vector_db.insert(docs)

    time.sleep(1)

    # Test search functionality
    results = vector_db.search("test document", limit=1)
    assert len(results) == 1
    assert all(isinstance(doc, Document) for doc in results)

    # Test vector search
    results = vector_db.vector_search("test document 1", limit=2)


def test_document_existence(vector_db):
    """Test document existence checking methods."""
    docs = create_test_documents(1)
    vector_db.insert(docs)

    # Test by document object
    assert vector_db.doc_exists(docs[0]) is True

    # Test by name
    assert vector_db.name_exists("test_doc_0") is True
    assert vector_db.name_exists("nonexistent") is False

    # Test by ID
    assert vector_db.id_exists("doc_0") is True
    assert vector_db.id_exists("nonexistent") is False


def test_upsert(vector_db):
    """Test upsert functionality."""
    # Initial insert
    docs = create_test_documents(1)
    vector_db.insert(docs)

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


def test_delete_and_drop(vector_db):
    """Test delete and drop functionality."""
    # Insert documents
    docs = create_test_documents()
    vector_db.insert(docs)

    # Test delete
    assert vector_db.delete() is True
    results = vector_db.search("test document", limit=5)
    assert len(results) == 0

    # Test drop
    vector_db.drop()
    assert vector_db.exists() is False


def test_exists(vector_db):
    """Test table existence checking."""
    assert vector_db.exists() is True
    vector_db.drop()
    assert vector_db.exists() is False
