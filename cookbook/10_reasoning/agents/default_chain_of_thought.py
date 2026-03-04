"""
OpenAI Default Chain Of Thought
===============================

Demonstrates fallback chain-of-thought and built-in reasoning in one script.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
manual_cot_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIChat(
        id="gpt-4o",
        max_tokens=1200,
    ),
    markdown=True,
)

default_cot_agent = Agent(
    model=OpenAIChat(id="gpt-4o", max_tokens=1200),
    reasoning=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    prompt = "Give me steps to write a python script for fibonacci series"

    print("=== Explicit reasoning_model fallback ===")
    manual_cot_agent.print_response(
        prompt,
        stream=True,
        show_full_reasoning=True,
    )

    print("\n=== Built-in reasoning=True ===")
    default_cot_agent.print_response(
        prompt,
        stream=True,
        show_full_reasoning=True,
    )
