"""
Basic Broadcast Mode Example

Demonstrates `mode=broadcast` where the team leader sends the same task
to all member agents simultaneously, then synthesizes their responses
into a unified answer.

This is ideal for getting multiple perspectives on a single question.

"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

optimist = Agent(
    name="Optimist",
    role="Focuses on opportunities and positive outcomes",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You see the bright side of every situation.",
        "Focus on opportunities, growth potential, and positive trends.",
        "Be genuine -- not blindly positive -- but emphasize upsides.",
    ],
)

pessimist = Agent(
    name="Pessimist",
    role="Focuses on risks and potential downsides",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You focus on risks, challenges, and potential pitfalls.",
        "Identify what could go wrong and why caution is warranted.",
        "Be constructive -- raise real concerns, not unfounded fears.",
    ],
)

realist = Agent(
    name="Realist",
    role="Provides balanced, pragmatic analysis",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You provide balanced, evidence-based analysis.",
        "Weigh both opportunities and risks objectively.",
        "Focus on what is most likely to happen based on current data.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Multi-Perspective Team",
    mode=TeamMode.broadcast,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[optimist, pessimist, realist],
    instructions=[
        "You lead a multi-perspective analysis team.",
        "All members receive the same question and respond independently.",
        "Synthesize their viewpoints into a balanced summary that captures",
        "the key opportunities, risks, and most likely outcomes.",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "Should a startup pivot from B2C to B2B in a crowded market?",
        stream=True,
    )
