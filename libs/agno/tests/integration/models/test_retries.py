"""Integration tests for model retry functionality."""

from unittest.mock import patch

import pytest

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus


def test_model_retry():
    """Test that model retries on failure and eventually succeeds."""
    model = OpenAIChat(
        id="gpt-4o-mini",
        retries=2,
    )
    agent = Agent(
        name="Model Retry Agent",
        model=model,
    )

    # Mock that fails once, then succeeds
    attempt_count = {"count": 0}
    original_invoke = model.invoke

    def mock_invoke(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 2:
            raise ModelProviderError(f"Simulated failure on attempt {attempt_count['count']}")
        return original_invoke(*args, **kwargs)

    with patch.object(model, "invoke", side_effect=mock_invoke):
        response = agent.run("Say hello")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed


def test_model_retry_delay():
    """Test that retry delay is constant between retries."""
    model = OpenAIChat(
        id="gpt-4o-mini",
        retries=2,
        delay_between_retries=2,
    )
    agent = Agent(
        name="Retry Delay Agent",
        model=model,
    )

    attempt_count = {"count": 0}
    original_invoke = model.invoke

    def mock_invoke(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 3:  # Fail first 2 attempts
            raise ModelProviderError("Simulated failure")
        # Succeed on 3rd attempt
        return original_invoke(*args, **kwargs)

    with patch.object(model, "invoke", side_effect=mock_invoke):
        with patch("agno.models.base.sleep") as mock_sleep:
            _ = agent.run("Say hello")

    # Check that sleep was called with constant delay
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == 2  # constant 2s delay
    assert mock_sleep.call_args_list[1][0][0] == 2  # constant 2s delay


def test_model_exponential_backoff():
    """Test that exponential backoff increases delay between retries."""
    model = OpenAIChat(
        id="gpt-4o-mini",
        retries=2,
        delay_between_retries=1,
        exponential_backoff=True,
    )
    agent = Agent(
        name="Exponential Backoff Agent",
        model=model,
    )

    attempt_count = {"count": 0}
    original_invoke = model.invoke

    def mock_invoke(*args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 3:  # Fail first 2 attempts
            raise ModelProviderError("Simulated failure")
        # Succeed on 3rd attempt
        return original_invoke(*args, **kwargs)

    with patch.object(model, "invoke", side_effect=mock_invoke):
        with patch("agno.models.base.sleep") as mock_sleep:
            _ = agent.run("Say hello")

    # Check that sleep was called with exponentially increasing delays
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == 1  # 2^0 * 1
    assert mock_sleep.call_args_list[1][0][0] == 2  # 2^1 * 1


@pytest.mark.asyncio
async def test_model_async_retry():
    """Test that model retries on async calls."""
    import types

    model = OpenAIChat(
        id="gpt-4o-mini",
        retries=2,
        delay_between_retries=0,
    )
    agent = Agent(
        name="Async Model Retry Agent",
        model=model,
    )

    attempt_count = {"count": 0}
    original_ainvoke = model.ainvoke

    async def mock_ainvoke(self, *args, **kwargs):
        attempt_count["count"] += 1
        if attempt_count["count"] < 2:
            raise ModelProviderError(f"Simulated failure on attempt {attempt_count['count']}")
        return await original_ainvoke(*args, **kwargs)

    # Properly bind the async method
    model.ainvoke = types.MethodType(mock_ainvoke, model)
    response = await agent.arun("Say hello")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed
