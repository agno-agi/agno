import uuid
from hashlib import md5
from unittest.mock import MagicMock, patch

import pytest
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from agno.document import Document
from agno.vectordb.mongodb import MongoDb


@pytest.fixture(scope="session")
def mock_mongodb_client():
    """Create a mock MongoDB client."""
    with patch("pymongo.MongoClient") as mock_client:
        # Create mock instances for client, db, and collection
        mock_collection = MagicMock(spec=Collection)
        mock_db = MagicMock(spec=Database)
        mock_client_instance = MagicMock(spec=MongoClient)

        # Setup the mock chain
        mock_client.return_value = mock_client_instance
        mock_client_instance.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_collection
        mock_db.list_collection_names = MagicMock(return_value=["test_vectors"])

        # Setup common collection methods
        mock_collection.create_search_index = MagicMock(return_value=None)
        mock_collection.list_search_indexes = MagicMock(return_value=[{"name": "vector_index_1"}])
        mock_collection.drop_search_index = MagicMock(return_value=None)
        mock_collection.aggregate = MagicMock(return_value=[])
        mock_collection.insert_one = MagicMock(return_value=MagicMock(inserted_id="test_id"))
        mock_collection.find_one = MagicMock(return_value=None)
        mock_collection.delete_many = MagicMock(return_value=MagicMock(deleted_count=1))
        mock_collection.drop = MagicMock()

        yield mock_client_instance


@pytest.fixture(scope="session")
def vector_db(mock_mongodb_client, mock_embedder):
    """Create a fresh VectorDB instance for each test."""
    collection_name = f"test_vectors_{uuid.uuid4().hex[:8]}"
    db = MongoDb(
        collection_name=collection_name,
        embedder=mock_embedder,
        client=mock_mongodb_client,
        database="test_vectordb",
    )
    db.create()
    yield db
    # Cleanup
    try:
        db._client.close()
    except Exception as e:
        raise Exception(f"Failed to close MongoDB client: {e}")


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


def test_initialization(mock_mongodb_client):
    """Test MongoDB VectorDB initialization."""
    # Test successful initialization
    db = MongoDb(
        collection_name="test_vectors",
        database="test_vectordb",
        client=mock_mongodb_client,
    )
    assert db.collection_name == "test_vectors"
    assert db.database == "test_vectordb"

    # Test initialization failures for empty collection_name
    with pytest.raises(ValueError):
        MongoDb(collection_name="", database="test_vectordb", client=mock_mongodb_client)

    # Test initialization failures for empty database name
    with pytest.raises(ValueError):
        MongoDb(collection_name="test_vectors", database="", client=mock_mongodb_client)


def test_insert_and_search(vector_db, mock_mongodb_client):
    """Test document insertion and search functionality."""
    # Setup mock response for search
    mock_search_result = [
        {
            "_id": "doc_0",
            "content": "This is test document 0",
            "meta_data": {"type": "test", "index": "0"},
            "name": "test_doc_0",
            "score": 0.95,
            "embedding": [0.1] * 384,  # Add mock embedding
        }
    ]

    collection = mock_mongodb_client["test_vectordb"]["test_vectors"]
    collection.aggregate.return_value = mock_search_result

    # Insert test documents
    docs = create_test_documents(1)
    vector_db.insert(docs)

    # Test search functionality
    results = vector_db.search("test document", limit=1)
    assert len(results) == 1
    assert all(isinstance(doc, Document) for doc in results)
    assert results[0].id == "doc_0"

    # Verify the search pipeline was called correctly
    args = collection.aggregate.call_args[0][0]
    assert isinstance(args, list)
    assert args[0]["$vectorSearch"]["limit"] == 1


def test_document_existence(vector_db, mock_mongodb_client):
    """Test document existence checking methods."""
    collection = mock_mongodb_client["test_vectordb"]["test_vectors"]

    # Create test documents
    docs = create_test_documents(1)
    vector_db.insert(docs)

    # Setup mock responses for find_one
    def mock_find_one(query):
        # For doc_exists
        if "_id" in query and query["_id"] == md5(docs[0].content.encode("utf-8")).hexdigest():
            return {"_id": "doc_0", "content": "This is test document 0", "name": "test_doc_0"}
        # For name_exists
        if "name" in query and query["name"] == "test_doc_0":
            return {"_id": "doc_0", "content": "This is test document 0", "name": "test_doc_0"}
        # For id_exists
        if "_id" in query and query["_id"] == "doc_0":
            return {"_id": "doc_0", "content": "This is test document 0", "name": "test_doc_0"}
        return None

    collection.find_one.side_effect = mock_find_one

    # Test by document object
    assert vector_db.doc_exists(docs[0])

    # Test by name
    assert vector_db.name_exists("test_doc_0")
    assert not vector_db.name_exists("nonexistent")

    # Test by ID
    assert vector_db.id_exists("doc_0")
    assert not vector_db.id_exists("nonexistent")


def test_upsert(vector_db, mock_mongodb_client):
    """Test upsert functionality."""
    collection = mock_mongodb_client["test_vectordb"]["test_vectors"]

    # Setup mock responses
    mock_doc = {"_id": "doc_0", "content": "Modified content", "name": "test_doc_0", "meta_data": {"type": "modified"}}
    collection.find_one.return_value = mock_doc
    collection.update_one = MagicMock(return_value=MagicMock(modified_count=1))

    # Initial insert
    docs = create_test_documents(1)
    vector_db.insert(docs)

    # Modify document and upsert
    modified_doc = Document(
        id=docs[0].id, content="Modified content", meta_data={"type": "modified"}, name=docs[0].name
    )
    vector_db.upsert([modified_doc])

    # Verify the update was called
    collection.update_one.assert_called_once()


def test_delete(vector_db, mock_mongodb_client):
    """Test delete functionality."""
    collection = mock_mongodb_client["test_vectordb"]["test_vectors"]
    collection.delete_many = MagicMock(return_value=MagicMock(deleted_count=3))
    collection.drop = MagicMock()

    # Insert documents
    docs = create_test_documents()
    vector_db.insert(docs)

    # Test delete
    assert vector_db.delete() is True


def test_exists(vector_db, mock_mongodb_client):
    """Test collection existence checking."""
    db = mock_mongodb_client["test_vectordb"]

    # Setup mock responses for collection existence
    db.list_collection_names.return_value = ["test_vectors"]

    # Force collection name to match mock response
    vector_db.collection_name = "test_vectors"

    assert vector_db.exists() is True

    # Test non-existent collection
    db.list_collection_names.return_value = []
    assert vector_db.exists() is False


def test_search_with_filters(vector_db, mock_mongodb_client):
    """Test search functionality with filters."""
    collection = mock_mongodb_client["test_vectordb"]["test_vectors"]

    # Setup mock response for filtered search
    mock_search_result = [
        {
            "_id": "doc_0",
            "content": "This is test document 0",
            "meta_data": {"type": "test", "index": "0"},
            "name": "test_doc_0",
            "score": 0.95,
        }
    ]
    collection.aggregate.return_value = mock_search_result

    # Test search with filters
    filters = {"meta_data.type": "test"}
    results = vector_db.search("test document", limit=1, filters=filters)

    # Verify results
    assert len(results) == 1
    assert results[0].meta_data["type"] == "test"

    # Verify the search pipeline included filters
    args = collection.aggregate.call_args[0][0]
    assert any("$match" in stage for stage in args)
