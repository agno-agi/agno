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
    # When a valid UUID id is provided, it should be returned even if name exists
    agent_uuid = str(uuid.uuid4())
    member = Agent(name="Test Agent", id=agent_uuid)
    assert get_member_id(member) == agent_uuid
    member = Agent(id=str(uuid.uuid4()))
    assert get_member_id(member) == member.id

    member = Agent(name="Test Agent")
    inner_team = Team(name="Test Team", members=[member])
    assert get_member_id(inner_team) == "test-team"
    inner_team = Team(name="Test Team", id="123", members=[member])
    assert get_member_id(inner_team) == "123"
    # When a valid UUID id is provided, it should be returned even if name exists
    team_uuid = str(uuid.uuid4())
    inner_team = Team(name="Test Team", id=team_uuid, members=[member])
    assert get_member_id(inner_team) == team_uuid
    inner_team = Team(id=str(uuid.uuid4()), members=[member])
    assert get_member_id(inner_team) == inner_team.id


def test_get_member_id_uuid_priority():
    """Test that get_member_id prioritizes id over name when id is a valid UUID."""
    # Agent with UUID id and name should return the UUID
    agent_uuid = "47ecf9eb-4dcf-4090-8e5b-ba5d20f98e14"
    member = Agent(name="写作助手", id=agent_uuid)
    assert get_member_id(member) == agent_uuid

    # Agent with non-UUID id should return url-safe id
    member = Agent(name="写作助手", id="my-custom-id")
    assert get_member_id(member) == "my-custom-id"

    # Agent with only name should return url-safe name
    member = Agent(name="写作助手")
    assert get_member_id(member) == "写作助手"

    # Team with UUID id and name should return the UUID
    team_uuid = str(uuid.uuid4())
    agent = Agent(name="Helper")
    team = Team(name="Test Team", id=team_uuid, members=[agent])
    assert get_member_id(team) == team_uuid

    # Team with non-UUID id should return url-safe id
    team = Team(name="Test Team", id="my-team-id", members=[agent])
    assert get_member_id(team) == "my-team-id"

    # Agent with only a UUID id (no name) should return the UUID
    only_uuid = str(uuid.uuid4())
    member = Agent(id=only_uuid)
    assert get_member_id(member) == only_uuid
