"""
Cookbook: Capturing reasoning_content with ThinkingTools

This example demonstrates how to access and print the reasoning_content
when using ThinkingTools, in both streaming and non-streaming modes.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.thinking import ThinkingTools

print("\n=== Example 1: Using ThinkingTools in non-streaming mode ===\n")

# Create agent with ThinkingTools
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[ThinkingTools(add_instructions=True)],
    instructions=dedent("""\
        You are an expert problem-solving assistant with strong analytical skills! 🧠
        Use the think tool to organize your thoughts and approach problems step-by-step.
        \
    """),
    markdown=True,
)

# Run the agent (non-streaming) using agent.run() to get the response
print("Running with ThinkingTools (non-streaming)...")
response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

# Check reasoning_content from the response
print("\n--- reasoning_content from response ---")
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


print("\n\n=== Example 2: Processing stream to find final response ===\n")

# Create a fresh agent for streaming
streaming_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[ThinkingTools(add_instructions=True)],
    instructions=dedent("""\
        You are an expert problem-solving assistant with strong analytical skills! 🧠
        Use the think tool to organize your thoughts and approach problems step-by-step.
        \
    """),
    markdown=True,
)

# Process streaming responses and look for the final RunOutput
print("Running with ThinkingTools (streaming)...")
final_response = None
for event in streaming_agent.run(
    "What is the value of 5! (factorial)?",
    stream=True,
    stream_intermediate_steps=True,
):
    # Print content as it streams (optional)
    if hasattr(event, "content") and event.content:
        print(event.content, end="", flush=True)

    # The final event in the stream should be a RunOutput object
    if hasattr(event, "reasoning_content"):
        final_response = event

print("\n\n--- reasoning_content from final stream event ---")
if (
    final_response
    and hasattr(final_response, "reasoning_content")
    and final_response.reasoning_content
):
    print("✅ reasoning_content FOUND in final stream event")
    print(f"   Length: {len(final_response.reasoning_content)} characters")
    print("\n=== reasoning_content preview (streaming) ===")
    preview = final_response.reasoning_content[:1000]
    if len(final_response.reasoning_content) > 1000:
        preview += "..."
    print(preview)
else:
    print("❌ reasoning_content NOT FOUND in final stream event")
