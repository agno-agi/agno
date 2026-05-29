"""
Broadcast Mode
=============================

Demonstrates delegating the same task to all members using TeamMode.broadcast.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team, TeamMode

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
product_manager = Agent(
    name="Product Manager",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Assess user and business impact",
)

engineer = Agent(
    name="Engineer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Assess technical feasibility and risks",
)

designer = Agent(
    name="Designer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Assess UX implications and usability",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
broadcast_team = Team(
    name="Broadcast Review Team",
    members=[product_manager, engineer, designer],
    model=OpenAIResponses(id="gpt-5.2"),
    mode=TeamMode.broadcast,
    instructions=[
        "Each member must independently evaluate the same request.",
        "Provide concise recommendations from your specialist perspective.",
        "Highlight tradeoffs and open risks clearly.",
    ],
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    broadcast_team.print_response(
        "Should we ship a beta autopilot feature next month? Provide your recommendation and risks.",
        stream=True,
    )
