import pytest

from agno.storage.in_memory import InMemoryStorage
from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession


@pytest.fixture
def agent_storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def workflow_storage() -> InMemoryStorage:
    return InMemoryStorage(mode="workflow")


def test_agent_storage_crud(agent_storage: InMemoryStorage):
    # Test create (no-op for in-memory)
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

    saved_session = agent_storage.upsert(session)
    assert saved_session is not None
    assert saved_session.session_id == session.session_id

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
    assert agent_storage.read("test-session") is None


def test_workflow_storage_crud(workflow_storage: InMemoryStorage):
    # Test create (no-op for in-memory)
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

    saved_session = workflow_storage.upsert(session)
    assert saved_session is not None
    assert saved_session.session_id == session.session_id

    # Test read
    read_session = workflow_storage.read("test-session")
    assert read_session is not None
    assert read_session.session_id == session.session_id
    assert read_session.workflow_id == session.workflow_id
    assert read_session.memory == session.memory

    # Test get all sessions
    all_sessions = workflow_storage.get_all_sessions()
    assert len(all_sessions) == 1
    assert all_sessions[0].session_id == session.session_id

    # Test delete
    workflow_storage.delete_session("test-session")
    assert workflow_storage.read("test-session") is None


def test_storage_filtering(agent_storage: InMemoryStorage):
    # Create test sessions
    sessions = [
        AgentSession(
            session_id=f"session-{i}",
            agent_id="agent-1" if i < 2 else "agent-2",
            user_id="user-1" if i % 2 == 0 else "user-2",
        )
        for i in range(4)
    ]

    for session in sessions:
        agent_storage.upsert(session)

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


def test_workflow_storage_filtering(workflow_storage: InMemoryStorage):
    # Create test sessions
    sessions = [
        WorkflowSession(
            session_id=f"session-{i}",
            workflow_id="workflow-1" if i < 2 else "workflow-2",
            user_id="user-1" if i % 2 == 0 else "user-2",
            memory={"key": f"value-{i}"},
            workflow_data={"name": f"Test Workflow {i}"},
            session_data={"state": "active"},
            extra_data={"custom": f"data-{i}"},
        )
        for i in range(4)
    ]

    for session in sessions:
        workflow_storage.upsert(session)

    # Test filtering by user_id
    user1_sessions = workflow_storage.get_all_sessions(user_id="user-1")
    assert len(user1_sessions) == 2
    assert all(s.user_id == "user-1" for s in user1_sessions)

    # Test filtering by workflow_id
    workflow1_sessions = workflow_storage.get_all_sessions(entity_id="workflow-1")
    assert len(workflow1_sessions) == 2
    assert all(s.workflow_id == "workflow-1" for s in workflow1_sessions)

    # Test combined filtering
    filtered_sessions = workflow_storage.get_all_sessions(user_id="user-1", entity_id="workflow-1")
    assert len(filtered_sessions) == 1
    assert filtered_sessions[0].user_id == "user-1"
    assert filtered_sessions[0].workflow_id == "workflow-1"

    # Test filtering with non-existent IDs
    empty_sessions = workflow_storage.get_all_sessions(user_id="non-existent")
    assert len(empty_sessions) == 0

    empty_sessions = workflow_storage.get_all_sessions(entity_id="non-existent")
    assert len(empty_sessions) == 0


def test_get_all_session_ids(agent_storage: InMemoryStorage):
    # Create test sessions
    sessions = [
        AgentSession(
            session_id=f"session-{i}",
            agent_id="agent-1" if i < 2 else "agent-2",
            user_id="user-1" if i % 2 == 0 else "user-2",
        )
        for i in range(4)
    ]

    for session in sessions:
        agent_storage.upsert(session)

    # Test get all session IDs
    all_ids = agent_storage.get_all_session_ids()
    assert len(all_ids) == 4

    # Test filtering by user_id
    user1_ids = agent_storage.get_all_session_ids(user_id="user-1")
    assert len(user1_ids) == 2

    # Test filtering by agent_id
    agent1_ids = agent_storage.get_all_session_ids(entity_id="agent-1")
    assert len(agent1_ids) == 2

    # Test combined filtering
    filtered_ids = agent_storage.get_all_session_ids(user_id="user-1", entity_id="agent-1")
    assert len(filtered_ids) == 1


def test_get_recent_sessions(agent_storage: InMemoryStorage):
    import time

    # Create test sessions with different timestamps
    sessions = []
    for i in range(5):
        session = AgentSession(
            session_id=f"session-{i}",
            agent_id="test-agent",
            user_id="test-user",
        )
        agent_storage.upsert(session)
        sessions.append(session)
        time.sleep(0.01)  # Small delay to ensure different timestamps

    # Test get recent sessions with default limit
    recent_sessions = agent_storage.get_recent_sessions()
    assert len(recent_sessions) == 2  # Default limit

    assert recent_sessions[0].session_id == "session-0"
    assert recent_sessions[1].session_id == "session-1"

    # Test with custom limit
    recent_sessions = agent_storage.get_recent_sessions(limit=3)
    assert len(recent_sessions) == 3
    assert recent_sessions[0].session_id == "session-0"
    assert recent_sessions[1].session_id == "session-1"
    assert recent_sessions[2].session_id == "session-2"

    # Test with user_id filter
    recent_sessions = agent_storage.get_recent_sessions(user_id="test-user", limit=1)
    assert len(recent_sessions) == 1
    assert recent_sessions[0].session_id == "session-0"

    # Test with entity_id filter
    recent_sessions = agent_storage.get_recent_sessions(entity_id="test-agent", limit=1)
    assert len(recent_sessions) == 1
    assert recent_sessions[0].session_id == "session-0"


