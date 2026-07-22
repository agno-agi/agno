"""Tests for custom datetime_format on Team."""

import re
import time
from unittest.mock import MagicMock, patch

import pytest

from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._messages import _aget_run_messages, _get_run_messages, get_system_message
from agno.team.team import Team

# =============================================================================
# Config tests
# =============================================================================


def test_default_datetime_format_is_none():
    team = Team(name="t", mode="coordinate", members=[])
    assert team.datetime_format is None


def test_custom_datetime_format_stored():
    team = Team(name="t", mode="coordinate", members=[], datetime_format="%Y-%m-%d %H:%M:%S")
    assert team.datetime_format == "%Y-%m-%d %H:%M:%S"


def test_datetime_format_in_to_dict():
    team = Team(
        name="t",
        mode="coordinate",
        members=[],
        add_datetime_to_context=True,
        datetime_format="%d/%m/%Y",
    )
    config = team.to_dict()
    assert config["datetime_format"] == "%d/%m/%Y"


def test_datetime_format_not_in_to_dict_when_none():
    team = Team(name="t", mode="coordinate", members=[])
    config = team.to_dict()
    assert "datetime_format" not in config


def test_datetime_format_from_dict():
    config = {
        "name": "t",
        "mode": "coordinate",
        "add_datetime_to_context": True,
        "datetime_format": "%Y-%m-%d",
    }
    team = Team.from_dict(config)
    assert team.datetime_format == "%Y-%m-%d"
    assert team.add_datetime_to_context is True


def test_datetime_format_from_dict_missing():
    config = {
        "name": "t",
        "mode": "coordinate",
        "add_datetime_to_context": True,
    }
    team = Team.from_dict(config)
    assert team.datetime_format is None


# =============================================================================
# System message tests
# =============================================================================


def _make_team_with_model(**kwargs) -> Team:
    """Create a Team with a mocked model for system message generation."""
    team = Team(name="test-team", mode="coordinate", members=[], **kwargs)
    mock_model = MagicMock()
    mock_model.get_instructions_for_model = MagicMock(return_value=None)
    mock_model.get_system_message_for_model = MagicMock(return_value=None)
    team.model = mock_model
    return team


def _get_team_run_messages(team: Team, input_message: str = "What time is it?"):
    session = TeamSession(session_id="test-session")
    return _get_run_messages(
        team,
        run_response=TeamRunOutput(run_id="test-run", session_id=session.session_id, team_id=team.id),
        run_context=RunContext(run_id="test-run", session_id=session.session_id),
        session=session,
        input_message=input_message,
    )


async def _aget_team_run_messages(team: Team, input_message: str = "What time is it?"):
    session = TeamSession(session_id="test-session")
    return await _aget_run_messages(
        team,
        run_response=TeamRunOutput(run_id="test-run", session_id=session.session_id, team_id=team.id),
        run_context=RunContext(run_id="test-run", session_id=session.session_id),
        session=session,
        input_message=input_message,
    )


def test_system_message_is_stable_with_datetime_context_enabled():
    team = _make_team_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d %H:%M:%S.%f",
    )
    session = TeamSession(session_id="test-session")

    first = get_system_message(team, session)
    time.sleep(0.01)
    second = get_system_message(team, session)

    assert first is not None
    assert second is not None
    assert first.content == second.content
    assert "The current time is" not in first.content


def test_default_datetime_format_is_sent_after_the_system_message():
    team = _make_team_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
    )

    run_messages = _get_team_run_messages(team)
    datetime_message = run_messages.messages[-2]

    assert datetime_message.role == "user"
    assert re.fullmatch(
        r"The current time is \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{6})?\.",
        datetime_message.content,
    )
    assert datetime_message.add_to_agent_memory is False
    assert run_messages.messages[-1] is run_messages.user_message


def test_custom_datetime_format_and_timezone_are_preserved():
    team = _make_team_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d %Z %z",
        timezone_identifier="UTC",
    )

    run_messages = _get_team_run_messages(team)

    assert re.fullmatch(
        r"The current time is \d{4}-\d{2}-\d{2} UTC \+0000\.",
        run_messages.messages[-2].content,
    )


def test_invalid_timezone_falls_back_and_keeps_datetime_outside_system_message():
    team = _make_team_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d",
        timezone_identifier="Invalid/Timezone",
    )

    with patch("agno.team._messages.log_warning") as mock_log_warning:
        run_messages = _get_team_run_messages(team)

    assert run_messages.system_message is not None
    assert "The current time is" not in str(run_messages.system_message.content)
    assert re.fullmatch(r"The current time is \d{4}-\d{2}-\d{2}\.", run_messages.messages[-2].content)
    mock_log_warning.assert_called_once()
    assert "Invalid timezone identifier" in mock_log_warning.call_args.args[0]


def test_no_datetime_message_when_disabled():
    team = _make_team_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=False,
        datetime_format="%Y-%m-%d",
    )

    run_messages = _get_team_run_messages(team)

    assert all("current time" not in str(message.content).lower() for message in run_messages.messages)


@pytest.mark.asyncio
async def test_async_datetime_context_matches_sync_message_semantics():
    team = _make_team_with_model(
        instructions="Keep answers concise.",
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d",
        timezone_identifier="UTC",
    )

    run_messages = await _aget_team_run_messages(team)
    datetime_message = run_messages.messages[-2]

    assert run_messages.system_message is not None
    assert "The current time is" not in str(run_messages.system_message.content)
    assert re.fullmatch(r"The current time is \d{4}-\d{2}-\d{2}\.", datetime_message.content)
    assert datetime_message.role == "user"
    assert datetime_message.add_to_agent_memory is False
    assert run_messages.messages[-1] is run_messages.user_message


def test_datetime_context_preserves_existing_custom_system_message_bypass():
    team = _make_team_with_model(system_message="Custom system", add_datetime_to_context=True)

    run_messages = _get_team_run_messages(team)

    assert all("current time" not in str(message.content).lower() for message in run_messages.messages)
