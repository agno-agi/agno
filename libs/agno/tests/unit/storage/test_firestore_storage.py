from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from agno.storage.firestore import FirestoreStorage
from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession


@pytest.fixture
def mock_firestore_client():
    """Create a mock Firestore client."""
    with patch("agno.storage.firestore.Client") as mock_client:
        # Create mock collection
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection
        mock_client.return_value = mock_db

        # Mock the client's collections() method for authentication test
        mock_client.return_value.collections.return_value = []

        yield mock_client, mock_collection


@pytest.fixture
def agent_storage(mock_firestore_client):
    """Create a FirestoreStorage instance for agent mode with mocked components."""
    mock_client, mock_collection = mock_firestore_client

    storage = FirestoreStorage(
        collection_name="agent_sessions", db_name="(default)", project_id="test-project", mode="agent"
    )

    return storage, mock_collection


@pytest.fixture
def workflow_storage(mock_firestore_client):
    """Create a FirestoreStorage instance for workflow mode with mocked components."""
    mock_client, mock_collection = mock_firestore_client

    storage = FirestoreStorage(
        collection_name="workflow_sessions", db_name="(default)", project_id="test-project", mode="workflow"
    )

    return storage, mock_collection


def test_initialization():
    """Test FirestoreStorage initialization with different parameters."""
    # Test with project_id
    with patch("agno.storage.firestore.Client") as mock_client:
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection
        mock_client.return_value = mock_db

        storage = FirestoreStorage(collection_name="test_collection", db_name="test-db", project_id="test-project")

        mock_client.assert_called_once_with(database="test-db", project="test-project")
        assert storage.collection_name == "test_collection"
        assert storage.db_name == "test-db"
        assert storage.mode == "agent"  # Default value

    # Test with existing client
    with patch("agno.storage.firestore.Client") as mock_client:
        mock_existing_client = MagicMock()
        mock_collection = MagicMock()
        mock_existing_client.collection.return_value = mock_collection

        storage = FirestoreStorage(collection_name="test_collection", client=mock_existing_client)

        mock_client.assert_not_called()  # Should not create a new client
        assert storage.collection_name == "test_collection"
        assert storage.db_name == "(default)"  # Default value

    # Test with environment variable
    with patch("agno.storage.firestore.Client") as mock_client:
        with patch("os.getenv", return_value="env-project"):
            mock_collection = MagicMock()
            mock_db = MagicMock()
            mock_db.collection.return_value = mock_collection
            mock_client.return_value = mock_db

            storage = FirestoreStorage(collection_name="test_collection")

            # Note: FirestoreStorage doesn't use os.getenv, so project will be None
            mock_client.assert_called_once_with(database="(default)", project=None)


def test_authentication_error():
    """Test handling of authentication errors."""
    with patch("agno.storage.firestore.Client") as mock_client:
        from google.api_core import exceptions as google_exceptions

        # Mock authentication error during Client initialization
        mock_client.side_effect = google_exceptions.Unauthenticated("Not authenticated")

        with pytest.raises(ImportError, match="Failed to authenticate with Google Cloud"):
            FirestoreStorage(collection_name="test_collection")


