import pytest

from agno.agent import Agent, RunResponse
from agno.exceptions import ModelProviderError
from agno.models.litellm import LiteLLM


def _assert_metrics(response: RunResponse):
    """Helper function to assert metrics are present and valid"""
    input_tokens = response.metrics.get("input_tokens", [])
    output_tokens = response.metrics.get("output_tokens", [])
    total_tokens = response.metrics.get("total_tokens", [])

    assert sum(input_tokens) > 0
    assert sum(output_tokens) > 0
    assert sum(total_tokens) > 0
    assert sum(total_tokens) == sum(input_tokens) + sum(output_tokens)

    assert response.metrics.get("completion_tokens_details") is not None
    assert response.metrics.get("prompt_tokens_details") is not None


def test_basic():
    """Test basic functionality with LiteLLM"""
    agent = Agent(model=LiteLLM(id="gpt-4o"), markdown=True,
                  telemetry=False, monitoring=False)

    # Get the response
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == [
        "system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    """Test streaming functionality with LiteLLM"""
    agent = Agent(model=LiteLLM(id="gpt-4o"), markdown=True,
                  telemetry=False, monitoring=False)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert isinstance(response, RunResponse)
        assert response.content is not None

    _assert_metrics(agent.run_response)


@pytest.mark.asyncio
async def test_async_basic():
    """Test async functionality with LiteLLM"""
    agent = Agent(model=LiteLLM(id="gpt-4o"), markdown=True,
                  telemetry=False, monitoring=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == [
        "system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    """Test async streaming functionality with LiteLLM"""
    agent = Agent(model=LiteLLM(id="gpt-4o"), markdown=True,
                  telemetry=False, monitoring=False)

    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    async for response in response_stream:
        assert isinstance(response, RunResponse)
        assert response.content is not None
    _assert_metrics(agent.run_response)


def test_exception_handling():
    """Test error handling with invalid model ID"""
    agent = Agent(model=LiteLLM(id="nonexistent-model"),
                  markdown=True, telemetry=False, monitoring=False)

    # Should raise an exception for invalid model
    with pytest.raises(ModelProviderError) as exc:
        agent.run("Share a 2 sentence horror story")

    assert exc.value.model_name == "LiteLLM"
    assert exc.value.model_id == "nonexistent-model"


def test_with_memory():
    """Test LiteLLM with agent memory"""
    agent = Agent(
        model=LiteLLM(id="gpt-4o"),
        add_history_to_messages=True,
        num_history_responses=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    # First interaction
    response1 = agent.run("My name is John Smith")
    assert response1.content is not None

    # Second interaction should remember the name
    response2 = agent.run("What's my name?")
    assert "John Smith" in response2.content

    # Verify memories were created
    assert len(agent.memory.messages) == 5
    assert [m.role for m in agent.memory.messages] == [
        "system", "user", "assistant", "user", "assistant"]

    # Test metrics structure and types
    _assert_metrics(response2)
