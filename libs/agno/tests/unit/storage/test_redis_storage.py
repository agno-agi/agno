from typing import Dict
from unittest.mock import ANY, MagicMock, patch

import pytest
import redis

from agno.storage.redis import RedisStorage
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession


@pytest.fixture
def mock_redis_client():
    """Mock Redis client with in-memory storage for testing."""
    with patch("agno.storage.redis.Redis") as mock_redis:
        # Create a mock Redis client
        client = MagicMock()

        # Create an in-memory store to simulate Redis
        mock_data: Dict[str, str] = {}

        # Mock Redis client methods
        client.get.side_effect = lambda key: mock_data.get(key)
        client.set.side_effect = lambda key, value: mock_data.update({key: value})

        # Make delete actually work correctly
        def mock_delete(key):
            if key in mock_data:
                del mock_data[key]
                return 1
            return 0

        client.delete.side_effect = mock_delete
        client.ping.return_value = True

        # Mock scan_iter to return keys
        client.scan_iter.side_effect = lambda match: [
            k for k in mock_data.keys() if k.startswith(match.replace("*", ""))
        ]

        # Return the mock Redis instance when Redis.Redis() is called
        mock_redis.return_value = client
        yield client


@pytest.fixture
def agent_storage(mock_redis_client):
    """Create agent storage with mock Redis client."""
    return RedisStorage(prefix="test_agent", mode="agent")


@pytest.fixture
def team_storage(mock_redis_client):
    """Create team storage with mock Redis client."""
    return RedisStorage(prefix="test_team", mode="team")


@pytest.fixture
def workflow_storage(mock_redis_client):
    """Create workflow storage with mock Redis client."""
    return RedisStorage(prefix="test_workflow", mode="workflow")


def test_create_connection(mock_redis_client):
    """Test that create() tests Redis connection."""
    storage = RedisStorage(prefix="test")
    storage.create()
    mock_redis_client.ping.assert_called_once()


def test_connection_error(mock_redis_client):
    """Test that create() raises exception on connection error."""
    mock_redis_client.ping.side_effect = redis.ConnectionError("Connection refused")
    storage = RedisStorage(prefix="test")

    with pytest.raises(redis.ConnectionError):
        storage.create()


