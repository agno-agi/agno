import tempfile
from pathlib import Path
from typing import Generator

import pytest

from agno.storage.json import JsonStorage
from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def agent_storage(temp_dir: Path) -> JsonStorage:
    return JsonStorage(dir_path=temp_dir)


@pytest.fixture
def workflow_storage(temp_dir: Path) -> JsonStorage:
    return JsonStorage(dir_path=temp_dir, mode="workflow")


def test_agent_storage_crud(agent_storage: JsonStorage, temp_dir: Path):
    # Test create
    agent_storage.create()
    assert temp_dir.exists()

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
    assert (temp_dir / "test-session.json").exists()

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
    assert not (temp_dir / "test-session.json").exists()


def test_workflow_storage_crud(workflow_storage: JsonStorage, temp_dir: Path):
    # Test create
    workflow_storage.create()
    assert temp_dir.exists()

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
    assert (temp_dir / "test-session.json").exists()

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
    assert not (temp_dir / "test-session.json").exists()


def test_storage_filtering(agent_storage: JsonStorage):
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


def test_workflow_storage_filtering(workflow_storage: JsonStorage):
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
