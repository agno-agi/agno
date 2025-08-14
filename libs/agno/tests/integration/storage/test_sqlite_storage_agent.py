import os
import uuid

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteStorage
from agno.session import AgentSession


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database file path."""
    db_file = tmp_path / "test_agent_db.db"
    yield str(db_file)
    # Clean up the file after tests
    if os.path.exists(db_file):
        os.remove(db_file)


@pytest.fixture
def agent_db(temp_db_path):
    """Create a SqliteStorage instance for agent sessions."""
    # Use a unique table name for each test run
    table_name = f"agent_sessions_{uuid.uuid4().hex[:8]}"
    storage = SqliteStorage(table_name=table_name, db_file=temp_db_path, mode="agent")
    storage.create()
    return storage


@pytest.fixture
def agent_with_storage(agent_db):
    """Create an agent with the test storage."""
    return Agent(db=agent_db, add_history_to_context=True)


def test_storage_creation(temp_db_path):
    """Test that storage is created correctly."""
    storage = SqliteStorage(table_name="agent_sessions", db_file=temp_db_path)
    storage.create()
    assert os.path.exists(temp_db_path)
    assert storage.table_exists()


def test_agent_session_storage(agent_with_storage, agent_db):
    """Test that agent sessions are properly stored."""
    # Run agent and get response
    agent_with_storage.run("What is the capital of France?")

    # Get the session ID from the agent
    session_id = agent_with_storage.session_id

    # Verify session was stored
    stored_session = agent_db.read(session_id)
    assert stored_session is not None
    assert isinstance(stored_session, AgentSession)
    assert stored_session.session_id == session_id

    # Verify session contains the interaction
    assert len(stored_session.memory["runs"]) > 0


def test_multiple_interactions(agent_with_storage, agent_db):
    """Test that multiple interactions are properly stored in the same session."""
    # First interaction
    agent_with_storage.run("What is the capital of France?")
    session_id = agent_with_storage.session_id

    # Second interaction
    agent_with_storage.run("What is its population?")

    # Verify both interactions are in the same session
    stored_session = agent_db.read(session_id)
    assert stored_session is not None
    assert len(stored_session.memory["runs"]) >= 2  # Should have at least 2 runs (2 x (question + response))


def test_session_retrieval_by_user(agent_with_storage, agent_db):
    """Test retrieving sessions filtered by user ID."""
    # Create a session with a specific user ID
    agent_with_storage.user_id = "test_user"
    agent_with_storage.run("What is the capital of France?")

    # Get all sessions for the user
    sessions = agent_db.get_all_sessions(user_id="test_user")
    assert len(sessions) == 1
    assert sessions[0].user_id == "test_user"

    # Verify no sessions for different user
    other_sessions = agent_db.get_all_sessions(user_id="other_user")
    assert len(other_sessions) == 0


def test_session_deletion(agent_with_storage, agent_db):
    """Test deleting a session."""
    # Create a session
    agent_with_storage.run("What is the capital of France?")
    session_id = agent_with_storage.session_id

    # Verify session exists
    assert agent_db.read(session_id) is not None

    # Delete session
    agent_db.delete_session(session_id)

    # Verify session was deleted
    assert agent_db.read(session_id) is None


def test_get_all_session_ids(agent_db):
    """Test retrieving all session IDs."""
    # Create multiple sessions with different user IDs and agent IDs
    agent_1 = Agent(db=agent_db, user_id="user1", id="agent1", add_history_to_context=True)
    agent_2 = Agent(db=agent_db, user_id="user1", id="agent2", add_history_to_context=True)
    agent_3 = Agent(db=agent_db, user_id="user2", id="agent3", add_history_to_context=True)

    agent_1.run("Question 1")
    agent_2.run("Question 2")
    agent_3.run("Question 3")

    # Get all session IDs
    all_sessions = agent_db.get_all_session_ids()
    assert len(all_sessions) == 3

    # Filter by user ID
    user1_sessions = agent_db.get_all_session_ids(user_id="user1")
    assert len(user1_sessions) == 2

    # Filter by agent ID
    agent1_sessions = agent_db.get_all_session_ids(entity_id="agent1")
    assert len(agent1_sessions) == 1

    # Filter by both
    filtered_sessions = agent_db.get_all_session_ids(user_id="user1", entity_id="agent2")
    assert len(filtered_sessions) == 1


def test_drop_storage(agent_with_storage, agent_db):
    """Test dropping all sessions from storage."""
    # Create a few sessions
    for i in range(3):
        agent = Agent(db=agent_db, add_history_to_context=True)
        agent.run(f"Question {i}")

    # Verify sessions exist
    assert len(agent_db.get_all_session_ids()) == 3

    # Drop all sessions
    agent_db.drop()

    # Verify no sessions remain
    assert len(agent_db.get_all_session_ids()) == 0
