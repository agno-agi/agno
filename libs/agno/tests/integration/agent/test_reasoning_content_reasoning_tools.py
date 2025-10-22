"""Test for reasoning_content generation in the Agno framework.

This test verifies that reasoning_content is properly populated in the RunOutput
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
    assert response.reasoning_steps is not None
    assert len(response.reasoning_steps) > 0


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

    # Consume all streaming responses and get the final response
    streaming_events = list(
        streaming_agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True)
    )

    # Get the final RunOutput from the last RunCompletedEvent
    from agno.run.agent import RunCompletedEvent

    completed_events = [event for event in streaming_events if isinstance(event, RunCompletedEvent)]
    assert len(completed_events) > 0, "Should have at least one RunCompletedEvent"

    # Use the last completed event as our response
    final_response = completed_events[-1]

    # Check that reasoning_content exists and is populated
    assert hasattr(final_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert final_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(final_response.reasoning_content) > 0, "reasoning_content should not be empty"
    assert final_response.reasoning_steps is not None
    assert len(final_response.reasoning_steps) > 0
