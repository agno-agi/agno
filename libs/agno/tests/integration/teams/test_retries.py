"""Integration tests for team retry functionality."""

from unittest.mock import Mock, patch

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.team import Team


def test_team_retry():
    """Test that team retries on failure and eventually succeeds."""
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    team = Team(
        members=[member],
        name="Retry Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        retries=2,
        delay_between_retries=0,
    )

    # Mock that fails once, then succeeds
    attempt_count = {"count": 0}
    original_run = team._run

    def mock_run(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 2:
            raise Exception(f"Simulated failure on attempt {attempt_count['count']}")
        return original_run(*args, **kwargs)

    with patch.object(team, "_run", side_effect=mock_run):
        response = team.run("Test message")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed


def test_team_exponential_backoff():
    """Test that exponential backoff increases delay between retries."""
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    team = Team(
        members=[member],
        name="Retry Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        retries=2,
        delay_between_retries=1,
        exponential_backoff=True,
    )

    attempt_count = {"count": 0}

    def mock_run(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 3:  # Fail first 2 attempts (attempts 1 and 2)
            raise Exception("Simulated failure")
        # Succeed on 3rd attempt
        return Mock(status=RunStatus.completed)

    with patch.object(team, "_run", side_effect=mock_run):
        with patch("agno.team.team.time.sleep") as mock_sleep:
            _ = team.run("Test message")

    # Check that sleep was called with exponentially increasing delays
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == 1  # 2^0 * 1
    assert mock_sleep.call_args_list[1][0][0] == 2  # 2^1 * 1


def test_team_keyboard_interrupt_stops_retries():
    """Test that KeyboardInterrupt stops retries immediately."""
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    team = Team(
        members=[member],
        name="Retry Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        retries=5,
        delay_between_retries=0,
    )

    attempt_count = {"count": 0}

    def mock_run(*args, **kwargs):
        attempt_count["count"] += 1
        raise KeyboardInterrupt()

    with patch.object(team, "_run", side_effect=mock_run):
        response = team.run("Test message")

    # Should stop on first attempt without retrying
    assert attempt_count["count"] == 1
    assert response.status == RunStatus.cancelled
    assert response.content == "Operation cancelled by user"


@pytest.mark.asyncio
async def test_team_async_retry():
    """Test that async team retries on failure and eventually succeeds."""
    import types

    member = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    team = Team(
        members=[member],
        name="Async Retry Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        retries=2,
        delay_between_retries=0,
    )

    attempt_count = {"count": 0}
    original_arun = team._arun

    def mock_arun(self, *args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 2:
            raise Exception(f"Simulated failure on attempt {attempt_count['count']}")
        return original_arun(*args, **kwargs)

    # Properly bind the async method
    team._arun = types.MethodType(mock_arun, team)
    response = await team.arun("Test message")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed
