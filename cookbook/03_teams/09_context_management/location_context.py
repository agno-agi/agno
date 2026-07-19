"""
Location Context
================

Demonstrates adding location and timezone context to team prompts.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
planner = Agent(
    name="Travel Planner",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Use location context in recommendations.",
        "Keep suggestions concise and practical.",
    ],
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
trip_planner_team = Team(
    name="Trip Planner",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[planner],
    add_location_to_context=True,
    timezone_identifier="America/Chicago",
    instructions=[
        "Plan recommendations around local time and season.",
        "Mention when local timing may affect itinerary decisions.",
    ],
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    trip_planner_team.print_response(
        "What should I pack for a weekend trip based on local time and climate context?",
        stream=True,
    )
