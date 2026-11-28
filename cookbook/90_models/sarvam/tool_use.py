"""
Sarvam Tool Use
===============

Give the agent a local weather tool and let it call the function. A local tool
keeps the example fast and deterministic; a web search adds external latency.
"""

from agno.agent import Agent
from agno.models.sarvam import Sarvam

# ---------------------------------------------------------------------------
# Define the tool
# ---------------------------------------------------------------------------


def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"The weather in {city} is sunny and 24C."


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Sarvam(id="sarvam-105b"),
    tools=[get_weather],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the weather in Paris?")
