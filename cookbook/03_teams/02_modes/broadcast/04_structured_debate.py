"""Broadcast Mode

Same task is sent to every agent in the team. Moderator synthesizes the answer.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.team.team import Team, TeamMode

proponent = Agent(
    name="Proponent",
    role="Argue FOR the proposition. Be concise: thesis, 2-3 points, conclusion.",
    model=Claude(id="claude-opus-4-6"),
)

opponent = Agent(
    name="Opponent",
    role="Argue AGAINST the proposition. Be concise: thesis, 2-3 points, conclusion.",
    model=OpenAIResponses(id="gpt-5.2"),
)

team = Team(
    name="Structured Debate",
    mode=TeamMode.broadcast,
    model=Claude(id="claude-sonnet-4-6"),
    members=[proponent, opponent],
    instructions=[
        "Synthesize responses: highlight points for, against, areas of agreement, and the verdict"
    ],
    show_members_responses=True,
    markdown=True,
)

if __name__ == "__main__":
    team.print_response(
        "Remote work is better than in-office work for software teams.",
        stream=True,
        show_member_responses=True,
    )
