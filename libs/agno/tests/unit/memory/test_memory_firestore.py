"""Unit tests for FirestoreMemoryDb."""

from unittest.mock import MagicMock, patch

import pytest

from agno.memory.v2.db.firestore import FirestoreMemoryDb
from agno.memory.v2.db.schema import MemoryRow


@pytest.fixture
def mock_firestore_client():
    """Create a mock Firestore client."""
    with patch("agno.memory.v2.db.firestore.Client") as mock_client:
        # Create mock collection and client
        mock_root_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_root_collection
        mock_client.return_value = mock_db

        # Mock the collections() method for authentication test
        mock_client.return_value.collections.return_value = []

        yield mock_client, mock_root_collection, mock_db


@pytest.fixture
def memory_db(mock_firestore_client):
    """Create a FirestoreMemoryDb instance with mocked components."""
    mock_client, mock_root_collection, mock_db = mock_firestore_client

    db = FirestoreMemoryDb(collection_name="test_memory", db_name="(default)", project_id="test-project")

    # Replace the mocked db on the client
    db._client = mock_db

    return db, mock_root_collection, mock_db


def test_initialization():
    """Test FirestoreMemoryDb initialization."""
    with patch("agno.memory.v2.db.firestore.Client") as mock_client:
        mock_db = MagicMock()
        mock_db.collection.return_value = MagicMock()
        mock_client.return_value = mock_db

        # Test with project_id
        db = FirestoreMemoryDb(collection_name="test_memory", db_name="test-db", project_id="test-project")

        mock_client.assert_called_once_with(database="test-db", project="test-project")
        assert db.collection_name == "test_memory"
        assert db.db_name == "test-db"
        assert db.project_id == "test-project"


def test_authentication_error():
    """Test handling of authentication errors."""
    with patch("agno.memory.v2.db.firestore.Client") as mock_client:
        from google.api_core import exceptions as google_exceptions

        # Mock authentication error
        mock_client.side_effect = google_exceptions.Unauthenticated("Not authenticated")

        with pytest.raises(ImportError, match="Failed to authenticate with Google Cloud"):
            FirestoreMemoryDb(collection_name="test_memory")


def test_get_user_collection(memory_db):
    """Test getting user-specific collection."""
    db, mock_root_collection, mock_client = memory_db

    # Mock the collection method
    mock_user_collection = MagicMock()
    mock_client.collection.return_value = mock_user_collection

    # Get user collection
    user_collection = db.get_user_collection("test-user")

    assert user_collection == mock_user_collection
    mock_client.collection.assert_called_with("test_memory/test-user/memories")


def test_read_memories(memory_db):
    """Test reading memories."""
    db, mock_root_collection, mock_client = memory_db

    # Mock user collection
    mock_user_collection = MagicMock()
    mock_client.collection.return_value = mock_user_collection

    # Mock query and documents
    mock_query = MagicMock()
    mock_doc1 = MagicMock()
    mock_doc1.to_dict.return_value = {
        "id": "mem1",
        "user_id": "test-user",
        "memory": {"text": "memory 1"},
        "created_at": 1234567890,
        "updated_at": 1234567890,
    }
    mock_doc2 = MagicMock()
    mock_doc2.to_dict.return_value = {
        "id": "mem2",
        "user_id": "test-user",
        "memory": {"text": "memory 2"},
        "created_at": 1234567891,
        "updated_at": 1234567891,
    }

    mock_query.stream.return_value = [mock_doc1, mock_doc2]
    mock_query.limit.return_value = mock_query
    mock_user_collection.order_by.return_value = mock_query

    # Test read with user_id
    memories = db.read_memories(user_id="test-user", limit=10)

    assert len(memories) == 2
    assert memories[0].id == "mem1"
    assert memories[0].memory == {"text": "memory 1"}
    assert memories[1].id == "mem2"

    # Test read without user_id (should return empty)
    memories = db.read_memories(user_id=None)
    assert len(memories) == 0


