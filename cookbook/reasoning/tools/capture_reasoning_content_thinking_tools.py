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

# Run the agent (non-streaming)
print("Running with ThinkingTools (non-streaming)...")
response = agent.print_response(
    "What is the sum of the first 10 natural numbers?", stream=False
)

# Print the reasoning_content
print("\n--- reasoning_content from agent.run_response ---")
if (
    hasattr(agent, "run_response")
    and agent.run_response
    and hasattr(agent.run_response, "reasoning_content")
    and agent.run_response.reasoning_content
):
    print(agent.run_response.reasoning_content)
else:
    print("No reasoning_content found in agent.run_response")


print("\n\n=== Example 2: Using ThinkingTools in streaming mode ===\n")

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

# Print response (which includes processing streaming responses)
print("Running with ThinkingTools (streaming)...")
streaming_agent.print_response(
    "What is the value of 5! (factorial)?",
    stream=True,
    stream_intermediate_steps=True,
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
