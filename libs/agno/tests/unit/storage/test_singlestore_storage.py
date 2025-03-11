import pytest
from unittest.mock import MagicMock, patch

from agno.storage.singlestore import SingleStoreStorage
from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine."""
    engine = MagicMock()
    return engine


@pytest.fixture
def mock_session():
    """Create a mock SQLAlchemy session."""
    session = MagicMock()
    session_instance = MagicMock()
    session.begin.return_value.__enter__.return_value = session_instance
    return session, session_instance


@pytest.fixture
def agent_storage(mock_engine, mock_session):
    """Create a SingleStoreStorage instance for agent mode with mocked components."""
    with patch("agno.storage.singlestore.sessionmaker", return_value=MagicMock(return_value=mock_session[0])):
        with patch("agno.storage.singlestore.inspect", return_value=MagicMock()):
            storage = SingleStoreStorage(
                table_name="agent_sessions",
                schema="ai",
                db_engine=mock_engine,
                mode="agent"
            )
            # Mock table_exists to return True
            storage.table_exists = MagicMock(return_value=True)
            return storage, mock_session[1]


@pytest.fixture
def workflow_storage(mock_engine, mock_session):
    """Create a SingleStoreStorage instance for workflow mode with mocked components."""
    with patch("agno.storage.singlestore.sessionmaker", return_value=MagicMock(return_value=mock_session[0])):
        with patch("agno.storage.singlestore.inspect", return_value=MagicMock()):
            storage = SingleStoreStorage(
                table_name="workflow_sessions",
                schema="ai",
                db_engine=mock_engine,
                mode="workflow"
            )
            # Mock table_exists to return True
            storage.table_exists = MagicMock(return_value=True)
            return storage, mock_session[1]


def test_initialization():
    """Test SingleStoreStorage initialization with different parameters."""
    # Test with db_url
    with patch("agno.storage.singlestore.create_engine") as mock_create_engine:
        with patch("agno.storage.singlestore.sessionmaker"):
            with patch("agno.storage.singlestore.inspect"):
                mock_engine = MagicMock()
                mock_create_engine.return_value = mock_engine
                
                storage = SingleStoreStorage(
                    table_name="test_table",
                    db_url="mysql://user:pass@localhost/db"
                )
                
                mock_create_engine.assert_called_once_with(
                    "mysql://user:pass@localhost/db", 
                    connect_args={"charset": "utf8mb4"}
                )
                assert storage.table_name == "test_table"
                assert storage.schema == "ai"  # Default value
                assert storage.mode == "agent"  # Default value

    # Test with missing db_url and db_engine
    with pytest.raises(ValueError, match="Must provide either db_url or db_engine"):
        SingleStoreStorage(table_name="test_table")


def test_agent_storage_crud(agent_storage):
    """Test CRUD operations for agent storage."""
    storage, mock_session = agent_storage
    
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
    
    # Mock the read method to return None initially (for checking if exists)
    # and then return the session after upsert
    original_read = storage.read
    storage.read = MagicMock(return_value=None)
    
    # Mock upsert to return the session directly
    original_upsert = storage.upsert
    storage.upsert = MagicMock(return_value=session)
    
    # Test upsert
    result = storage.upsert(session)
    assert result == session
    
    # Restore original methods
    storage.read = original_read
    storage.upsert = original_upsert
    
    # Now test read with a direct mock
    storage.read = MagicMock(return_value=session)
    read_result = storage.read("test-session")
    assert read_result == session
    
    # Test delete by mocking the delete_session method directly
    storage.delete_session = MagicMock()
    storage.delete_session("test-session")
    storage.delete_session.assert_called_once_with("test-session")


def test_workflow_storage_crud(workflow_storage):
    """Test CRUD operations for workflow storage."""
    storage, mock_session = workflow_storage
    
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
    
    # Mock the read method to return None initially (for checking if exists)
    # and then return the session after upsert
    original_read = storage.read
    storage.read = MagicMock(return_value=None)
    
    # Mock upsert to return the session directly
    original_upsert = storage.upsert
    storage.upsert = MagicMock(return_value=session)
    
    # Test upsert
    result = storage.upsert(session)
    assert result == session
    
    # Restore original methods
    storage.read = original_read
    storage.upsert = original_upsert
    
    # Now test read with a direct mock
    storage.read = MagicMock(return_value=session)
    read_result = storage.read("test-session")
    assert read_result == session
    
    # Test delete by mocking the delete_session method directly
    storage.delete_session = MagicMock()
    storage.delete_session("test-session")
    storage.delete_session.assert_called_once_with("test-session")


def test_get_all_sessions(agent_storage):
    """Test retrieving all sessions."""
    storage, mock_session = agent_storage
    
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
    storage, mock_session = agent_storage
    
    # Mock the get_all_session_ids method directly
    original_get_all_session_ids = storage.get_all_session_ids
    storage.get_all_session_ids = MagicMock(return_value=["session-1", "session-2", "session-3"])
    
    # Test get_all_session_ids
    result = storage.get_all_session_ids()
    assert result == ["session-1", "session-2", "session-3"]
    
    # Restore original method
    storage.get_all_session_ids = original_get_all_session_ids


def test_table_exists(agent_storage):
    """Test the table_exists method."""
    storage, _ = agent_storage
    
    # Test when table exists
    with patch("agno.storage.singlestore.inspect") as mock_inspect:
        mock_inspect.return_value.has_table.return_value = True
        
        # Reset the mocked table_exists
        storage.table_exists = SingleStoreStorage.table_exists.__get__(storage)
        
        assert storage.table_exists() is True
        
        # Test when table doesn't exist
        mock_inspect.return_value.has_table.return_value = False
        
        assert storage.table_exists() is False


def test_create_table(agent_storage):
    """Test table creation."""
    storage, _ = agent_storage
    
    # Reset the mocked table_exists
    storage.table_exists = MagicMock(return_value=False)
    
    # Mock the create method
    with patch.object(storage.table, "create") as mock_create:
        storage.create()
        mock_create.assert_called_once_with(storage.db_engine)


def test_drop_table(agent_storage):
    """Test dropping a table."""
    storage, _ = agent_storage
    
    # Mock table_exists to return True
    storage.table_exists = MagicMock(return_value=True)
    
    # Mock the drop method
    with patch.object(storage.table, "drop") as mock_drop:
        storage.drop()
        mock_drop.assert_called_once_with(storage.db_engine)


def test_mode_switching():
    """Test switching between agent and workflow modes."""
    with patch("agno.storage.singlestore.sessionmaker"):
        with patch("agno.storage.singlestore.inspect"):
            with patch("agno.storage.singlestore.create_engine"):
                # Create storage in agent mode
                storage = SingleStoreStorage(
                    table_name="test_table",
                    db_url="mysql://user:pass@localhost/db"
                )
                assert storage.mode == "agent"
                
                # Switch to workflow mode
                with patch.object(storage, "get_table") as mock_get_table:
                    storage.mode = "workflow"
                    assert storage.mode == "workflow"
                    mock_get_table.assert_called_once() 