def test_upsert_memory(memory_db):
    """Test upserting a memory."""
    db, mock_root_collection, mock_client = memory_db

    # Mock user collection and document reference
    mock_user_collection = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_snapshot = MagicMock()
    mock_doc_snapshot.exists = False
    mock_doc_ref.get.return_value = mock_doc_snapshot

    mock_user_collection.document.return_value = mock_doc_ref
    mock_client.collection.return_value = mock_user_collection

    # Mock transaction
    mock_transaction = MagicMock()
    mock_client.transaction.return_value = mock_transaction

    # Create a memory
    memory = MemoryRow(id="test-memory", user_id="test-user", memory={"text": "test memory"})

    # Test upsert - just verify it doesn't raise an error
    # The transactional decorator makes this complex to mock perfectly
    result = db.upsert_memory(memory)

    # Should complete without error
    assert result is None  # upsert_memory returns None
    assert mock_doc_ref.get.called

    # Test upsert without user_id (should skip)
    memory_no_user = MemoryRow(id="test-memory2", memory={"text": "test memory"})
    db.upsert_memory(memory_no_user)
    # Should return early without error


def test_memory_exists(memory_db):
    """Test checking if memory exists."""
    db, mock_root_collection, mock_client = memory_db

    # Mock user collection and document
    mock_user_collection = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_snapshot = MagicMock()

    mock_user_collection.document.return_value = mock_doc_ref
    mock_doc_ref.get.return_value = mock_doc_snapshot
    mock_client.collection.return_value = mock_user_collection

    memory = MemoryRow(id="test-memory", user_id="test-user", memory={"text": "test"})

    # Test when exists
    mock_doc_snapshot.exists = True
    assert db.memory_exists(memory) is True

    # Test when doesn't exist
    mock_doc_snapshot.exists = False
    assert db.memory_exists(memory) is False

    # Test without user_id
    memory_no_user = MemoryRow(id="test", memory={})
    assert db.memory_exists(memory_no_user) is False


def test_delete_memory(memory_db):
    """Test deleting a memory."""
    db, mock_root_collection, mock_client = memory_db

    # Set user_id on the db instance
    db._user_id = "test-user"

    # Mock user collection
    mock_user_collection = MagicMock()
    mock_doc_ref = MagicMock()
    mock_user_collection.document.return_value = mock_doc_ref
    mock_client.collection.return_value = mock_user_collection

    # Delete memory
    db.delete_memory("test-memory-id")

    mock_doc_ref.delete.assert_called_once()


def test_clear(memory_db):
    """Test clearing all memories."""
    db, mock_root_collection, _ = memory_db

    # Mock documents
    mock_docs = []
    for i in range(3):
        mock_doc_ref = MagicMock()
        mock_doc_ref.collections.return_value = []  # No subcollections
        mock_docs.append(mock_doc_ref)

    mock_root_collection.list_documents.return_value = mock_docs

    # Clear all memories
    result = db.clear()

    assert result is True
    for doc in mock_docs:
        doc.delete.assert_called_once()


def test_table_exists(memory_db):
    """Test checking if collection exists."""
    db, mock_root_collection, _ = memory_db

    # Mock stream to check existence
    mock_root_collection.limit.return_value.stream.return_value = [MagicMock()]

    assert db.table_exists() is True

    # Test when exception occurs
    mock_root_collection.limit.return_value.stream.side_effect = Exception("Error")

    assert db.table_exists() is False


def test_recursive_deletion(memory_db):
    """Test recursive deletion of documents with subcollections."""
    db, _, _ = memory_db

    # Create mock document with subcollection
    mock_doc_ref = MagicMock()
    mock_subcollection = MagicMock()
    mock_subdoc_ref = MagicMock()

    # Setup subcollection structure
    mock_doc_ref.collections.return_value = [mock_subcollection]
    mock_subcollection.list_documents.return_value = [mock_subdoc_ref]
    mock_subdoc_ref.collections.return_value = []

    # Delete document
    db._delete_document(mock_doc_ref)

    # Verify both document and subdocument were deleted
    mock_subdoc_ref.delete.assert_called_once()
    mock_doc_ref.delete.assert_called_once()


def test_error_handling(memory_db):
    """Test error handling in various operations."""
    db, _, mock_client = memory_db

    # Test read_memories with exception
    mock_client.collection.side_effect = Exception("Firestore error")

    memories = db.read_memories(user_id="test-user")
    assert memories == []

    # Test upsert_memory with exception
    memory = MemoryRow(id="test", user_id="test-user", memory={"text": "test"})

    # Should raise the exception
    with pytest.raises(Exception):
        db.upsert_memory(memory)

    # Test clear with exception
    mock_client.collection.side_effect = None
    db.collection.list_documents.side_effect = Exception("Error")

    result = db.clear()
    assert result is False