def test_drop_storage(agent_storage: InMemoryStorage):
    # Create test sessions
    sessions = [AgentSession(session_id=f"session-{i}", agent_id="test-agent", user_id="test-user") for i in range(3)]

    for session in sessions:
        agent_storage.upsert(session)

    # Verify sessions exist
    assert len(agent_storage.get_all_sessions()) == 3

    # Drop all sessions
    agent_storage.drop()

    # Verify no sessions remain
    assert len(agent_storage.get_all_sessions()) == 0


def test_read_with_user_id_filter(agent_storage: InMemoryStorage):
    # Create a session
    session = AgentSession(
        session_id="test-session",
        agent_id="test-agent",
        user_id="test-user",
    )
    agent_storage.upsert(session)

    # Test reading with correct user_id
    read_session = agent_storage.read("test-session", user_id="test-user")
    assert read_session is not None
    assert read_session.session_id == "test-session"

    # Test reading with incorrect user_id
    read_session = agent_storage.read("test-session", user_id="wrong-user")
    assert read_session is None

    # Test reading without user_id filter
    read_session = agent_storage.read("test-session")
    assert read_session is not None


def test_upgrade_schema(agent_storage: InMemoryStorage):
    # Test upgrade_schema (no-op for in-memory)
    agent_storage.upgrade_schema()
    # Should complete without error


def test_external_storage_dict():
    # Test with external dictionary
    external_dict = {}
    storage = InMemoryStorage(storage_dict=external_dict)

    # Create a session
    session = AgentSession(
        session_id="test-session",
        agent_id="test-agent",
        user_id="test-user",
    )

    # Upsert session
    storage.upsert(session)

    # Verify session is stored in external dict
    assert "test-session" in external_dict
    assert external_dict["test-session"]["session_id"] == "test-session"

    # Verify we can read it back
    read_session = storage.read("test-session")
    assert read_session is not None
    assert read_session.session_id == "test-session"

    # Test that external dict is modified when we modify storage
    storage.delete_session("test-session")
    assert "test-session" not in external_dict


def test_shared_external_storage_dict():
    # Test sharing external dictionary between multiple storage instances
    shared_dict = {}

    # Create two storage instances with the same external dict
    storage1 = InMemoryStorage(storage_dict=shared_dict)
    storage2 = InMemoryStorage(storage_dict=shared_dict)

    # Create session in first storage
    session1 = AgentSession(
        session_id="session-1",
        agent_id="agent-1",
        user_id="user-1",
    )
    storage1.upsert(session1)

    # Verify second storage can read it
    read_session = storage2.read("session-1")
    assert read_session is not None
    assert read_session.session_id == "session-1"

    # Create session in second storage
    session2 = AgentSession(
        session_id="session-2",
        agent_id="agent-2",
        user_id="user-2",
    )
    storage2.upsert(session2)

    # Verify first storage can see both sessions
    all_sessions = storage1.get_all_sessions()
    assert len(all_sessions) == 2
    session_ids = [s.session_id for s in all_sessions]
    assert "session-1" in session_ids
    assert "session-2" in session_ids

    # Verify shared dict contains both sessions
    assert len(shared_dict) == 2
    assert "session-1" in shared_dict
    assert "session-2" in shared_dict


def test_external_dict_with_existing_data():
    # Test with external dict that already has data
    existing_data = {
        "existing-session": {
            "session_id": "existing-session",
            "agent_id": "existing-agent",
            "user_id": "existing-user",
            "memory": {"existing": "data"},
            "agent_data": {},
            "session_data": {},
            "extra_data": {},
            "created_at": 1000000000,
            "updated_at": 1000000000,
        }
    }

    storage = InMemoryStorage(storage_dict=existing_data)

    # Verify we can read existing data
    read_session = storage.read("existing-session")
    assert read_session is not None
    assert read_session.session_id == "existing-session"
    assert read_session.memory == {"existing": "data"}

    # Verify get_all_sessions includes existing data
    all_sessions = storage.get_all_sessions()
    assert len(all_sessions) == 1
    assert all_sessions[0].session_id == "existing-session"

    # Add new session and verify both exist
    new_session = AgentSession(
        session_id="new-session",
        agent_id="new-agent",
        user_id="new-user",
    )
    storage.upsert(new_session)

    all_sessions = storage.get_all_sessions()
    assert len(all_sessions) == 2
    session_ids = [s.session_id for s in all_sessions]
    assert "existing-session" in session_ids
    assert "new-session" in session_ids
