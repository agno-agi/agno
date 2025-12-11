"""Integration tests for agent retry functionality."""

from unittest.mock import Mock, patch

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus


def test_agent_retry():
    """Test that agent retries on failure and eventually succeeds."""
    agent = Agent(
        name="Retry Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        retries=2,
        delay_between_retries=0,
    )

    # Mock that fails once, then succeeds
    attempt_count = {"count": 0}
    original_run = agent._run

    def mock_run(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 2:
            raise Exception(f"Simulated failure on attempt {attempt_count['count']}")
        return original_run(*args, **kwargs)

    with patch.object(agent, "_run", side_effect=mock_run):
        response = agent.run("Test message")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed


def test_agent_exponential_backoff():
    """Test that exponential backoff increases delay between retries."""
    agent = Agent(
        name="Retry Agent",
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

    with patch.object(agent, "_run", side_effect=mock_run):
        with patch("agno.agent.agent.time.sleep") as mock_sleep:
            _ = agent.run("Test message")

    # Check that sleep was called with exponentially increasing delays
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == 1  # 2^0 * 1
    assert mock_sleep.call_args_list[1][0][0] == 2  # 2^1 * 1


def test_agent_keyboard_interrupt_stops_retries():
    """Test that KeyboardInterrupt stops retries immediately."""
    agent = Agent(
        name="Retry Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        retries=5,
        delay_between_retries=0,
    )

    attempt_count = {"count": 0}

    def mock_run(*args, **kwargs):
        attempt_count["count"] += 1
        raise KeyboardInterrupt()

    with patch.object(agent, "_run", side_effect=mock_run):
        response = agent.run("Test message")

    # Should stop on first attempt without retrying
    assert attempt_count["count"] == 1
    assert response.status == RunStatus.cancelled
    assert response.content == "Operation cancelled by user"


@pytest.mark.asyncio
async def test_agent_async_retry():
    """Test that async agent retries on failure and eventually succeeds."""
    model = OpenAIChat(id="gpt-4o-mini")
    agent = Agent(
        name="Async Retry Agent",
        model=model,
        retries=2,
        delay_between_retries=0,
    )

    attempt_count = {"count": 0}
    original_aresponse = model.aresponse

    async def mock_aresponse(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 2:
            raise Exception(f"Simulated failure on attempt {attempt_count['count']}")
        return await original_aresponse(*args, **kwargs)

    # Mock the model's aresponse method so _arun's retry logic can still work
    with patch.object(model, "aresponse", side_effect=mock_aresponse):
        response = await agent.arun("Test message")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed
