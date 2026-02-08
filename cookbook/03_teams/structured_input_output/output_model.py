"""
Output Model
============

Demonstrates setting a dedicated model for final team response generation.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.websearch import WebSearchTools


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
itinerary_planner = Agent(
    name="Itinerary Planner",
    model=Claude(id="claude-sonnet-4-20250514"),
    description="You help people plan amazing vacations. Use the tools at your disposal to find latest information about the destination.",
    tools=[WebSearchTools()],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
travel_expert = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[itinerary_planner],
    output_model=OpenAIChat(id="o3-mini"),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    travel_expert.print_response("Plan a summer vacation in Paris", stream=True)
