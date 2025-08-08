import shutil

import pytest

from agno.agent import Agent
from agno.db.yaml import YamlStorage
from agno.session import AgentSession


@pytest.fixture
def temp_storage_path(tmp_path):
    """Create a temporary directory for storage that's cleaned up after tests."""
    storage_dir = tmp_path / "test_storage"
    storage_dir.mkdir()
    yield storage_dir
    shutil.rmtree(storage_dir)


@pytest.fixture
def shared_db(temp_storage_path):
    """Create a YamlStorage instance for agent sessions."""
    return YamlStorage(dir_path=temp_storage_path, mode="agent")


@pytest.fixture
def shared_db(temp_storage_path):
    """Create a YamlStorage instance for workflow sessions."""
    return YamlStorage(dir_path=temp_storage_path / "workflows", mode="workflow")


@pytest.fixture
def agent_with_storage(shared_db):
    """Create an agent with the test storage."""
    return Agent(storage=shared_db, add_history_to_context=True)


def test_storage_creation(temp_storage_path):
    """Test that storage directory is created."""
    YamlStorage(dir_path=temp_storage_path)
    assert temp_storage_path.exists()
    assert temp_storage_path.is_dir()


def test_agent_session_storage(agent_with_storage, shared_db):
    """Test that agent sessions are properly stored."""
    # Run agent and get response
    agent_with_storage.run("What is the capital of France?")

    # Get the session ID from the agent
    session_id = agent_with_storage.session_id

    # Verify session was stored
    stored_session = shared_db.read(session_id)
    assert stored_session is not None
    assert isinstance(stored_session, AgentSession)
    assert stored_session.session_id == session_id

    # Verify session contains the interaction
    assert len(stored_session.memory["runs"]) > 0


def test_multiple_interactions(agent_with_storage, shared_db):
    """Test that multiple interactions are properly stored in the same session."""
    # First interaction
    agent_with_storage.run("What is the capital of France?")
    session_id = agent_with_storage.session_id

    # Second interaction
    agent_with_storage.run("What is its population?")

    # Verify both interactions are in the same session
    stored_session = shared_db.read(session_id)
    assert stored_session is not None
    assert len(stored_session.memory["runs"]) >= 2  # Should have at least 2 runs (2 x (question + response))


def test_session_retrieval_by_user(agent_with_storage, shared_db):
    """Test retrieving sessions filtered by user ID."""
    # Create a session with a specific user ID
    agent_with_storage.user_id = "test_user"
    agent_with_storage.run("What is the capital of France?")

    # Get all sessions for the user
    sessions = shared_db.get_all_sessions(user_id="test_user")
    assert len(sessions) == 1
    assert sessions[0].user_id == "test_user"

    # Verify no sessions for different user
    other_sessions = shared_db.get_all_sessions(user_id="other_user")
    assert len(other_sessions) == 0


def test_session_deletion(agent_with_storage, shared_db):
    """Test deleting a session."""
    # Create a session
    agent_with_storage.run("What is the capital of France?")
    session_id = agent_with_storage.session_id

    # Verify session exists
    assert shared_db.read(session_id) is not None

    # Delete session
    shared_db.delete_session(session_id)

    # Verify session was deleted
    assert shared_db.read(session_id) is None


def test_get_all_session_ids(shared_db):
    """Test retrieving all session IDs."""
    # Create multiple sessions with different user IDs and agent IDs
    agent_1 = Agent(storage=shared_db, user_id="user1", agent_id="agent1", add_history_to_context=True)
    agent_2 = Agent(storage=shared_db, user_id="user1", agent_id="agent2", add_history_to_context=True)
    agent_3 = Agent(storage=shared_db, user_id="user2", agent_id="agent3", add_history_to_context=True)

    agent_1.run("Question 1")
    agent_2.run("Question 2")
    agent_3.run("Question 3")

    # Get all session IDs
    all_sessions = shared_db.get_all_session_ids()
    assert len(all_sessions) == 3

    # Filter by user ID
    user1_sessions = shared_db.get_all_session_ids(user_id="user1")
    assert len(user1_sessions) == 2

    # Filter by agent ID
    agent1_sessions = shared_db.get_all_session_ids(entity_id="agent1")
    assert len(agent1_sessions) == 1

    # Filter by both
    filtered_sessions = shared_db.get_all_session_ids(user_id="user1", entity_id="agent2")
    assert len(filtered_sessions) == 1


def test_drop_storage(agent_with_storage, shared_db):
    """Test dropping all sessions from storage."""
    # Create a few sessions
    for i in range(3):
        agent = Agent(storage=shared_db, add_history_to_context=True)
        agent.run(f"Question {i}")

    # Verify sessions exist
    assert len(shared_db.get_all_session_ids()) == 3

    # Drop all sessions
    shared_db.drop()

    # Verify no sessions remain
    assert len(shared_db.get_all_session_ids()) == 0
