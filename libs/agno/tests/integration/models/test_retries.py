"""Integration tests for model retry functionality."""

from unittest.mock import Mock, patch

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus


def test_model_retry():
    """Test that model retries on failure and eventually succeeds."""
    model = OpenAIChat(
        id="gpt-4o-mini",
        max_retries=2,
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
            raise Exception(f"Simulated failure on attempt {attempt_count['count']}")
        return original_invoke(*args, **kwargs)

    with patch.object(model, "invoke", side_effect=mock_invoke):
        response = agent.run("Say hello")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed


def test_model_max_retries_exhausted():
    """Test that model fails after exhausting all retries."""
    model = OpenAIChat(
        id="gpt-4o-mini",
        max_retries=1,
    )
    agent = Agent(
        name="Model Retry Agent",
        model=model,
    )

    attempt_count = {"count": 0}

    def mock_invoke(*args, **kwargs):
        attempt_count["count"] += 1
        raise Exception("Simulated failure")

    with patch.object(model, "invoke", side_effect=mock_invoke):
        with pytest.raises(Exception, match="Simulated failure"):
            agent.run("Say hello")

    # Should attempt: initial + 1 retry = 2 attempts
    assert attempt_count["count"] == 2


def test_model_no_retries():
    """Test that model with max_retries=0 doesn't retry."""
    model = OpenAIChat(
        id="gpt-4o-mini",
        max_retries=0,
    )
    agent = Agent(
        name="Model No Retry Agent",
        model=model,
    )

    attempt_count = {"count": 0}

    def mock_invoke(*args, **kwargs):
        attempt_count["count"] += 1
        raise Exception("Simulated failure")

    with patch.object(model, "invoke", side_effect=mock_invoke):
        with pytest.raises(Exception, match="Simulated failure"):
            agent.run("Say hello")

    # Should attempt only once (no retries)
    assert attempt_count["count"] == 1


@pytest.mark.asyncio
async def test_model_async_retry():
    """Test that model retries on async calls."""
    import types

    model = OpenAIChat(
        id="gpt-4o-mini",
        max_retries=2,
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
            raise Exception(f"Simulated failure on attempt {attempt_count['count']}")
        return await original_ainvoke(*args, **kwargs)

    # Properly bind the async method
    model.ainvoke = types.MethodType(mock_ainvoke, model)
    response = await agent.arun("Say hello")

    # Should succeed on the 2nd attempt
    assert attempt_count["count"] == 2
    assert response is not None
    assert response.status == RunStatus.completed


def test_model_retry_with_agent_retry():
    """Test that model retries work in combination with agent retries."""
    model = OpenAIChat(
        id="gpt-4o-mini",
        max_retries=1,  # Model will retry once
    )
    agent = Agent(
        name="Combined Retry Agent",
        model=model,
        retries=1,  # Agent will also retry once
        delay_between_retries=0,
    )

    model_attempt_count = {"count": 0}
    agent_attempt_count = {"count": 0}
    original_invoke = model.invoke
    original_agent_run = agent._run

    def mock_invoke(*args, **kwargs):
        model_attempt_count["count"] += 1
        if model_attempt_count["count"] < 3:  # Fail first 2 model attempts
            raise Exception(f"Model failure on attempt {model_attempt_count['count']}")
        return original_invoke(*args, **kwargs)

    def mock_agent_run(*args, **kwargs):
        agent_attempt_count["count"] += 1
        return original_agent_run(*args, **kwargs)

    with patch.object(model, "invoke", side_effect=mock_invoke):
        with patch.object(agent, "_run", side_effect=mock_agent_run):
            response = agent.run("Say hello")

    # Model should attempt twice in first agent attempt (initial + 1 retry)
    # Then agent retries, and model attempts twice again (initial + 1 retry)
    # But we expect success on 3rd model attempt, which is in the 2nd agent attempt
    assert model_attempt_count["count"] >= 2
    assert response is not None
    assert response.status == RunStatus.completed
