"""Tests for custom datetime_format on Agent."""

import re
from unittest.mock import MagicMock

from agno.agent._messages import get_system_message
from agno.agent.agent import Agent
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


def test_default_format_includes_full_datetime():
    """When no datetime_format is set, the full default datetime str is used."""
    agent = _make_agent_with_model(add_datetime_to_context=True)
    session = AgentSession(session_id="test-session")

    msg = get_system_message(agent, session)

    assert msg is not None
    # Default Python datetime str format: YYYY-MM-DD HH:MM:SS.ffffff
    assert re.search(r"The current time is \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", msg.content)


def test_custom_date_only_format():
    """When datetime_format='%Y-%m-%d', only the date portion appears."""
    agent = _make_agent_with_model(
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d",
    )
    session = AgentSession(session_id="test-session")

    msg = get_system_message(agent, session)

    assert msg is not None
    # Should match YYYY-MM-DD followed by period (no time component)
    assert re.search(r"The current time is \d{4}-\d{2}-\d{2}\.", msg.content)


def test_custom_format_slash_style():
    """Custom format with slashes: %d/%m/%Y %H:%M."""
    agent = _make_agent_with_model(
        add_datetime_to_context=True,
        datetime_format="%d/%m/%Y %H:%M",
    )
    session = AgentSession(session_id="test-session")

    msg = get_system_message(agent, session)

    assert msg is not None
    assert re.search(r"The current time is \d{2}/\d{2}/\d{4} \d{2}:\d{2}\.", msg.content)


def test_no_datetime_when_disabled():
    """When add_datetime_to_context is False, no datetime info is added."""
    agent = _make_agent_with_model(
        add_datetime_to_context=False,
        datetime_format="%Y-%m-%d",
    )
    session = AgentSession(session_id="test-session")
    msg = get_system_message(agent, session)

    if msg is not None:
        assert "current time" not in msg.content.lower()
