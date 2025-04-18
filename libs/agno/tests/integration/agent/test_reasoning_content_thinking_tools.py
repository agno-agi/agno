"""Test for reasoning_content generation with ThinkingTools.

This test verifies that reasoning_content is properly populated in the RunResponse
when using ThinkingTools, in both streaming and non-streaming modes.
"""

from textwrap import dedent

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.thinking import ThinkingTools


@pytest.mark.integration
def test_thinking_tools_non_streaming():
    """Test that reasoning_content is populated when using ThinkingTools in non-streaming mode."""
    # Create an agent with ThinkingTools
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[ThinkingTools(add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            Make sure to use the think tool to organize your thoughts.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
def test_thinking_tools_streaming():
    """Test that reasoning_content is populated when using ThinkingTools in streaming mode."""
    # Create an agent with ThinkingTools
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[ThinkingTools(add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            Make sure to use the think tool to organize your thoughts.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_intermediate_steps=True))

    # Check the agent's run_response directly after streaming is complete
    assert hasattr(agent, "run_response"), "Agent should have run_response after streaming"
    assert agent.run_response is not None, "Agent's run_response should not be None"
    assert hasattr(agent.run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert agent.run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(agent.run_response.reasoning_content) > 0, "reasoning_content should not be empty"
