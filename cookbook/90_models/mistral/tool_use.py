"""Mistral tool use example with a custom function tool."""

import asyncio
import json

from agno.agent import Agent
from agno.models.mistral import MistralChat
from agno.tools import tool

# ---------------------------------------------------------------------------
# Define a tool
# ---------------------------------------------------------------------------


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city name to get weather for.
    """
    weather_data = {
        "Paris": {"temp": 18, "condition": "cloudy", "humidity": 65},
        "London": {"temp": 14, "condition": "rainy", "humidity": 80},
        "Tokyo": {"temp": 22, "condition": "sunny", "humidity": 50},
        "New York": {"temp": 20, "condition": "partly cloudy", "humidity": 55},
    }
    data = weather_data.get(city, {"temp": 20, "condition": "unknown", "humidity": 50})
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=MistralChat(id="mistral-large-latest"),
    tools=[get_weather],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What is the weather in Paris and Tokyo?")

    # --- Async ---
    asyncio.run(agent.aprint_response("What is the weather in London and New York?"))
