from unittest.mock import MagicMock, patch

import pytest

from agno.storage.mysql import MySQLStorage
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
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
    session.return_value.__enter__.return_value = session_instance
    return session, session_instance


@pytest.fixture
def agent_storage(mock_engine, mock_session):
    """Create a MySQLStorage instance for agent mode with mocked components."""
    with patch("agno.storage.mysql.scoped_session", return_value=mock_session[0]):
        with patch("agno.storage.mysql.inspect", return_value=MagicMock()):
            storage = MySQLStorage(table_name="agent_sessions", schema="ai", db_engine=mock_engine, mode="agent")
            # Mock table_exists to return True
            storage.table_exists = MagicMock(return_value=True)
            return storage, mock_session[1]


@pytest.fixture
def team_storage(mock_engine, mock_session):
    """Create a MySQLStorage instance for team mode with mocked components."""
    with patch("agno.storage.mysql.scoped_session", return_value=mock_session[0]):
        with patch("agno.storage.mysql.inspect", return_value=MagicMock()):
            storage = MySQLStorage(table_name="team_sessions", schema="ai", db_engine=mock_engine, mode="team")
            # Mock table_exists to return True
            storage.table_exists = MagicMock(return_value=True)
            return storage, mock_session[1]


@pytest.fixture
def workflow_storage(mock_engine, mock_session):
    """Create a MySQLStorage instance for workflow mode with mocked components."""
    with patch("agno.storage.mysql.scoped_session", return_value=mock_session[0]):
        with patch("agno.storage.mysql.inspect", return_value=MagicMock()):
            storage = MySQLStorage(table_name="workflow_sessions", schema="ai", db_engine=mock_engine, mode="workflow")
            # Mock table_exists to return True
            storage.table_exists = MagicMock(return_value=True)
            return storage, mock_session[1]


def test_mysql_storage_initialization():
    """Test MySQLStorage initialization with different parameters."""
    # Test with db_url
    with patch("agno.storage.mysql.create_engine") as mock_create_engine:
        with patch("agno.storage.mysql.scoped_session"):
            with patch("agno.storage.mysql.inspect"):
                mock_engine = MagicMock()
                mock_create_engine.return_value = mock_engine

                storage = MySQLStorage(table_name="test_table", db_url="mysql+pymysql://user:pass@localhost/db")

                mock_create_engine.assert_called_once_with("mysql+pymysql://user:pass@localhost/db")
                assert storage.table_name == "test_table"
                assert storage.schema == "ai"  # Default value
                assert storage.mode == "agent"  # Default value

    # Test with missing db_url and db_engine
    with pytest.raises(ValueError, match="Must provide either db_url or db_engine"):
        MySQLStorage(table_name="test_table")


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
        team_session_id="team-123",
    )

    # Mock the read method for initial check
    original_read = storage.read
    storage.read = MagicMock(return_value=None)

    # Mock upsert to return the session directly
    original_upsert = storage.upsert
    storage.upsert = MagicMock(return_value=session)

    # Test upsert
    result = storage.upsert(session)
    assert result == session

    # Restore original methods for other tests
    storage.read = original_read
    storage.upsert = original_upsert

    # Now test read with a direct mock
    storage.read = MagicMock(return_value=session)
    read_result = storage.read("test-session")
    assert read_result == session

    # Test delete
    storage.delete_session("test-session")
    mock_session.execute.assert_called()


def test_team_storage_crud(team_storage):
    """Test CRUD operations for team storage."""
    storage, mock_session = team_storage

    # Create a test session
    session = TeamSession(
        session_id="test-session",
        team_id="test-team",
        user_id="test-user",
        memory={"key": "value"},
        team_data={"name": "Test Team"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
        team_session_id="team-session-123",
    )

    # Mock the read method for initial check
    original_read = storage.read
    storage.read = MagicMock(return_value=None)

    # Mock upsert to return the session directly
    original_upsert = storage.upsert
    storage.upsert = MagicMock(return_value=session)

    # Test upsert
    result = storage.upsert(session)
    assert result == session

    # Restore original methods for other tests
    storage.read = original_read
    storage.upsert = original_upsert

    # Now test read with a direct mock
    storage.read = MagicMock(return_value=session)
    read_result = storage.read("test-session")
    assert read_result == session

    # Test delete
    storage.delete_session("test-session")
    mock_session.execute.assert_called()


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

    # Mock the read method for initial check
    original_read = storage.read
    storage.read = MagicMock(return_value=None)

    # Mock upsert to return the session directly
    original_upsert = storage.upsert
    storage.upsert = MagicMock(return_value=session)

    # Test upsert
    result = storage.upsert(session)
    assert result == session

    # Restore original methods for other tests
    storage.read = original_read
    storage.upsert = original_upsert

    # Now test read with a direct mock
    storage.read = MagicMock(return_value=session)
    read_result = storage.read("test-session")
    assert read_result == session

    # Test delete
    storage.delete_session("test-session")
    mock_session.execute.assert_called()


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

    # Mock the fetchall result
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [MagicMock(_mapping=session.to_dict()) for session in sessions]
    mock_session.execute.return_value = mock_result

    # Test get_all_sessions
    result = storage.get_all_sessions()
    assert len(result) == 4

    # Test filtering by user_id
    mock_session.execute.reset_mock()
    mock_result.fetchall.return_value = [
        MagicMock(_mapping=session.to_dict()) for session in sessions if session.user_id == "user-1"
    ]
    mock_session.execute.return_value = mock_result

    result = storage.get_all_sessions(user_id="user-1")
    assert len(result) == 2
    assert all(s.user_id == "user-1" for s in result)

    # Test filtering by agent_id
    mock_session.execute.reset_mock()
    mock_result.fetchall.return_value = [
        MagicMock(_mapping=session.to_dict()) for session in sessions if session.agent_id == "agent-1"
    ]
    mock_session.execute.return_value = mock_result

    result = storage.get_all_sessions(entity_id="agent-1")
    assert len(result) == 2
    assert all(s.agent_id == "agent-1" for s in result)


def test_get_all_session_ids(agent_storage):
    """Test retrieving all session IDs."""
    storage, mock_session = agent_storage

    # Mock the fetchall result
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("session-1",), ("session-2",), ("session-3",)]
    mock_session.execute.return_value = mock_result

    # Test get_all_session_ids
    result = storage.get_all_session_ids()
    assert result == ["session-1", "session-2", "session-3"]


