"""Tests for generate_session_name — validates message history is preserved
and naming instruction is appended (the core prompt-cache optimisation)."""

from unittest.mock import Mock

from agno.agent.agent import Agent
from agno.agent._session import generate_session_name
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team._session import generate_session_name as team_generate_session_name
from agno.team.team import Team


def _make_run(messages: list[Message], status: RunStatus = RunStatus.completed) -> RunOutput:
    return RunOutput(status=status, messages=messages)


def test_agent_preserves_existing_messages():
    """Session messages are passed verbatim; naming instruction is appended last."""
    model = Mock(spec=OpenAIChat)
    model.response.return_value = ModelResponse(content="My Session")

    agent = Agent(name="TestAgent", model=model)

    session = AgentSession(
        session_id="test-session",
        runs=[
            _make_run([
                Message(role="system", content="You are a helpful assistant."),
                Message(role="user", content="What is Kubernetes?"),
                Message(role="assistant", content="A container orchestrator."),
            ]),
        ],
    )

    name = generate_session_name(agent, session)

    called_messages = model.response.call_args[1]["messages"]
    assert len(called_messages) == 4
    assert called_messages[0].role == "system"
    assert called_messages[0].content == "You are a helpful assistant."
    assert called_messages[1].role == "user"
    assert called_messages[1].content == "What is Kubernetes?"
    assert called_messages[2].role == "assistant"
    assert called_messages[2].content == "A container orchestrator."
    assert called_messages[3].role == "user"
    assert "maximum 5 words" in called_messages[3].content
    assert name == "My Session"


def test_team_preserves_existing_messages():
    """Same assertion for the Team variant."""
    model = Mock(spec=OpenAIChat)
    model.response.return_value = ModelResponse(content="Team Session")

    team = Team(name="TestTeam", model=model, members=[])

    session = TeamSession(
        session_id="team-test-session",
        runs=[
            _make_run([
                Message(role="system", content="Team instructions."),
                Message(role="user", content="Plan migration."),
                Message(role="assistant", content="Step 1: ..."),
            ]),
        ],
    )

    name = team_generate_session_name(team, session)

    called_messages = model.response.call_args[1]["messages"]
    assert len(called_messages) == 4
    assert called_messages[0].content == "Team instructions."
    assert called_messages[1].content == "Plan migration."
    assert called_messages[2].content == "Step 1: ..."
    assert called_messages[3].role == "user"
    assert "maximum 5 words" in called_messages[3].content
    assert name == "Team Session"
