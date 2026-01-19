"""Test for reasoning_content generation

This script tests whether reasoning_content is properly populated in the RunOutput
when using ReasoningTools. It tests both streaming and non-streaming modes.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.reasoning import ReasoningTools

"""Test function to verify reasoning_content is populated in RunOutput."""
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

# Process streaming responses to find the final one
print("\n\n=== Test 2: Processing stream to find final response ===\n")

# Create another fresh agent
streaming_agent_alt = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[ReasoningTools(add_instructions=True)],
    instructions=dedent("""\
        You are an expert problem-solving assistant with strong analytical skills! 🧠
        Use step-by-step reasoning to solve the problem.
        \
    """),
)

# Process streaming responses and look for the final RunOutput
final_response = None
for event in streaming_agent_alt.run(
    "What is the value of 3! (factorial)?",
    stream=True,
    stream_events=True,
):
    # The final event in the stream should be a RunOutput object
    if hasattr(event, "reasoning_content"):
        final_response = event

print("--- Checking reasoning_content from final stream event ---")
if (
    final_response
    and hasattr(final_response, "reasoning_content")
    and final_response.reasoning_content
):
    print("✅ reasoning_content FOUND in final stream event")
    print(f"   Length: {len(final_response.reasoning_content)} characters")
    print("\n=== reasoning_content preview (final stream event) ===")
    preview = final_response.reasoning_content[:1000]
    if len(final_response.reasoning_content) > 1000:
        preview += "..."
    print(preview)
else:
    print("❌ reasoning_content NOT FOUND in final stream event")
