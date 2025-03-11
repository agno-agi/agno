from unittest.mock import MagicMock, patch

import pytest

from agno.storage.mongodb import MongoDbStorage
from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession


@pytest.fixture
def mock_mongo_client():
    """Create a mock MongoDB client."""
    with patch("agno.storage.mongodb.MongoClient") as mock_client:
        mock_collection = MagicMock()
        mock_client.return_value.__getitem__.return_value.__getitem__.return_value = mock_collection
        yield mock_client, mock_collection


@pytest.fixture
def agent_storage(mock_mongo_client):
    """Create a MongoDbStorage instance for agent mode with mocked components."""
    mock_client, mock_collection = mock_mongo_client

    storage = MongoDbStorage(collection_name="agent_sessions", db_name="test_db", mode="agent")

    return storage, mock_collection


@pytest.fixture
def workflow_storage(mock_mongo_client):
    """Create a MongoDbStorage instance for workflow mode with mocked components."""
    mock_client, mock_collection = mock_mongo_client

    storage = MongoDbStorage(collection_name="workflow_sessions", db_name="test_db", mode="workflow")

    return storage, mock_collection


def test_initialization():
    """Test MongoDbStorage initialization with different parameters."""
    # Test with db_url
    with patch("agno.storage.mongodb.MongoClient") as mock_client:
        mock_collection = MagicMock()
        mock_client.return_value.__getitem__.return_value.__getitem__.return_value = mock_collection

        storage = MongoDbStorage(
            collection_name="test_collection", db_url="mongodb://localhost:27017", db_name="test_db"
        )

        mock_client.assert_called_once_with("mongodb://localhost:27017")
        assert storage.collection_name == "test_collection"
        assert storage.db_name == "test_db"
        assert storage.mode == "agent"  # Default value

    # Test with existing client
    with patch("agno.storage.mongodb.MongoClient") as mock_client:
        mock_existing_client = MagicMock()
        mock_collection = MagicMock()
        mock_existing_client.__getitem__.return_value.__getitem__.return_value = mock_collection

        storage = MongoDbStorage(collection_name="test_collection", db_name="test_db", client=mock_existing_client)

        mock_client.assert_not_called()  # Should not create a new client
        assert storage.collection_name == "test_collection"
        assert storage.db_name == "test_db"

    # Test with no parameters
    with patch("agno.storage.mongodb.MongoClient") as mock_client:
        mock_collection = MagicMock()
        mock_client.return_value.__getitem__.return_value.__getitem__.return_value = mock_collection

        storage = MongoDbStorage(collection_name="test_collection")

        mock_client.assert_called_once()  # Should create a default client
        assert storage.collection_name == "test_collection"
        assert storage.db_name == "agno"  # Default value


def test_create_indexes(agent_storage):
    """Test creating indexes."""
    storage, mock_collection = agent_storage

    # Mock create_index
    mock_collection.create_index = MagicMock()

    # Call create
    storage.create()

    # Verify create_index was called for each index
    assert mock_collection.create_index.call_count >= 4  # At least 4 indexes

    # Verify agent_id index is created in agent mode
    mock_collection.create_index.assert_any_call("agent_id")

    # Test in workflow mode
    storage.mode = "workflow"
    mock_collection.create_index.reset_mock()

    storage.create()

    # Verify workflow_id index is created in workflow mode
    mock_collection.create_index.assert_any_call("workflow_id")


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

    # Mock find_one for read
    mock_collection.find_one.return_value = {**session.to_dict(), "_id": "mock_id"}

    # Test read
    read_result = storage.read("test-session")
    assert read_result is not None
    assert read_result.session_id == session.session_id

    # Mock update_one for upsert
    mock_collection.update_one.return_value = MagicMock(acknowledged=True)

    # Mock the read method for upsert
    original_read = storage.read
    storage.read = MagicMock(return_value=session)

    # Test upsert
    result = storage.upsert(session)
    assert result == session
    mock_collection.update_one.assert_called_once()

    # Restore original read method
    storage.read = original_read

    # Test delete
    storage.delete_session = MagicMock()
    storage.delete_session("test-session")
    storage.delete_session.assert_called_once_with("test-session")


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

    # Mock find_one for read
    mock_collection.find_one.return_value = {**session.to_dict(), "_id": "mock_id"}

    # Test read
    read_result = storage.read("test-session")
    assert read_result is not None
    assert read_result.session_id == session.session_id

    # Mock update_one for upsert
    mock_collection.update_one.return_value = MagicMock(acknowledged=True)

    # Mock the read method for upsert
    original_read = storage.read
    storage.read = MagicMock(return_value=session)

    # Test upsert
    result = storage.upsert(session)
    assert result == session
    mock_collection.update_one.assert_called_once()

    # Restore original read method
    storage.read = original_read

    # Test delete
    storage.delete_session = MagicMock()
    storage.delete_session("test-session")
    storage.delete_session.assert_called_once_with("test-session")


