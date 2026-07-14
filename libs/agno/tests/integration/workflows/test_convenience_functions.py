import uuid

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.db.sqlite.sqlite import SqliteDb
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# -- 1. Workflow class convenience functions --


def test_get_session(simple_workflow: Workflow):
    """Test get_session returns the correct session."""
    session_id = str(uuid.uuid4())

    # Simple run to store the session
    response = simple_workflow.run("Hello", session_id=session_id)
    assert response is not None

    # Assert we can get the session
    session = simple_workflow.get_session(session_id=session_id)
    assert session is not None
    assert session.session_id == session_id
    assert len(session.runs or []) == 1


@pytest.mark.asyncio
async def test_aget_session(simple_workflow_with_async_db: Workflow):
    """Test aget_session returns the correct session."""
    session_id = str(uuid.uuid4())

    # Simple run to store the session
    response = await simple_workflow_with_async_db.arun("Hello", session_id=session_id)
    assert response is not None

    # Assert we can get the session
    session = await simple_workflow_with_async_db.aget_session(session_id=session_id)
    assert session is not None
    assert session.session_id == session_id
    assert len(session.runs or []) == 1


def test_get_session_nonexistent(simple_workflow):
    """Test get_session returns None for non-existent session."""
    session = simple_workflow.get_session(session_id="nonexistent")
    assert session is None


def test_get_chat_history(simple_workflow: Workflow):
    """Test get_chat_history returns the correct chat history."""
    session_id = str(uuid.uuid4())

    # Simple run to store the session
    response = simple_workflow.run("Hello", session_id=session_id)
    assert response is not None

    # Assert we can get the chat history
    chat_history = simple_workflow.get_chat_history(session_id=session_id)
    assert len(chat_history) == 1
    assert chat_history[0].input == "Hello"
    assert chat_history[0].output == response.content


def test_get_chat_history_with_default_session_id(simple_workflow: Workflow):
    """Test get_chat_history uses workflow's session_id if not provided."""
    simple_workflow.session_id = str(uuid.uuid4())
    response = simple_workflow.run("Hello")
    assert response is not None

    # Assert we can get the chat history
    chat_history = simple_workflow.get_chat_history()
    assert len(chat_history) == 1
    assert chat_history[0].input == "Hello"
    assert chat_history[0].output == response.content


# -- 2. Step class convenience functions --


def test_step_get_chat_history_for_agent(agent_with_db: Agent):
    """Test step.get_chat_history returns the correct chat history."""
    session_id = str(uuid.uuid4())
    step = Step(name="Test Step", agent=agent_with_db)
    workflow = Workflow(name="Test Workflow", db=agent_with_db.db, steps=[step])

    # Simple run to store the session
    response = workflow.run("Hello", session_id=session_id)
    assert response is not None

    # Assert we can get the chat history
    step_chat_history = step.get_chat_history(session_id=session_id)
    assert step_chat_history is not None
    assert len(step_chat_history) == 3
    assert step_chat_history[0].role == "system"
    assert step_chat_history[1].role == "user"
    assert step_chat_history[1].content == "Hello"
    assert step_chat_history[2].role == "assistant"
    assert step_chat_history[2].content == response.content


@pytest.mark.asyncio
async def test_step_aget_chat_history_for_agent(mock_agent: Agent, async_shared_db: AsyncSqliteDb):
    """Test step.aget_chat_history returns the correct chat history."""
    session_id = str(uuid.uuid4())
    mock_agent.db = async_shared_db
    step = Step(name="Test Step", agent=mock_agent)
    workflow = Workflow(name="Test Workflow", db=async_shared_db, steps=[step])

    # Simple run to store the session
    response = await workflow.arun("Hello", session_id=session_id)
    assert response is not None

    # Assert we can get the chat history
    step_chat_history = await step.aget_chat_history(session_id=session_id)
    assert step_chat_history is not None
    assert len(step_chat_history) == 3
    assert step_chat_history[0].role == "system"
    assert step_chat_history[1].role == "user"
    assert step_chat_history[1].content == "Hello"
    assert step_chat_history[2].role == "assistant"
    assert step_chat_history[2].content == response.content


def test_step_get_chat_history_for_team(mock_team: Team, shared_db: SqliteDb):
    """Test step.get_chat_history returns the correct chat history."""
    session_id = str(uuid.uuid4())
    mock_team.db = shared_db
    step = Step(name="Test Step", team=mock_team)
    workflow = Workflow(name="Test Workflow", db=shared_db, steps=[step])

    # Simple run to store the session
    response = workflow.run("Hello", session_id=session_id)
    assert response is not None

    # Assert we can get the chat history
    step_chat_history = step.get_chat_history(session_id=session_id)
    assert step_chat_history is not None
    assert len(step_chat_history) == 3
    assert step_chat_history[0].role == "system"
    assert step_chat_history[1].role == "user"
    assert step_chat_history[1].content == "Hello"
    assert step_chat_history[2].role == "assistant"
    assert step_chat_history[2].content == response.content


@pytest.mark.asyncio
async def test_step_aget_chat_history_for_team(mock_team: Team, async_shared_db: AsyncSqliteDb):
    """Test step.aget_chat_history returns the correct chat history."""
    session_id = str(uuid.uuid4())
    mock_team.db = async_shared_db
    step = Step(name="Test Step", team=mock_team)
    workflow = Workflow(name="Test Workflow", db=async_shared_db, steps=[step])

    # Simple run to store the session
    response = await workflow.arun("Hello", session_id=session_id)
    assert response is not None

    # Assert we can get the chat history
    step_chat_history = await step.aget_chat_history(session_id=session_id)
    assert step_chat_history is not None
    assert len(step_chat_history) == 3
    assert step_chat_history[0].role == "system"
    assert step_chat_history[1].role == "user"
    assert step_chat_history[1].content == "Hello"
    assert step_chat_history[2].role == "assistant"
    assert step_chat_history[2].content == response.content
