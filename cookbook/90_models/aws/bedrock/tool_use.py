"""Run `uv pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.aws import AwsBedrock
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[WebSearchTools()],
    instructions="You are a helpful assistant that can use the following tools to answer questions.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Agent with forced tool_choice
# ---------------------------------------------------------------------------


def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Weather data placeholder for {city}: 72F and clear."


forced_tool_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    tools=[get_weather],
    tool_choice={"type": "function", "name": "get_weather"},
    tool_call_limit=1,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Whats happening in France?")

    # --- Sync + Streaming ---
    agent.print_response("Whats happening in France?", stream=True)

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))

    # --- Forced tool_choice ---
    forced_tool_agent.print_response("What is the weather in San Francisco?")