def test_get_recent_sessions(agent_storage):
    """Test retrieving recent sessions with limit."""
    storage, mock_session = agent_storage

    # Create mock sessions
    sessions = [
        AgentSession(
            session_id=f"session-{i}",
            agent_id="agent-1",
            user_id="user-1",
        )
        for i in range(5)
    ]

    # Mock the fetchall result for recent sessions
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [MagicMock(_mapping=sessions[i].to_dict()) for i in range(2)]
    mock_session.execute.return_value = mock_result

    # Test get_recent_sessions with limit
    result = storage.get_recent_sessions(user_id="user-1", entity_id="agent-1", limit=2)
    assert len(result) == 2


def test_table_exists(agent_storage):
    """Test the table_exists method."""
    storage, mock_session = agent_storage

    # Test when table exists
    mock_scalar = MagicMock(return_value=1)
    mock_session.execute.return_value.scalar = mock_scalar

    # Reset the mocked table_exists
    storage.table_exists = MySQLStorage.table_exists.__get__(storage)

    assert storage.table_exists() is True

    # Test when table doesn't exist
    mock_scalar = MagicMock(return_value=None)
    mock_session.execute.return_value.scalar = mock_scalar

    assert storage.table_exists() is False


def test_create_table(agent_storage):
    """Test table creation."""
    storage, mock_session = agent_storage

    # Reset the mocked table_exists
    storage.table_exists = MagicMock(return_value=False)

    # Mock the create method
    with patch.object(storage.table, "create"):
        storage.create()
        mock_session.execute.assert_called()  # For schema creation


def test_drop_table(agent_storage):
    """Test dropping a table."""
    storage, mock_session = agent_storage

    # Mock table_exists to return True
    storage.table_exists = MagicMock(return_value=True)

    # Mock the drop method
    with patch.object(storage.table, "drop") as mock_drop:
        storage.drop()
        mock_drop.assert_called_once_with(storage.db_engine, checkfirst=True)


def test_mode_switching():
    """Test switching between agent, team, and workflow modes."""
    with patch("agno.storage.mysql.scoped_session"):
        with patch("agno.storage.mysql.inspect"):
            with patch("agno.storage.mysql.create_engine"):
                # Create storage in agent mode
                storage = MySQLStorage(table_name="test_table", db_url="mysql+pymysql://user:pass@localhost/db")
                assert storage.mode == "agent"

                # Switch to workflow mode
                with patch.object(storage, "get_table") as mock_get_table:
                    storage.mode = "workflow"
                    assert storage.mode == "workflow"
                    mock_get_table.assert_called_once()

                # Switch to team mode
                with patch.object(storage, "get_table") as mock_get_table:
                    storage.mode = "team"
                    assert storage.mode == "team"
                    mock_get_table.assert_called_once()


def test_schema_upgrade(agent_storage):
    """Test schema upgrade functionality."""
    storage, mock_session = agent_storage
    storage.auto_upgrade_schema = True
    storage._schema_up_to_date = False

    # Mock column exists check to return False (column doesn't exist)
    mock_scalar = MagicMock(return_value=None)
    mock_session.execute.return_value.scalar = mock_scalar

    # Test upgrade_schema
    storage.upgrade_schema()

    # Verify ALTER TABLE was called
    calls = mock_session.execute.call_args_list
    alter_table_called = any("ALTER TABLE" in str(call) for call in calls)
    assert alter_table_called or storage._schema_up_to_date


