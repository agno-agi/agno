"""Tests for custom datetime_format on Team."""

import re
from unittest.mock import MagicMock

from agno.session import TeamSession
from agno.team._messages import get_system_message
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


def test_default_format_includes_full_datetime():
    """When no datetime_format is set, the full default datetime str is used."""
    team = _make_team_with_model(add_datetime_to_context=True)
    session = TeamSession(session_id="test-session")

    msg = get_system_message(team, session)

    assert msg is not None
    assert re.search(r"The current time is \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", msg.content)


def test_custom_date_only_format():
    """When datetime_format='%Y-%m-%d', only the date portion appears."""
    team = _make_team_with_model(
        add_datetime_to_context=True,
        datetime_format="%Y-%m-%d",
    )
    session = TeamSession(session_id="test-session")

    msg = get_system_message(team, session)

    assert msg is not None
    assert re.search(r"The current time is \d{4}-\d{2}-\d{2}\.", msg.content)


def test_custom_format_slash_style():
    """Custom format with slashes: %d/%m/%Y %H:%M."""
    team = _make_team_with_model(
        add_datetime_to_context=True,
        datetime_format="%d/%m/%Y %H:%M",
    )
    session = TeamSession(session_id="test-session")

    msg = get_system_message(team, session)

    assert msg is not None
    assert re.search(r"The current time is \d{2}/\d{2}/\d{4} \d{2}:\d{2}\.", msg.content)


def test_no_datetime_when_disabled():
    """When add_datetime_to_context is False, no datetime info is added."""
    team = _make_team_with_model(
        add_datetime_to_context=False,
        datetime_format="%Y-%m-%d",
    )
    session = TeamSession(session_id="test-session")
    msg = get_system_message(team, session)

    if msg is not None:
        assert "current time" not in msg.content.lower()
