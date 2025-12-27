"""
Cookbook: Working with reasoning_content in Agents

This example demonstrates how to access and print the reasoning_content
when using either reasoning=True or setting a specific reasoning_model.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

print("\n=== Example 1: Using reasoning=True (default COT) ===\n")

# Create agent with reasoning=True (default model COT)
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)

# Run the agent (non-streaming)
print("Running with reasoning=True (non-streaming)...")
response = agent.run("What is the sum of the first 10 natural numbers?")

# Print the reasoning_content
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


print("\n\n=== Example 2: Using a custom reasoning_model ===\n")

# Create agent with a specific reasoning_model
agent_with_reasoning_model = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIChat(id="gpt-4o"),  # Should default to manual COT
    markdown=True,
)

# Run the agent (non-streaming)
print("Running with reasoning_model specified (non-streaming)...")
response = agent_with_reasoning_model.run(
    "What is the sum of the first 10 natural numbers?"
)

# Print the reasoning_content
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


print("\n\n=== Example 3: Processing stream with reasoning=True ===\n")

# Create a fresh agent for streaming
streaming_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)

# Process streaming responses and look for the final RunOutput
print("Running with reasoning=True (streaming)...")
final_response = None
for event in streaming_agent.run(
    "What is the value of 5! (factorial)?",
    stream=True,
    stream_events=True,
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


print("\n\n=== Example 4: Processing stream with reasoning_model ===\n")

# Create a fresh agent with reasoning_model for streaming
streaming_agent_with_model = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

# Process streaming responses and look for the final RunOutput
print("Running with reasoning_model specified (streaming)...")
final_response_with_model = None
for event in streaming_agent_with_model.run(
    "What is the value of 7! (factorial)?",
    stream=True,
    stream_events=True,
):
    # Print content as it streams (optional)
    if hasattr(event, "content") and event.content:
        print(event.content, end="", flush=True)

    # The final event in the stream should be a RunOutput object
    if hasattr(event, "reasoning_content"):
        final_response_with_model = event

print("\n\n--- reasoning_content from final stream event (reasoning_model) ---")
if (
    final_response_with_model
    and hasattr(final_response_with_model, "reasoning_content")
    and final_response_with_model.reasoning_content
):
    print("✅ reasoning_content FOUND in final stream event")
    print(f"   Length: {len(final_response_with_model.reasoning_content)} characters")
    print("\n=== reasoning_content preview (streaming with reasoning_model) ===")
    preview = final_response_with_model.reasoning_content[:1000]
    if len(final_response_with_model.reasoning_content) > 1000:
        preview += "..."
    print(preview)
else:
    print("❌ reasoning_content NOT FOUND in final stream event")