def test_agent_storage_crud(agent_storage, mock_redis_client):
    """Test CRUD operations for agent storage."""
    # Test create
    agent_storage.create()

    # Test upsert
    session = AgentSession(
        session_id="test-session",
        agent_id="test-agent",
        user_id="test-user",
        memory={"key": "value"},
        agent_data={"name": "Test Agent"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
    )

    # Mock time.time() to return a fixed value
    with patch("time.time", return_value=12345):
        saved_session = agent_storage.upsert(session)
        assert saved_session is not None
        assert saved_session.session_id == session.session_id

        # Use ANY for the second parameter to ignore timestamp differences
        mock_redis_client.set.assert_called_with("test_agent:test-session", ANY)

    # Mock the get response with updated timestamps for consistency
    updated_data = session.__dict__.copy()
    updated_data["updated_at"] = 12345
    updated_data["created_at"] = 12345
    mock_redis_client.get.return_value = agent_storage.serialize(updated_data)

    # Test read
    read_session = agent_storage.read("test-session")
    assert read_session is not None
    assert read_session.session_id == session.session_id
    assert read_session.agent_id == session.agent_id
    assert read_session.memory == session.memory

    # Test get all sessions
    all_sessions = agent_storage.get_all_sessions()
    assert len(all_sessions) == 1
    assert all_sessions[0].session_id == session.session_id

    # Test delete
    agent_storage.delete_session("test-session")
    mock_redis_client.delete.assert_called_with("test_agent:test-session")


def test_workflow_storage_crud(workflow_storage, mock_redis_client):
    """Test CRUD operations for workflow storage."""
    # Test create
    workflow_storage.create()

    # Test upsert
    session = WorkflowSession(
        session_id="test-session",
        workflow_id="test-workflow",
        user_id="test-user",
        memory={"key": "value"},
        workflow_data={"name": "Test Workflow"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
    )

    # Mock time.time() to return a fixed value
    with patch("time.time", return_value=12345):
        saved_session = workflow_storage.upsert(session)
        assert saved_session is not None
        assert saved_session.session_id == session.session_id

        # Use ANY for the second parameter to ignore timestamp differences
        mock_redis_client.set.assert_called_with("test_workflow:test-session", ANY)

    # Mock the get response
    updated_data = session.__dict__.copy()
    updated_data["updated_at"] = 12345
    updated_data["created_at"] = 12345
    mock_redis_client.get.return_value = workflow_storage.serialize(updated_data)

    # Test read
    read_session = workflow_storage.read("test-session")
    assert read_session is not None
    assert read_session.session_id == session.session_id
    assert read_session.workflow_id == session.workflow_id
    assert read_session.memory == session.memory


def test_storage_filtering(agent_storage, mock_redis_client):
    """Test session filtering in agent storage."""
    # Create test sessions
    sessions = [
        AgentSession(
            session_id=f"session-{i}",
            agent_id="agent-1" if i < 2 else "agent-2",
            user_id="user-1" if i % 2 == 0 else "user-2",
            memory={},
            agent_data={},
            session_data={},
            extra_data={},
        )
        for i in range(4)
    ]

    # Manually add the serialized data to our mock_redis_client
    for i, session in enumerate(sessions):
        key = f"test_agent:session-{i}"
        serialized_data = agent_storage.serialize(session.__dict__)
        mock_redis_client.set(key, serialized_data)

    # Test filtering by user_id
    user1_sessions = agent_storage.get_all_sessions(user_id="user-1")
    assert len(user1_sessions) == 2
    assert all(s.user_id == "user-1" for s in user1_sessions)

    # Test filtering by agent_id
    agent1_sessions = agent_storage.get_all_sessions(entity_id="agent-1")
    assert len(agent1_sessions) == 2
    assert all(s.agent_id == "agent-1" for s in agent1_sessions)

    # Test combined filtering
    filtered_sessions = agent_storage.get_all_sessions(user_id="user-1", entity_id="agent-1")
    assert len(filtered_sessions) == 1
    assert filtered_sessions[0].user_id == "user-1"
    assert filtered_sessions[0].agent_id == "agent-1"


def test_team_storage_operations(team_storage, mock_redis_client):
    """Test team storage operations."""
    # Test upsert
    session = TeamSession(
        session_id="team-session",
        team_id="test-team",
        user_id="test-user",
        team_session_id=None,
        memory={"key": "value"},
        team_data={"name": "Test Team"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
    )

    saved_session = team_storage.upsert(session)
    assert saved_session is not None
    assert saved_session.session_id == session.session_id

    # Mock the get response
    mock_redis_client.get.return_value = team_storage.serialize(session.__dict__)

    # Test read with user_id filter
    read_session = team_storage.read("team-session", user_id="test-user")
    assert read_session is not None
    assert read_session.session_id == session.session_id

    # Test read with wrong user_id filter (should return None)
    read_session = team_storage.read("team-session", user_id="wrong-user")
    assert read_session is None


def test_drop_all_sessions(agent_storage, mock_redis_client):
    """Test dropping all sessions."""
    # Add some test data first
    mock_redis_client.set("test_agent:session-1", "{}")
    mock_redis_client.set("test_agent:session-2", "{}")

    # Verify keys were added
    assert mock_redis_client.get("test_agent:session-1") == "{}"
    assert mock_redis_client.get("test_agent:session-2") == "{}"

    # Call drop (this should delete all keys with the prefix)
    agent_storage.drop()

    # Verify keys were deleted
    assert mock_redis_client.delete.call_count >= 2
    mock_redis_client.delete.assert_any_call("test_agent:session-1")
    mock_redis_client.delete.assert_any_call("test_agent:session-2")


def test_upgrade_schema(agent_storage):
    """Test schema upgrade is a no-op for Redis."""
    # This should not raise any errors
    agent_storage.upgrade_schema()


def test_key_generation(agent_storage):
    """Test key generation."""
    key = agent_storage._get_key("test-id")
    assert key == "test_agent:test-id"


def test_serialization(agent_storage):
    """Test serialization and deserialization."""
    data = {"key": "value", "nested": {"inner": "value"}}
    serialized = agent_storage.serialize(data)
    deserialized = agent_storage.deserialize(serialized)
    assert deserialized == data


def test_error_handling(agent_storage, mock_redis_client):
    """Test error handling during operations."""
    # Make Redis client raise an exception
    mock_redis_client.get.side_effect = Exception("Test error")

    # Read should handle error and return None
    result = agent_storage.read("test-session")
    assert result is None

    # Get all sessions should handle error and return empty list
    mock_redis_client.scan_iter.side_effect = Exception("Test error")
    result = agent_storage.get_all_sessions()
    assert result == []

    # Get all session IDs should handle error and return empty list
    result = agent_storage.get_all_session_ids()
    assert result == []

    # Upsert should handle error and return None
    mock_redis_client.set.side_effect = Exception("Test error")
    session = AgentSession(session_id="test-id", agent_id="test-agent", user_id="test-user")
    result = agent_storage.upsert(session)
    assert result is None

    # Delete should handle error without raising
    mock_redis_client.delete.side_effect = Exception("Test error")
    agent_storage.delete_session("test-id")  # Should not raise

    # Drop should handle error without raising
    mock_redis_client.scan_iter.side_effect = Exception("Test error")
    agent_storage.drop()  # Should not raise


def test_get_all_session_ids(agent_storage, mock_redis_client):
    """Test getting all session IDs."""
    # Create test sessions
    sessions = [
        AgentSession(
            session_id=f"session-{i}",
            agent_id="agent-1" if i < 2 else "agent-2",
            user_id="user-1" if i % 2 == 0 else "user-2",
            memory={},
            agent_data={},
            session_data={},
            extra_data={},
        )
        for i in range(4)
    ]

    # Manually add the serialized data to our mock_redis_client
    for i, session in enumerate(sessions):
        key = f"test_agent:session-{i}"
        serialized_data = agent_storage.serialize(session.__dict__)
        mock_redis_client.set(key, serialized_data)

    # Test getting all session IDs
    session_ids = agent_storage.get_all_session_ids()
    assert len(session_ids) == 4
    assert all(f"session-{i}" in session_ids for i in range(4))

    # Test filtering by user_id
    user1_session_ids = agent_storage.get_all_session_ids(user_id="user-1")
    assert len(user1_session_ids) == 2

    # Test filtering by agent_id
    agent1_session_ids = agent_storage.get_all_session_ids(entity_id="agent-1")
    assert len(agent1_session_ids) == 2

    # Test combined filtering
    filtered_session_ids = agent_storage.get_all_session_ids(user_id="user-1", entity_id="agent-1")
    assert len(filtered_session_ids) == 1
