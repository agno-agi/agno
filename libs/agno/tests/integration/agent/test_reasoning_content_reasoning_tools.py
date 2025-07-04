"""Test for reasoning_content generation in the Agno framework.

This test verifies that reasoning_content is properly populated in the RunResponse
when using ReasoningTools, in both streaming and non-streaming modes.
"""

from textwrap import dedent

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.reasoning import ReasoningTools


@pytest.mark.integration
def test_reasoning_content_from_reasoning_tools():
    """Test that reasoning_content is populated in non-streaming mode."""
    # Create an agent with ReasoningTools
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[ReasoningTools(add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"
    assert response.extra_data.reasoning_steps is not None
    assert len(response.extra_data.reasoning_steps) > 0


@pytest.mark.integration
def test_reasoning_content_from_reasoning_tools_streaming():
    """Test that reasoning_content is populated in streaming mode."""
    # Create a fresh agent for streaming test
    streaming_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[ReasoningTools(add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(streaming_agent.run("What is the value of 5! (factorial)?", stream=True, stream_intermediate_steps=True))

    # Check the agent's run_response directly after streaming is complete
    assert hasattr(streaming_agent, "run_response"), "Agent should have run_response after streaming"
    assert streaming_agent.run_response is not None, "Agent's run_response should not be None"
    assert hasattr(streaming_agent.run_response, "reasoning_content"), (
        "Response should have reasoning_content attribute"
    )
    assert streaming_agent.run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(streaming_agent.run_response.reasoning_content) > 0, "reasoning_content should not be empty"
    assert streaming_agent.run_response.extra_data.reasoning_steps is not None
    assert len(streaming_agent.run_response.extra_data.reasoning_steps) > 0
