"""
Broadcast Mode for Structured Debate

Demonstrates broadcast mode for a structured debate between agents with
opposing viewpoints. The team leader acts as moderator, synthesizing
arguments from both sides.

"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

proponent = Agent(
    name="Proponent",
    role="Argues in favor of the proposition",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You argue in favor of the given proposition.",
        "Present strong, logical arguments with supporting evidence.",
        "Acknowledge counterarguments but explain why your position is stronger.",
        "Structure your argument clearly: thesis, supporting points, conclusion.",
    ],
)

opponent = Agent(
    name="Opponent",
    role="Argues against the proposition",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You argue against the given proposition.",
        "Present strong, logical counterarguments with supporting evidence.",
        "Address the strongest pro-arguments and explain their weaknesses.",
        "Structure your argument clearly: thesis, counterpoints, conclusion.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Debate Team",
    mode=TeamMode.broadcast,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[proponent, opponent],
    instructions=[
        "You are a debate moderator.",
        "Both debaters receive the same proposition and argue their sides.",
        "After hearing both sides, provide:",
        "1. A summary of the strongest arguments from each side",
        "2. Areas of agreement (if any)",
        "3. Your assessment of which arguments are most compelling and why",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "Proposition: Remote work is better than in-office work for software teams.",
        stream=True,
    )
