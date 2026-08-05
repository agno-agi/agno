"""
OpenRouteService Tools - Accurate distance and travel time between locations

This example shows how to use OpenRouteServiceTools to get real, routed distances
and travel times instead of letting the language model guess. It geocodes place
names automatically, so you can ask about cities directly (e.g. Berlin to Amsterdam)
for driving, cycling or walking.

Prerequisites:
1. Create a free account at https://account.heigit.org and generate an API token
   (no credit card required).
2. Set the ORS_API_KEY environment variable, or pass api_key="..." to the tool.

Note:
- OpenRouteService does not support public transit / train routing. Use the
  driving-car, cycling-* or foot-* profiles, or GoogleMapTools for transit.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.openrouteservice import OpenRouteServiceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[OpenRouteServiceTools()],
    instructions=[
        "Use the routing tools to answer distance and travel time questions accurately.",
        "Never estimate distances yourself, always call a tool.",
        "Report distances in kilometers and durations in hours and minutes.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Driving distance ===")
    agent.print_response(
        "How far is it to drive from Berlin to Amsterdam, and how long does it take?",
        stream=True,
    )

    print("\n=== Cycling distance ===")
    agent.print_response(
        "What is the cycling distance and time from Berlin to Amsterdam?",
        stream=True,
    )

    print("\n=== Distance matrix ===")
    agent.print_response(
        "Give me a driving distance matrix between Berlin, Amsterdam and Paris.",
        stream=True,
    )
