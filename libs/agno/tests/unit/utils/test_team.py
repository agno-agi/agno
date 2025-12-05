import uuid
from unittest.mock import patch

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.utils.team import get_member_id


@pytest.fixture
def team_show_member_responses_true():
    agent = Agent(name="Test Agent", model=OpenAIChat(id="gpt-4o-mini"))
    return Team(
        name="Test Team",
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        show_members_responses=True,
    )


@pytest.fixture
def team_show_member_responses_false():
    agent = Agent(name="Test Agent", model=OpenAIChat(id="gpt-4o-mini"))
    return Team(
        name="Test Team",
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        show_members_responses=False,
    )


def test_show_member_responses_fallback(team_show_member_responses_true):
    """Test fallback to team.show_members_responses"""
    with patch("agno.team.team.print_response") as mock:
        team_show_member_responses_true.print_response("test", stream=False)
        assert mock.call_args[1]["show_member_responses"] is True


def test_show_member_responses_override_false(team_show_member_responses_true):
    """Test parameter overrides team default"""
    with patch("agno.team.team.print_response") as mock:
        team_show_member_responses_true.print_response("test", stream=False, show_member_responses=False)
        assert mock.call_args[1]["show_member_responses"] is False


def test_show_member_responses_override_true(team_show_member_responses_false):
    """Test parameter overrides team default"""
    with patch("agno.team.team.print_response") as mock:
        team_show_member_responses_false.print_response("test", stream=False, show_member_responses=True)
        assert mock.call_args[1]["show_member_responses"] is True


def test_show_member_responses_streaming(team_show_member_responses_true):
    """Test parameter with streaming"""
    with patch("agno.team.team.print_response_stream") as mock:
        team_show_member_responses_true.print_response("test", stream=True, show_member_responses=False)
        assert mock.call_args[1]["show_member_responses"] is False


@pytest.mark.asyncio
async def test_async_show_member_responses_fallback(team_show_member_responses_true):
    """Test fallback to team.show_members_responses"""
    with patch("agno.team.team.aprint_response") as mock:
        await team_show_member_responses_true.aprint_response("test", stream=False)
        assert mock.call_args[1]["show_member_responses"] is True


@pytest.mark.asyncio
async def test_async_show_member_responses_override_false(team_show_member_responses_true):
    """Test parameter overrides team default"""
    with patch("agno.team.team.aprint_response") as mock:
        await team_show_member_responses_true.aprint_response("test", stream=False, show_member_responses=False)
        assert mock.call_args[1]["show_member_responses"] is False


@pytest.mark.asyncio
async def test_async_show_member_responses_override_true(team_show_member_responses_false):
    """Test parameter overrides team default"""
    with patch("agno.team.team.aprint_response") as mock:
        await team_show_member_responses_false.aprint_response("test", stream=False, show_member_responses=True)
        assert mock.call_args[1]["show_member_responses"] is True


@pytest.mark.asyncio
async def test_async_show_member_responses_streaming(team_show_member_responses_true):
    """Test parameter override with streaming"""
    with patch("agno.team.team.aprint_response_stream") as mock:
        await team_show_member_responses_true.aprint_response("test", stream=True, show_member_responses=False)
        assert mock.call_args[1]["show_member_responses"] is False


def test_get_member_id():
    member = Agent(name="Test Agent")
    assert get_member_id(member) == "test-agent"
    member = Agent(name="Test Agent", id="123")
    assert get_member_id(member) == "123"
    member = Agent(name="Test Agent", id=str(uuid.uuid4()))
    assert get_member_id(member) == "test-agent"
    member = Agent(id=str(uuid.uuid4()))
    assert get_member_id(member) == member.id

    member = Agent(name="Test Agent")
    inner_team = Team(name="Test Team", members=[member])
    assert get_member_id(inner_team) == "test-team"
    inner_team = Team(name="Test Team", id="123", members=[member])
    assert get_member_id(inner_team) == "123"
    inner_team = Team(name="Test Team", id=str(uuid.uuid4()), members=[member])
    assert get_member_id(inner_team) == "test-team"
    inner_team = Team(id=str(uuid.uuid4()), members=[member])
    assert get_member_id(inner_team) == inner_team.id
