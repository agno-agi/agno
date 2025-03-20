import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession
from agno.storage.sqlite import SqliteStorage


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    if db_path.exists():
        os.unlink(db_path)


@pytest.fixture
def agent_storage(temp_db_path: Path) -> SqliteStorage:
    return SqliteStorage(table_name="agent_sessions", db_file=str(temp_db_path), mode="agent")


@pytest.fixture
def workflow_storage(temp_db_path: Path) -> SqliteStorage:
    return SqliteStorage(table_name="workflow_sessions", db_file=str(temp_db_path), mode="workflow")


def test_agent_storage_crud(agent_storage: SqliteStorage):
    # Test create
    agent_storage.create()
    assert agent_storage.table_exists()

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

    # Test drop
    agent_storage.drop()
    assert not agent_storage.table_exists()


def test_workflow_storage_crud(workflow_storage: SqliteStorage):
    # Test create
    workflow_storage.create()
    assert workflow_storage.table_exists()

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

    # Test drop
    workflow_storage.drop()
    assert not workflow_storage.table_exists()


def test_storage_filtering(agent_storage: SqliteStorage):
    # Create test sessions with different combinations
    sessions = [
        AgentSession(
            session_id=f"session-{i}",
            agent_id=f"agent-{i // 2 + 1}",  # agent-1, agent-1, agent-2, agent-2
            user_id=f"user-{i % 3 + 1}",  # user-1, user-2, user-3, user-1
            memory={"test": f"memory-{i}"},
            agent_data={"name": f"Agent {i}"},
            session_data={"state": "active"},
        )
        for i in range(4)
    ]

    for session in sessions:
        agent_storage.upsert(session)

    # Test filtering by user_id
    for user_id in ["user-1", "user-2", "user-3"]:
        user_sessions = agent_storage.get_all_sessions(user_id=user_id)
        assert all(s.user_id == user_id for s in user_sessions)

    # Test filtering by agent_id
    for agent_id in ["agent-1", "agent-2"]:
        agent_sessions = agent_storage.get_all_sessions(entity_id=agent_id)
        assert all(s.agent_id == agent_id for s in agent_sessions)
        assert len(agent_sessions) == 2  # Each agent has 2 sessions

    # Test combined filtering
    filtered_sessions = agent_storage.get_all_sessions(user_id="user-1", entity_id="agent-1")
    assert len(filtered_sessions) == 1
    assert filtered_sessions[0].user_id == "user-1"
    assert filtered_sessions[0].agent_id == "agent-1"

    # Test filtering with non-existent IDs
    empty_sessions = agent_storage.get_all_sessions(user_id="non-existent")
    assert len(empty_sessions) == 0

    empty_sessions = agent_storage.get_all_sessions(entity_id="non-existent")
    assert len(empty_sessions) == 0


def test_workflow_storage_filtering(workflow_storage: SqliteStorage):
    # Create test sessions with different combinations
    sessions = [
        WorkflowSession(
            session_id=f"session-{i}",
            workflow_id=f"workflow-{i // 2 + 1}",  # workflow-1, workflow-1, workflow-2, workflow-2
            user_id=f"user-{i % 3 + 1}",  # user-1, user-2, user-3, user-1
            memory={"test": f"memory-{i}"},
            workflow_data={"name": f"Workflow {i}"},
            session_data={"state": "active"},
        )
        for i in range(4)
    ]

    for session in sessions:
        workflow_storage.upsert(session)

    # Test filtering by user_id
    for user_id in ["user-1", "user-2", "user-3"]:
        user_sessions = workflow_storage.get_all_sessions(user_id=user_id)
        assert all(s.user_id == user_id for s in user_sessions)

    # Test filtering by workflow_id
    for workflow_id in ["workflow-1", "workflow-2"]:
        workflow_sessions = workflow_storage.get_all_sessions(entity_id=workflow_id)
        assert all(s.workflow_id == workflow_id for s in workflow_sessions)
        assert len(workflow_sessions) == 2  # Each workflow has 2 sessions

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
