"""Test for reasoning_content generation

This script tests whether reasoning_content is properly populated in the RunResponse
when using ReasoningTools. It tests both streaming and non-streaming modes.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.reasoning import ReasoningTools

"""Test function to verify reasoning_content is populated in RunResponse."""
print("\n=== Testing reasoning_content generation ===\n")

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

# Test 1: Non-streaming mode
print("Running with stream=False...")
response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

# Check reasoning_content
if hasattr(response, "reasoning_content") and response.reasoning_content:
    print("✅ reasoning_content FOUND in non-streaming response")
    print(f"   Length: {len(response.reasoning_content)} characters")
    print("\n=== reasoning_content preview (non-streaming) ===")
    preview = response.reasoning_content[:1000]
    if len(response.reasoning_content) > 1000:
        preview += "..."
    print(preview)
else:
    print("❌ reasoning_content NOT FOUND in non-streaming response")

# Test 2: Streaming mode with a fresh agent
print("\nRunning with stream=True...")

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
_ = list(
    streaming_agent.run(
        "What is the value of 5! (factorial)?",
        stream=True,
        stream_intermediate_steps=True,
    )
)

# Check the agent's run_response directly after streaming is complete
if hasattr(streaming_agent, "run_response") and streaming_agent.run_response:
    if (
        hasattr(streaming_agent.run_response, "reasoning_content")
        and streaming_agent.run_response.reasoning_content
    ):
        print("✅ reasoning_content FOUND in agent's run_response after streaming")
        print(
            f"   Length: {len(streaming_agent.run_response.reasoning_content)} characters"
        )
        print("\n=== reasoning_content preview (streaming) ===")
        preview = streaming_agent.run_response.reasoning_content[:1000]
        if len(streaming_agent.run_response.reasoning_content) > 1000:
            preview += "..."
        print(preview)
    else:
        print("❌ reasoning_content NOT FOUND in agent's run_response after streaming")
else:
    print("❌ Agent's run_response is not accessible after streaming")
