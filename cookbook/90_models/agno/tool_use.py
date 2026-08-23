"""
Agno Gateway - tool use
=======================

Function calling through the Agno gateway. The OpenAI tools / tool_calls schema is
forwarded by the gateway; the selected model must support function calling.

Requires:
- AGNO_API_KEY
"""

import asyncio

from agno.agent import Agent
from agno.models.agno import Agno


def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to get the weather for.
    """
    return f"The weather in {city} is 22 degrees Celsius and sunny."


def get_activities(city: str) -> str:
    """Get popular activities for a city.

    Args:
        city: The city to get activities for.
    """
    return f"Popular activities in {city}: museums, riverside walks, and local cuisine."


agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    tools=[get_weather, get_activities],
    markdown=True,
)

if __name__ == "__main__":
    # --- Single tool ---
    agent.print_response("What's the weather in Tokyo?")

    # --- Multiple tools in one turn ---
    agent.print_response("What's the weather in Paris and what can I do there?")

    # --- Streaming with tools ---
    agent.print_response("What's the weather in Lisbon?", stream=True)

    # --- Async with tools ---
    asyncio.run(agent.aprint_response("What can I do in Rome?"))
