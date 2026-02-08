"""
Input Formats
=============================

Demonstrates different input formats accepted by team run methods.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Research topics",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Research Team",
    members=[researcher],
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Dict input
    team.print_response(
        {"role": "user", "content": "Explain AI"},
        stream=True,
    )

    # List input
    team.print_response(
        ["What is machine learning?", "Keep it brief."],
        stream=True,
    )

    # Messages list input
    team.print_response(
        [{"role": "user", "content": "What is deep learning?"}],
        stream=True,
    )