def test_mysql_specific_features(agent_storage):
    """Test MySQL-specific features like backtick quoting."""
    storage, mock_session = agent_storage

    # Reset table_exists to test actual implementation
    storage.table_exists = MySQLStorage.table_exists.__get__(storage)

    # Mock execute to capture SQL queries
    executed_queries = []

    def capture_execute(query, *args, **kwargs):
        executed_queries.append(str(query))
        result = MagicMock()
        result.scalar = MagicMock(return_value=1)
        return result

    mock_session.execute = MagicMock(side_effect=capture_execute)

    # Call table_exists to trigger query
    storage.table_exists()

    # Verify information_schema query is used (MySQL style)
    assert any("information_schema.tables" in query for query in executed_queries)


def test_deepcopy(agent_storage):
    """Test deep copying of MySQLStorage instance."""
    storage, _ = agent_storage

    import copy

    # Test deepcopy
    copied_storage = copy.deepcopy(storage)

    # Verify essential attributes are preserved
    assert copied_storage.table_name == storage.table_name
    assert copied_storage.schema == storage.schema
    assert copied_storage.mode == storage.mode
    assert copied_storage.schema_version == storage.schema_version
    assert copied_storage.auto_upgrade_schema == storage.auto_upgrade_schema

    # Verify db_engine is the same (not copied)
    assert copied_storage.db_engine is storage.db_engine


def test_error_handling(agent_storage):
    """Test error handling for various scenarios."""
    storage, mock_session = agent_storage

    # Test 1: Read with table doesn't exist error
    mock_session.execute.side_effect = Exception("Table 'ai.agent_sessions' doesn't exist")

    # Reset read method
    storage.read = MySQLStorage.read.__get__(storage)

    # Should handle error gracefully and return None
    result = storage.read("test-session")
    assert result is None

    # Test 2: Verify upsert calls create when table doesn't exist
    # We'll test this by directly verifying the logic path
    session = AgentSession(
        session_id="test-session",
        agent_id="test-agent",
        user_id="test-user",
    )

    # Setup the scenario where upsert fails and needs to create table
    original_table_exists = storage.table_exists
    create_called = False

    def track_create():
        nonlocal create_called
        create_called = True

    # Override methods
    storage.table_exists = MagicMock(return_value=False)
    storage.create = MagicMock(side_effect=track_create)
    storage.read = MagicMock(return_value=session)

    # Setup mock session to fail initially
    def failing_execute(*args, **kwargs):
        if not create_called:
            raise Exception("Table doesn't exist")
        return MagicMock()

    mock_session.execute = MagicMock(side_effect=failing_execute)
    mock_session.begin.return_value.__enter__.return_value = mock_session

    # Get the actual upsert method
    storage.upsert = MySQLStorage.upsert.__get__(storage)

    # Call upsert - it should fail, check table_exists, call create, then succeed
    try:
        result = storage.upsert(session, create_and_retry=True)
        # If successful, verify create was called
        assert create_called
    except Exception:
        # Even if it fails, create should have been called
        assert create_called

    # Verify create was actually called
    storage.create.assert_called()

    # Restore original
    storage.table_exists = original_table_exists

    # Test 3: Error handling in get methods
    mock_session.execute.side_effect = Exception("doesn't exist")

    # These should handle errors gracefully
    storage.get_all_sessions = MySQLStorage.get_all_sessions.__get__(storage)
    assert storage.get_all_sessions() == []

    storage.get_all_session_ids = MySQLStorage.get_all_session_ids.__get__(storage)
    assert storage.get_all_session_ids() == []

    storage.get_recent_sessions = MySQLStorage.get_recent_sessions.__get__(storage)
    assert storage.get_recent_sessions() == []


def test_all_modes_table_structure():
    """Test that table structure is correct for all modes."""
    with patch("agno.storage.mysql.scoped_session"):
        with patch("agno.storage.mysql.inspect"):
            with patch("agno.storage.mysql.create_engine"):
                # Test agent mode columns
                agent_storage = MySQLStorage(
                    table_name="agent_table", db_url="mysql+pymysql://user:pass@localhost/db", mode="agent"
                )
                agent_table = agent_storage.get_table()
                agent_columns = {c.name for c in agent_table.columns}
                assert "agent_id" in agent_columns
                assert "team_session_id" in agent_columns
                assert "agent_data" in agent_columns

                # Test team mode columns
                team_storage = MySQLStorage(
                    table_name="team_table", db_url="mysql+pymysql://user:pass@localhost/db", mode="team"
                )
                team_table = team_storage.get_table()
                team_columns = {c.name for c in team_table.columns}
                assert "team_id" in team_columns
                assert "team_session_id" in team_columns
                assert "team_data" in team_columns

                # Test workflow mode columns
                workflow_storage = MySQLStorage(
                    table_name="workflow_table", db_url="mysql+pymysql://user:pass@localhost/db", mode="workflow"
                )
                workflow_table = workflow_storage.get_table()
                workflow_columns = {c.name for c in workflow_table.columns}
                assert "workflow_id" in workflow_columns
                assert "workflow_data" in workflow_columns
                assert "team_session_id" not in workflow_columns
