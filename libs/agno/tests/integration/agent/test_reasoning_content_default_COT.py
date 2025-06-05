"""Test for reasoning_content generation in different Agent configurations.

This test verifies that reasoning_content is properly populated in the RunResponse
for various Agent configurations, including:
- reasoning=True (with default model)
- reasoning_model=specified model
- streaming and non-streaming modes
"""

from textwrap import dedent

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat


@pytest.fixture(autouse=True)
def _show_output(capfd):
    """Force pytest to show print output for all tests in this module."""
    yield
    # Print captured output after test completes
    captured = capfd.readouterr()
    if captured.out:
        print(captured.out)
    if captured.err:
        print(captured.err)


@pytest.mark.integration
def test_reasoning_true_non_streaming():
    """Test that reasoning_content is populated with reasoning=True in non-streaming mode."""
    # Create an agent with reasoning=True
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        reasoning=True,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== Default reasoning model (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("=========================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
def test_reasoning_true_streaming():
    """Test that reasoning_content is populated with reasoning=True in streaming mode."""
    # Create an agent with reasoning=True
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        reasoning=True,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_intermediate_steps=True))

    # Print the reasoning_content when received
    if (
        hasattr(agent, "run_response")
        and agent.run_response
        and hasattr(agent.run_response, "reasoning_content")
        and agent.run_response.reasoning_content
    ):
        print("\n=== Default reasoning model (streaming) reasoning_content ===")
        print(agent.run_response.reasoning_content)
        print("====================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert hasattr(agent, "run_response"), "Agent should have run_response after streaming"
    assert agent.run_response is not None, "Agent's run_response should not be None"
    assert hasattr(agent.run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert agent.run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(agent.run_response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
def test_reasoning_model_non_streaming():
    """Test that reasoning_content is populated with a specified reasoning_model in non-streaming mode."""
    # Create an agent with a specified reasoning_model
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        reasoning_model=OpenAIChat(id="gpt-4o"),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== Custom reasoning model (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("==========================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
def test_reasoning_model_streaming():
    """Test that reasoning_content is populated with a specified reasoning_model in streaming mode."""
    # Create an agent with a specified reasoning_model
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        reasoning_model=OpenAIChat(id="gpt-4o"),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_intermediate_steps=True))

    # Print the reasoning_content when received
    if (
        hasattr(agent, "run_response")
        and agent.run_response
        and hasattr(agent.run_response, "reasoning_content")
        and agent.run_response.reasoning_content
    ):
        print("\n=== Custom reasoning model (streaming) reasoning_content ===")
        print(agent.run_response.reasoning_content)
        print("=====================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert hasattr(agent, "run_response"), "Agent should have run_response after streaming"
    assert agent.run_response is not None, "Agent's run_response should not be None"
    assert hasattr(agent.run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert agent.run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(agent.run_response.reasoning_content) > 0, "reasoning_content should not be empty"