def test_agent_storage_crud(agent_storage):
    """Test CRUD operations for agent storage."""
    storage, mock_collection = agent_storage

    # Create a test session
    session = AgentSession(
        session_id="test-session",
        agent_id="test-agent",
        user_id="test-user",
        memory={"key": "value"},
        agent_data={"name": "Test Agent"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
    )

    # Mock query and document for read
    mock_query = MagicMock()
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {**session.to_dict(), "created_at": 1234567890, "updated_at": 1234567890}
    mock_query.get.return_value = [mock_doc]
    # Make where() chainable - it returns itself
    mock_query.where.return_value = mock_query
    mock_collection.where.return_value = mock_query

    # Test read operations - all inside with block to keep FieldFilter mocked
    with patch("agno.storage.firestore.FieldFilter") as mock_field_filter:
        mock_field_filter.return_value = MagicMock()

        # Test basic read
        read_result = storage.read("test-session")
        assert read_result is not None
        assert read_result.session_id == session.session_id

        # Test read with user_id filter
        read_result = storage.read("test-session", user_id="test-user")
        assert read_result is not None

        # Test read with wrong user_id - return empty list
        mock_query.get.return_value = []
        read_result = storage.read("test-session", user_id="wrong-user")
        assert read_result is None

    # Test upsert
    mock_doc_ref = MagicMock()
    mock_doc_snapshot = MagicMock()
    mock_doc_snapshot.exists = False
    mock_doc_ref.get.return_value = mock_doc_snapshot
    mock_collection.document.return_value = mock_doc_ref

    # Mock the read method to return the session after upsert
    with patch.object(storage, "read", return_value=session):
        result = storage.upsert(session)
        assert result == session
        mock_doc_ref.set.assert_called_once()

    # Test delete
    storage.delete_session("test-session")
    mock_doc_ref.delete.assert_called_once()


def test_workflow_storage_crud(workflow_storage):
    """Test CRUD operations for workflow storage."""
    storage, mock_collection = workflow_storage

    # Create a test session
    session = WorkflowSession(
        session_id="test-session",
        workflow_id="test-workflow",
        user_id="test-user",
        memory={"key": "value"},
        workflow_data={"name": "Test Workflow"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
    )

    # Mock query and document for read
    mock_query = MagicMock()
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {**session.to_dict(), "created_at": 1234567890, "updated_at": 1234567890}
    mock_query.get.return_value = [mock_doc]
    mock_collection.where.return_value = mock_query

    # Test read
    with patch("agno.storage.firestore.FieldFilter") as mock_field_filter:
        mock_field_filter.return_value = MagicMock()
        read_result = storage.read("test-session")
        assert read_result is not None
        assert read_result.session_id == session.session_id
        assert read_result.workflow_id == session.workflow_id

    # Test upsert
    mock_doc_ref = MagicMock()
    mock_doc_snapshot = MagicMock()
    mock_doc_snapshot.exists = False
    mock_doc_ref.get.return_value = mock_doc_snapshot
    mock_collection.document.return_value = mock_doc_ref

    with patch.object(storage, "read", return_value=session):
        result = storage.upsert(session)
        assert result == session

    # Test delete
    storage.delete_session("test-session")
    mock_doc_ref.delete.assert_called_once()


def test_get_all_sessions(agent_storage):
    """Test retrieving all sessions."""
    storage, mock_collection = agent_storage

    # Create mock sessions
    sessions = [
        {
            "session_id": f"session-{i}",
            "agent_id": f"agent-{i % 2 + 1}",
            "user_id": f"user-{i % 2 + 1}",
            "created_at": 1234567890 + i,
            "updated_at": 1234567890 + i,
            "memory": {},
            "agent_data": {},
            "session_data": {},
        }
        for i in range(4)
    ]

    # Create mock document objects
    mock_docs = []
    for session_data in sessions:
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = session_data
        mock_docs.append(mock_doc)

    # Mock collection.get() to return all docs
    mock_collection.get.return_value = mock_docs

    # Test get_all_sessions without filters
    result = storage.get_all_sessions()
    assert len(result) == 4

    # Test filtering by user_id
    with patch("agno.storage.firestore.FieldFilter") as mock_field_filter:
        mock_field_filter.return_value = MagicMock()
        mock_query = MagicMock()
        user1_docs = [d for d in mock_docs if d.to_dict()["user_id"] == "user-1"]
        mock_query.get.return_value = user1_docs
        mock_collection.where.return_value = mock_query

        result = storage.get_all_sessions(user_id="user-1")
        assert len(result) == 2
        assert all(s.user_id == "user-1" for s in result)

    # Test filtering by agent_id
    agent1_docs = [d for d in mock_docs if d.to_dict()["agent_id"] == "agent-1"]
    mock_query.get.return_value = agent1_docs

    result = storage.get_all_sessions(entity_id="agent-1")
    assert len(result) == 2
    assert all(s.agent_id == "agent-1" for s in result)


def test_get_all_session_ids(agent_storage):
    """Test retrieving all session IDs."""
    storage, mock_collection = agent_storage

    # Create mock documents
    mock_docs = []
    for i in range(3):
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = {"created_at": 1234567890 + i, "session_id": f"session-{i}"}
        mock_docs.append(mock_doc)

    # Mock collection.get() to return all docs
    mock_collection.get.return_value = mock_docs

    # Test get_all_session_ids without filters
    result = storage.get_all_session_ids()
    # Should be sorted by created_at descending
    assert result == ["session-2", "session-1", "session-0"]

    # Test with user_id filter
    with patch("agno.storage.firestore.FieldFilter") as mock_field_filter:
        mock_field_filter.return_value = MagicMock()
        mock_query = MagicMock()
        user_docs = mock_docs[:2]
        mock_query.get.return_value = user_docs
        mock_collection.where.return_value = mock_query

        result = storage.get_all_session_ids(user_id="test-user")
        assert result == ["session-1", "session-0"]


def test_get_recent_sessions(agent_storage):
    """Test retrieving recent sessions."""
    storage, mock_collection = agent_storage

    # Create mock sessions
    sessions = []
    for i in range(5):
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = {
            "session_id": f"session-{i}",
            "agent_id": "test-agent",
            "user_id": f"user-{i % 2}",
            "created_at": 1234567890 + i,
            "updated_at": 1234567890 + i,
            "memory": {},
            "agent_data": {},
            "session_data": {},
        }
        sessions.append(mock_doc)

    # Mock collection.get() to return all docs
    mock_collection.get.return_value = sessions

    # Test get_recent_sessions (default limit=2)
    result = storage.get_recent_sessions()
    assert len(result) == 2
    # Should get the most recent ones
    assert result[0].session_id == "session-4"
    assert result[1].session_id == "session-3"

    # Test with user_id filter
    with patch("agno.storage.firestore.FieldFilter") as mock_field_filter:
        mock_field_filter.return_value = MagicMock()
        mock_query = MagicMock()
        user_sessions = [s for s in sessions if s.to_dict()["user_id"] == "user-0"]
        mock_query.get.return_value = user_sessions
        mock_collection.where.return_value = mock_query

        result = storage.get_recent_sessions(user_id="user-0", limit=3)
        assert all(s.user_id == "user-0" for s in result)


def test_drop_collection(agent_storage):
    """Test dropping a collection."""
    storage, mock_collection = agent_storage

    # Create mock documents
    mock_docs = []
    for i in range(3):
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = f"doc-{i}"
        mock_doc_ref.delete = MagicMock()
        mock_doc_ref.collections.return_value = []  # No subcollections
        mock_docs.append(mock_doc_ref)

    mock_collection.list_documents.return_value = mock_docs

    # Call drop
    storage.drop()

    # Verify all documents were deleted
    for doc in mock_docs:
        doc.delete.assert_called_once()


def test_recursive_deletion(agent_storage):
    """Test recursive deletion of documents with subcollections."""
    storage, _ = agent_storage

    # Create mock document with subcollection
    mock_doc_ref = MagicMock()
    mock_subcollection = MagicMock()
    mock_subdoc_ref = MagicMock()

    # Setup subcollection structure
    mock_doc_ref.collections.return_value = [mock_subcollection]
    mock_subcollection.list_documents.return_value = [mock_subdoc_ref]
    mock_subdoc_ref.collections.return_value = []

    # Call delete document
    storage._delete_document(mock_doc_ref)

    # Verify both document and subdocument were deleted
    mock_subdoc_ref.delete.assert_called_once()
    mock_doc_ref.delete.assert_called_once()


def test_deepcopy(agent_storage):
    """Test deep copying the storage instance."""
    storage, _ = agent_storage

    # Deep copy the storage
    copied_storage = deepcopy(storage)

    # Verify the copy has the same attributes
    assert copied_storage.collection_name == storage.collection_name
    assert copied_storage.db_name == storage.db_name
    assert copied_storage.mode == storage.mode
    assert copied_storage.project_id == storage.project_id

    # Note: In the current implementation, deepcopy creates a new client
    # This is different from MongoDB/other implementations
    assert copied_storage._client is not storage._client


def test_mode_switching():
    """Test switching between agent, workflow, and team modes."""
    with patch("agno.storage.firestore.Client") as mock_client:
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection
        mock_client.return_value = mock_db

        # Create storage in agent mode
        storage = FirestoreStorage(collection_name="test_collection")
        assert storage.mode == "agent"

        # Switch to workflow mode
        storage.mode = "workflow"
        assert storage.mode == "workflow"

        # Switch to team mode
        storage.mode = "team"
        assert storage.mode == "team"


def test_error_handling(agent_storage):
    """Test error handling in various operations."""
    storage, mock_collection = agent_storage

    # Test read with non-existent document
    mock_query = MagicMock()
    mock_query.get.return_value = []  # No documents found
    mock_collection.where.return_value = mock_query

    with patch("agno.storage.firestore.FieldFilter") as mock_field_filter:
        mock_field_filter.return_value = MagicMock()
        result = storage.read("non-existent")
        assert result is None

    # Test exception handling in get_all_sessions
    mock_collection.get.side_effect = Exception("Firestore error")

    result = storage.get_all_sessions()
    assert result == []  # Should return empty list on error

    # Test exception handling in upsert
    mock_collection.get.side_effect = None
    mock_doc_ref = MagicMock()
    mock_doc_ref.set.side_effect = Exception("Firestore error")
    mock_collection.document.return_value = mock_doc_ref

    result = storage.upsert(AgentSession(session_id="test", agent_id="test"))
    assert result is None  # Should return None on error