def test_get_all_sessions(agent_storage):
    """Test retrieving all sessions."""
    storage, mock_collection = agent_storage

    # Create mock sessions
    sessions = [
        AgentSession(
            session_id=f"session-{i}",
            agent_id=f"agent-{i % 2 + 1}",
            user_id=f"user-{i % 2 + 1}",
        )
        for i in range(4)
    ]

    # Mock the get_all_sessions method directly
    original_get_all_sessions = storage.get_all_sessions
    storage.get_all_sessions = MagicMock(return_value=sessions)

    # Test get_all_sessions
    result = storage.get_all_sessions()
    assert len(result) == 4

    # Test filtering by user_id
    user1_sessions = [s for s in sessions if s.user_id == "user-1"]
    storage.get_all_sessions = MagicMock(return_value=user1_sessions)

    result = storage.get_all_sessions(user_id="user-1")
    assert len(result) == 2
    assert all(s.user_id == "user-1" for s in result)

    # Test filtering by agent_id
    agent1_sessions = [s for s in sessions if s.agent_id == "agent-1"]
    storage.get_all_sessions = MagicMock(return_value=agent1_sessions)

    result = storage.get_all_sessions(entity_id="agent-1")
    assert len(result) == 2
    assert all(s.agent_id == "agent-1" for s in result)

    # Restore original method
    storage.get_all_sessions = original_get_all_sessions


def test_get_all_session_ids(agent_storage):
    """Test retrieving all session IDs."""
    storage, mock_collection = agent_storage

    # Mock the find method to return session IDs
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = [
        {"session_id": "session-1"},
        {"session_id": "session-2"},
        {"session_id": "session-3"},
    ]
    mock_collection.find.return_value = mock_cursor

    # Test get_all_session_ids without filters
    result = storage.get_all_session_ids()
    assert result == ["session-1", "session-2", "session-3"]
    mock_collection.find.assert_called_once_with({}, {"session_id": 1})

    # Test with user_id filter
    mock_collection.find.reset_mock()
    mock_cursor.sort.return_value = [{"session_id": "session-1"}, {"session_id": "session-2"}]
    mock_collection.find.return_value = mock_cursor

    result = storage.get_all_session_ids(user_id="test-user")
    assert result == ["session-1", "session-2"]
    mock_collection.find.assert_called_once_with({"user_id": "test-user"}, {"session_id": 1})

    # Test with entity_id filter (agent_id in agent mode)
    mock_collection.find.reset_mock()
    mock_cursor.sort.return_value = [{"session_id": "session-3"}]
    mock_collection.find.return_value = mock_cursor

    result = storage.get_all_session_ids(entity_id="test-agent")
    assert result == ["session-3"]
    mock_collection.find.assert_called_once_with({"agent_id": "test-agent"}, {"session_id": 1})


def test_drop_collection(agent_storage):
    """Test dropping a collection."""
    storage, mock_collection = agent_storage

    # Mock the drop method
    mock_collection.drop = MagicMock()

    # Call drop
    storage.drop()

    # Verify drop was called
    mock_collection.drop.assert_called_once()


def test_mode_switching():
    """Test switching between agent and workflow modes."""
    with patch("agno.storage.mongodb.MongoClient") as mock_client:
        mock_collection = MagicMock()
        mock_client.return_value.__getitem__.return_value.__getitem__.return_value = mock_collection

        # Create storage in agent mode
        storage = MongoDbStorage(collection_name="test_collection")
        assert storage.mode == "agent"

        # Switch to workflow mode
        storage.mode = "workflow"
        assert storage.mode == "workflow"


def test_deepcopy(agent_storage):
    """Test deep copying the storage instance."""
    from copy import deepcopy

    storage, _ = agent_storage

    # Deep copy the storage
    copied_storage = deepcopy(storage)

    # Verify the copy has the same attributes
    assert copied_storage.collection_name == storage.collection_name
    assert copied_storage.db_name == storage.db_name
    assert copied_storage.mode == storage.mode

    # Verify the copy shares the same client, db, and collection references
    assert copied_storage._client is storage._client
    assert copied_storage.db is storage.db
    assert copied_storage.collection is storage.collection
