"""Tests for agno.os.utils session name functions."""

import time

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.utils import get_session_name
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


@pytest.fixture
def test_agent(shared_db):
    """Create a test agent with SQLite database."""
    return Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
    )


@pytest.fixture
def test_os_client(test_agent: Agent, shared_db: SqliteDb):
    """Create a FastAPI test client with AgentOS."""
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    return TestClient(app), shared_db, test_agent


@pytest.fixture
def session_with_explicit_name(test_agent: Agent):
    """Session with explicit session_name in session_data."""
    run = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Hello, how are you?"),
            Message(role="assistant", content="I'm doing great!"),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-explicit-name",
        agent_id=test_agent.id,
        user_id="test-user",
        session_data={"session_name": "My Custom Session Name"},
        runs=[run],
    )


@pytest.fixture
def session_with_user_message(test_agent: Agent):
    """Session without session_name, should use first user message."""
    run = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Hello, how are you?"),
            Message(role="assistant", content="I'm doing great!"),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-user-message",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[run],
    )


@pytest.fixture
def session_with_fallback(test_agent: Agent):
    """Session where first run has no user message, should fallback to second run."""
    run1 = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="assistant", content="I'm doing great, thank you!"),
        ],
        created_at=int(time.time()) - 3600,
    )
    run2 = RunOutput(
        run_id="run-2",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="What is the weather?"),
            Message(role="assistant", content="It's sunny and 70 degrees Fahrenheit."),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-fallback",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[run1, run2],
    )


@pytest.fixture
def session_empty_runs(test_agent: Agent):
    """Session with no runs."""
    return AgentSession(
        session_id="session-empty",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[],
    )


@pytest.fixture
def session_no_user_messages(test_agent: Agent):
    """Session with only assistant messages."""
    run = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="assistant", content="Hello!"),
            Message(role="assistant", content="How can I help?"),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-no-user",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[run],
    )


@pytest.fixture
def session_with_introduction(test_agent: Agent):
    """Session where assistant sends intro first, then user responds."""
    run = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="assistant", content="Hello! I'm your helpful assistant."),
            Message(role="user", content="What is the weather like?"),
            Message(role="assistant", content="It's sunny today."),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-with-intro",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[run],
    )


def test_get_session_name_returns_explicit_session_name(session_with_explicit_name):
    """Test that get_session_name returns explicitly set session_name from session_data."""
    assert get_session_name(session_with_explicit_name.to_dict()) == "My Custom Session Name"


def test_get_session_name_returns_first_user_message(session_with_user_message):
    """Test that get_session_name returns first user message when no session_name is set."""
    assert get_session_name(session_with_user_message.to_dict()) == "Hello, how are you?"


def test_get_session_name_fallback_to_second_run(session_with_fallback):
    """Test that get_session_name falls back to user message in second run when first run has none."""
    assert get_session_name(session_with_fallback.to_dict()) == "What is the weather?"


def test_get_session_name_empty_runs(session_empty_runs):
    """Test that get_session_name returns empty string when session has no runs."""
    assert get_session_name(session_empty_runs.to_dict()) == ""


def test_get_session_name_no_user_messages(session_no_user_messages):
    """Test that get_session_name returns empty string when no user messages exist."""
    assert get_session_name(session_no_user_messages.to_dict()) == ""


def test_get_session_name_with_introduction(session_with_introduction):
    """Test that get_session_name skips assistant introduction and returns user message."""
    assert get_session_name(session_with_introduction.to_dict()) == "What is the weather like?"
