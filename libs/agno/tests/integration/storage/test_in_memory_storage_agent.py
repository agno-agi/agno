import pytest

from agno.agent import Agent
from agno.storage.in_memory import InMemoryStorage
from agno.storage.session.agent import AgentSession


@pytest.fixture
def agent_storage():
    """Create an InMemoryStorage instance for agent sessions."""
    return InMemoryStorage(mode="agent")


@pytest.fixture
def agent_with_storage(agent_storage):
    """Create an agent with the test storage."""
    return Agent(storage=agent_storage, add_history_to_messages=True)


def test_storage_creation():
    """Test that storage can be created without errors."""
    storage = InMemoryStorage()
    assert storage.mode == "agent"


def test_agent_session_storage(agent_with_storage, agent_storage):
    """Test that agent sessions are properly stored."""
    # Run agent and get response
    agent_with_storage.run("What is the capital of France?")

    # Get the session ID from the agent
    session_id = agent_with_storage.session_id

    # Verify session was stored
    stored_session = agent_storage.read(session_id)
    assert stored_session is not None
    assert isinstance(stored_session, AgentSession)
    assert stored_session.session_id == session_id

    # Verify session contains the interaction
    assert len(stored_session.memory["runs"]) > 0


def test_multiple_interactions(agent_with_storage, agent_storage):
    """Test that multiple interactions are properly stored in the same session."""
    # First interaction
    agent_with_storage.run("What is the capital of France?")
    session_id = agent_with_storage.session_id

    # Second interaction
    agent_with_storage.run("What is its population?")

    # Verify both interactions are in the same session
    stored_session = agent_storage.read(session_id)
    assert stored_session is not None
    assert len(stored_session.memory["runs"]) >= 2  # Should have at least 2 runs (2 x (question + response))


def test_session_retrieval_by_user(agent_with_storage, agent_storage):
    """Test retrieving sessions filtered by user ID."""
    # Create a session with a specific user ID
    agent_with_storage.user_id = "test_user"
    agent_with_storage.run("What is the capital of France?")

    # Get all sessions for the user
    sessions = agent_storage.get_all_sessions(user_id="test_user")
    assert len(sessions) == 1
    assert sessions[0].user_id == "test_user"

    # Verify no sessions for different user
    other_sessions = agent_storage.get_all_sessions(user_id="other_user")
    assert len(other_sessions) == 0


def test_session_deletion(agent_with_storage, agent_storage):
    """Test deleting a session."""
    # Create a session
    agent_with_storage.run("What is the capital of France?")
    session_id = agent_with_storage.session_id

    # Verify session exists
    assert agent_storage.read(session_id) is not None

    # Delete session
    agent_storage.delete_session(session_id)

    # Verify session was deleted
    assert agent_storage.read(session_id) is None


def test_get_all_session_ids(agent_storage):
    """Test retrieving all session IDs."""
    # Create multiple sessions with different user IDs and agent IDs
    agent_1 = Agent(storage=agent_storage, user_id="user1", agent_id="agent1", add_history_to_messages=True)
    agent_2 = Agent(storage=agent_storage, user_id="user1", agent_id="agent2", add_history_to_messages=True)
    agent_3 = Agent(storage=agent_storage, user_id="user2", agent_id="agent3", add_history_to_messages=True)

    agent_1.run("Question 1")
    agent_2.run("Question 2")
    agent_3.run("Question 3")

    # Get all session IDs
    all_sessions = agent_storage.get_all_session_ids()
    assert len(all_sessions) == 3

    # Filter by user ID
    user1_sessions = agent_storage.get_all_session_ids(user_id="user1")
    assert len(user1_sessions) == 2

    # Filter by agent ID
    agent1_sessions = agent_storage.get_all_session_ids(entity_id="agent1")
    assert len(agent1_sessions) == 1

    # Filter by both
    filtered_sessions = agent_storage.get_all_session_ids(user_id="user1", entity_id="agent2")
    assert len(filtered_sessions) == 1


def test_drop_storage(agent_with_storage, agent_storage):
    """Test dropping all sessions from storage."""
    # Create a few sessions
    for i in range(3):
        agent = Agent(storage=agent_storage, add_history_to_messages=True)
        agent.run(f"Question {i}")

    # Verify sessions exist
    assert len(agent_storage.get_all_session_ids()) == 3

    # Drop all sessions
    agent_storage.drop()

    # Verify no sessions remain
    assert len(agent_storage.get_all_session_ids()) == 0


