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
    print(response.reasoning_content)
else:
    print("No reasoning_content found in response")


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
    print(response.reasoning_content)
else:
    print("No reasoning_content found in response")


print("\n\n=== Example 3: Streaming with reasoning=True ===\n")

# Create a fresh agent for streaming
streaming_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)

# Print response (which includes processing streaming responses)
print("Running with reasoning=True (streaming)...")
streaming_agent.print_response(
    "What is the value of 5! (factorial)?",
    stream=True,
    show_full_reasoning=True,
)

# Access reasoning_content from the agent's run_response after streaming
print("\n--- reasoning_content from agent.run_response after streaming ---")
if (
    hasattr(streaming_agent, "run_response")
    and streaming_agent.run_response
    and hasattr(streaming_agent.run_response, "reasoning_content")
    and streaming_agent.run_response.reasoning_content
):
    print(streaming_agent.run_response.reasoning_content)
else:
    print("No reasoning_content found in agent.run_response after streaming")


print("\n\n=== Example 4: Streaming with reasoning_model ===\n")

# Create a fresh agent with reasoning_model for streaming
streaming_agent_with_model = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

# Print response (which includes processing streaming responses)
print("Running with reasoning_model specified (streaming)...")
streaming_agent_with_model.print_response(
    "What is the value of 5! (factorial)?",
    stream=True,
    show_full_reasoning=True,
)

# Access reasoning_content from the agent's run_response after streaming
print("\n--- reasoning_content from agent.run_response after streaming ---")
if (
    hasattr(streaming_agent_with_model, "run_response")
    and streaming_agent_with_model.run_response
    and hasattr(streaming_agent_with_model.run_response, "reasoning_content")
    and streaming_agent_with_model.run_response.reasoning_content
):
    print(streaming_agent_with_model.run_response.reasoning_content)
else:
    print("No reasoning_content found in agent.run_response after streaming")
