"""
Custom Datetime Format
======================

Customize the datetime format injected into the team's system context.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
scheduler = Agent(
    name="Scheduler",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Schedule meetings and events based on the current time.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
scheduling_team = Team(
    name="Scheduling Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[scheduler],
    add_datetime_to_context=True,
    datetime_format="%B %d, %Y %I:%M %p %Z",  # Human-readable format (e.g., March 09, 2026 02:30 PM UTC)
    timezone_identifier="US/Eastern",
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    scheduling_team.print_response(
        "Schedule a standup meeting for 30 minutes from now.", stream=True
    )