def test_get_recent_sessions(agent_storage):
    """Test getting recent sessions."""
    import time

    # Create multiple agents with different timestamps
    agents = []
    for i in range(5):
        agent = Agent(storage=agent_storage, add_history_to_messages=True)
        agent.run(f"Question {i}")
        agents.append(agent)
        time.sleep(0.01)  # Small delay to ensure different timestamps

    # Test get recent sessions with default limit
    recent_sessions = agent_storage.get_recent_sessions()
    assert len(recent_sessions) == 2  # Default limit

    # Sessions should be ordered by created_at descending (most recent first)
    session_ids = [s.session_id for s in recent_sessions]
    # The most recent sessions should be from the last agents created
    assert agents[-1].session_id in session_ids
    assert agents[-2].session_id in session_ids

    # Test with custom limit
    recent_sessions = agent_storage.get_recent_sessions(limit=3)
    assert len(recent_sessions) == 3

    # Test with user_id filter
    # Create an agent with a specific user_id
    user_agent = Agent(storage=agent_storage, user_id="specific_user", add_history_to_messages=True)
    user_agent.run("User question")

    recent_sessions = agent_storage.get_recent_sessions(user_id="specific_user", limit=5)
    assert len(recent_sessions) == 1
    assert recent_sessions[0].user_id == "specific_user"

    # Test with entity_id filter
    entity_agent = Agent(storage=agent_storage, agent_id="specific_agent", add_history_to_messages=True)
    entity_agent.run("Entity question")

    recent_sessions = agent_storage.get_recent_sessions(entity_id="specific_agent", limit=5)
    assert len(recent_sessions) == 1
    assert recent_sessions[0].agent_id == "specific_agent"


def test_persistent_memory_across_runs(agent_storage):
    """Test that memory persists across multiple runs with the same agent."""
    # Create an agent with a specific session_id
    agent = Agent(storage=agent_storage, session_id="persistent_session", add_history_to_messages=True)

    # First run
    agent.run("My name is John")

    # Create a new agent instance with the same session_id
    agent2 = Agent(storage=agent_storage, session_id="persistent_session", add_history_to_messages=True)

    # The second agent should have access to the previous conversation
    stored_session = agent_storage.read("persistent_session")
    assert stored_session is not None
    assert len(stored_session.memory["runs"]) > 0

    # Run with the second agent
    agent2.run("What is my name?")

    # Verify both runs are stored
    final_session = agent_storage.read("persistent_session")
    assert final_session is not None
    assert len(final_session.memory["runs"]) >= 2


def test_external_storage_dict_with_agent():
    """Test using external dict with agents for custom storage mechanisms."""
    # Create an external dict that could be connected to Redis, database, etc.
    external_storage = {}

    # Create storage with external dict
    storage = InMemoryStorage(storage_dict=external_storage)

    # Create agent with external storage
    agent = Agent(storage=storage, add_history_to_messages=True)

    # Run agent
    agent.run("Hello, I'm testing external storage")

    # Verify data is in external dict
    assert len(external_storage) == 1
    session_id = agent.session_id
    assert session_id in external_storage
    assert external_storage[session_id]["session_id"] == session_id

    # Create another agent instance sharing the same external storage
    agent2 = Agent(
        storage=InMemoryStorage(storage_dict=external_storage), session_id=session_id, add_history_to_messages=True
    )

    # Verify agent2 can access the previous conversation
    stored_session = agent2.storage.read(session_id)
    assert stored_session is not None
    assert len(stored_session.memory["runs"]) > 0

    # Run agent2 and verify external dict is updated
    agent2.run("This is a follow-up message")

    # Verify external dict reflects the update
    final_session_data = external_storage[session_id]
    assert len(final_session_data["memory"]["runs"]) >= 2


def test_shared_storage_across_multiple_agents():
    """Test multiple agents sharing the same external storage dict."""
    shared_storage = {}

    # Create multiple agents with shared storage
    agents = []
    for i in range(3):
        agent = Agent(
            storage=InMemoryStorage(storage_dict=shared_storage),
            user_id=f"user-{i}",
            agent_id=f"agent-{i}",
            add_history_to_messages=True,
        )
        agents.append(agent)
        agent.run(f"Hello from agent {i}")

    # Verify all sessions are in shared storage
    assert len(shared_storage) == 3

    # Verify each agent can see its own session
    for i, agent in enumerate(agents):
        session = agent.storage.read(agent.session_id)
        assert session is not None
        assert session.user_id == f"user-{i}"
        assert session.agent_id == f"agent-{i}"

    # Test filtering across shared storage
    storage = InMemoryStorage(storage_dict=shared_storage)
    user_0_sessions = storage.get_all_sessions(user_id="user-0")
    assert len(user_0_sessions) == 1
    assert user_0_sessions[0].user_id == "user-0"

    agent_1_sessions = storage.get_all_sessions(entity_id="agent-1")
    assert len(agent_1_sessions) == 1
    assert agent_1_sessions[0].agent_id == "agent-1"
