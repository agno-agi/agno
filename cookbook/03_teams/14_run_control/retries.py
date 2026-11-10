"""
Retries
=============================

Demonstrates team retry configuration for transient run errors.
"""

from agno.agent import Agent
from agno.team import Team
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
sarah = Agent(
    name="Sarah",
    role="Data Researcher",
    tools=[WebSearchTools()],
    instructions="Focus on gathering and analyzing data",
)

mike = Agent(
    name="Mike",
    role="Technical Writer",
    instructions="Create clear, concise summaries",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    members=[sarah, mike],
    retries=3,
    delay_between_retries=1,
    exponential_backoff=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response(
        "Search for latest news about the latest AI models",
        stream=True,
    )
