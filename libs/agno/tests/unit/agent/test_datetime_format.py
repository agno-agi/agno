"""Tests for custom datetime_format on Agent."""

import re
import time
from unittest.mock import MagicMock, patch

import pytest

from agno.agent._messages import aget_run_messages, get_run_messages, get_system_message
from agno.agent.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession

# =============================================================================
# Config tests
# =============================================================================


def test_default_datetime_format_is_none():
    agent = Agent()
    assert agent.datetime_format is None


def test_custom_datetime_format_stored():
    agent = Agent(datetime_format="%Y-%m-%d %H:%M:%S")
    assert agent.datetime_format == "%Y-%m-%d %H:%M:%S"


def test_datetime_format_in_to_dict():
    agent = Agent(
        id="test-agent",
        add_datetime_to_context=True,
        datetime_format="%d/%m/%Y",
    )
    config = agent.to_dict()
    assert config["datetime_format"] == "%d/%m/%Y"


def test_datetime_format_not_in_to_dict_when_none():
    agent = Agent(id="test-agent")
    config = agent.to_dict()
    assert "datetime_format" not in config


def test_datetime_format_from_dict():
    config = {
        "id": "test-agent",
        "add_datetime_to_context": True,
        "datetime_format": "%Y-%m-%d",
    }
    agent = Agent.from_dict(config)
    assert agent.datetime_format == "%Y-%m-%d"
    assert agent.add_datetime_to_context is True


def test_datetime_format_from_dict_missing():
    config = {
        "id": "test-agent",
        "add_datetime_to_context": True,
    }
    agent = Agent.from_dict(config)
    assert agent.datetime_format is None


# =============================================================================
# System message tests
# =============================================================================


def _make_agent_with_model(**kwargs) -> Agent:
    """Create an Agent with a mocked model for system message generation."""
    agent = Agent(**kwargs)
    mock_model = MagicMock()
    mock_model.get_instructions_for_model = MagicMock(return_value=None)
    mock_model.get_system_message_for_model = MagicMock(return_value=None)
    agent.model = mock_model
    return agent


def _get_agent_run_messages(agent: Agent, input: str = "What time is it?"):
    session = AgentSession(session_id="test-session")
    return get_run_messages(
        agent,
        run_response=RunOutput(run_id="test-run", session_id=session.session_id),
        run_context=RunContext(run_id="test-run", session_id=session.session_id),
        input=input,
        session=session,
    )


async def _aget_agent_run_messages(agent: Agent, input: str = "What time is it?"):
    session = AgentSession(session_id="test-session")
    return await aget_run_messages(
        agent,
        run_response=RunOutput(run_id="test-run", session_id=session.session_id),
        run_context=RunContext(run_id="test-run", session_id=session.session_id),
        input=input,
        session=session,
    )


def test_system_message_is_stable_with_datetime_context_enabled():
    agent = _make_agent_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d %H:%M:%S.%f",
    )
    session = AgentSession(session_id="test-session")

    first = get_system_message(agent, session)
    time.sleep(0.01)
    second = get_system_message(agent, session)

    assert first is not None
    assert second is not None
    assert first.content == second.content
    assert "The current time is" not in first.content


def test_default_datetime_format_is_sent_after_the_system_message():
    agent = _make_agent_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
    )

    run_messages = _get_agent_run_messages(agent)
    datetime_message = run_messages.messages[-2]

    assert datetime_message.role == "user"
    assert re.fullmatch(
        r"The current time is \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{6})?\.",
        datetime_message.content,
    )
    assert datetime_message.add_to_agent_memory is False
    assert run_messages.messages[-1] is run_messages.user_message


def test_datetime_context_uses_user_role_when_user_message_role_is_developer():
    agent = _make_agent_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        user_message_role="developer",
    )

    run_messages = _get_agent_run_messages(agent)

    assert run_messages.messages[-2].role == "user"
    assert run_messages.messages[-1].role == "developer"


def test_custom_datetime_format_and_timezone_are_preserved():
    agent = _make_agent_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d %Z %z",
        timezone_identifier="UTC",
    )

    run_messages = _get_agent_run_messages(agent)

    assert re.fullmatch(
        r"The current time is \d{4}-\d{2}-\d{2} UTC \+0000\.",
        run_messages.messages[-2].content,
    )


def test_invalid_timezone_falls_back_and_keeps_datetime_outside_system_message():
    agent = _make_agent_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d",
        timezone_identifier="Invalid/Timezone",
    )

    with patch("agno.agent._messages.log_warning") as mock_log_warning:
        run_messages = _get_agent_run_messages(agent)

    assert run_messages.system_message is not None
    assert "The current time is" not in str(run_messages.system_message.content)
    assert re.fullmatch(r"The current time is \d{4}-\d{2}-\d{2}\.", run_messages.messages[-2].content)
    mock_log_warning.assert_called_once()
    assert "Invalid timezone identifier" in mock_log_warning.call_args.args[0]


def test_no_datetime_message_when_disabled():
    agent = _make_agent_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=False,
        datetime_format="%Y-%m-%d",
    )

    run_messages = _get_agent_run_messages(agent)

    assert all("current time" not in str(message.content).lower() for message in run_messages.messages)


@pytest.mark.asyncio
async def test_async_datetime_context_matches_sync_message_semantics():
    agent = _make_agent_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d",
        timezone_identifier="UTC",
    )

    run_messages = await _aget_agent_run_messages(agent)
    datetime_message = run_messages.messages[-2]

    assert run_messages.system_message is not None
    assert "The current time is" not in str(run_messages.system_message.content)
    assert re.fullmatch(r"The current time is \d{4}-\d{2}-\d{2}\.", datetime_message.content)
    assert datetime_message.role == "user"
    assert datetime_message.add_to_agent_memory is False
    assert run_messages.messages[-1] is run_messages.user_message


@pytest.mark.parametrize(
    "agent",
    [
        _make_agent_with_model(system_message="Custom system", add_datetime_to_context=True),
        _make_agent_with_model(build_context=False, add_datetime_to_context=True),
    ],
)
def test_datetime_context_preserves_existing_system_message_bypass(agent: Agent):
    run_messages = _get_agent_run_messages(agent)

    assert all("current time" not in str(message.content).lower() for message in run_messages.messages)
