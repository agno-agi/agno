"""
Custom Team System Message
=========================

Demonstrates setting a custom system message, role, and including the team
name in context.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
coach = Agent(
    name="Coaching Agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Offer practical, concise improvements.",
        "Keep advice actionable and realistic.",
    ],
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
coaching_team = Team(
    name="Team Coach",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[coach],
    instructions=["Focus on high-leverage behavior changes."],
    system_message=(
        "You are a performance coach for remote teams. "
        "Every answer must end with one concrete next action."
    ),
    system_message_role="system",
    add_name_to_context=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    coaching_team.print_response(
        "How should my team improve meeting quality this week?",
        stream=True,
    )
