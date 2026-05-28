"""Integration tests for team retry functionality."""

from unittest.mock import patch

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus
from agno.team import Team


def test_team_retry():
    """Test that team retries on failure and eventually succeeds."""
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    model = OpenAIChat(id="gpt-4o-mini")
    team = Team(
        members=[member],
        name="Retry Team",
        model=model,
        retries=2,
        delay_between_retries=0,
    )

    # Mock that fails once, then succeeds
    attempt_count = {"count": 0}
    original_response = model.response

    def mock_response(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 2:
            raise Exception(f"Simulated failure on attempt {attempt_count['count']}")
        return original_response(*args, **kwargs)

    # Mock the model's response method so _run's retry logic can still work
    with patch.object(model, "response", side_effect=mock_response):
        response = team.run("Test message")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed


def test_team_exponential_backoff():
    """Test that exponential backoff increases delay between retries."""
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    model = OpenAIChat(id="gpt-4o-mini")
    team = Team(
        members=[member],
        name="Retry Team",
        model=model,
        retries=2,
        delay_between_retries=1,
        exponential_backoff=True,
    )

    attempt_count = {"count": 0}
    original_response = model.response

    def mock_response(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 3:  # Fail first 2 attempts (attempts 1 and 2)
            raise Exception("Simulated failure")
        # Succeed on 3rd attempt
        return original_response(*args, **kwargs)

    # Mock the model's response method so _run's retry logic can still work
    with patch.object(model, "response", side_effect=mock_response):
        with patch("agno.team._run.time.sleep") as mock_sleep:
            _ = team.run("Test message")

    # Check that sleep was called with exponentially increasing delays
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == 1  # 2^0 * 1
    assert mock_sleep.call_args_list[1][0][0] == 2  # 2^1 * 1


def test_team_keyboard_interrupt_stops_retries():
    """Test that KeyboardInterrupt stops retries immediately."""
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    model = OpenAIChat(id="gpt-4o-mini")
    team = Team(
        members=[member],
        name="Retry Team",
        model=model,
        retries=5,
        delay_between_retries=0,
    )

    attempt_count = {"count": 0}

    def mock_response(*args, **kwargs):
        attempt_count["count"] += 1
        raise KeyboardInterrupt()

    # Mock the model's response method so _run's KeyboardInterrupt handling can work
    with patch.object(model, "response", side_effect=mock_response):
        response = team.run("Test message")

    # Should stop on first attempt without retrying
    assert attempt_count["count"] == 1
    assert response.status == RunStatus.cancelled
    assert response.content == "Operation cancelled by user"


@pytest.mark.asyncio
async def test_team_async_retry():
    """Test that async team retries on failure and eventually succeeds."""
    member = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    team = Team(
        members=[member],
        name="Async Retry Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        retries=2,
        delay_between_retries=0,
    )

    attempt_count = {"count": 0}
    original_aresponse = team.model.aresponse  # type: ignore

    async def mock_aresponse(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 2:
            raise Exception(f"Simulated failure on attempt {attempt_count['count']}")
        return await original_aresponse(*args, **kwargs)

    with patch.object(team.model, "aresponse", side_effect=mock_aresponse):
        response = await team.arun("Test message")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed
