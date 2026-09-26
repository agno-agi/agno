"""
TogetherLink Tool Use
=====================

Cookbook example for `togetherlink/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.togetherlink import TogetherLink


def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: Name of the city.
    """
    return f"It is 22 degrees Celsius and sunny in {city}."


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=TogetherLink(id="zai-org/GLM-5.3-Flash"),
    tools=[get_weather],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync + Streaming ---
    agent.print_response("What is the weather in Paris?", stream=True)

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("What is the weather in Tokyo?", stream=True))
