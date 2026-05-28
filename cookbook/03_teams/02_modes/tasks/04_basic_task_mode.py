"""
Basic Task Mode Example

Demonstrates a team in `mode=tasks` where the team leader autonomously:
1. Decomposes a user goal into discrete tasks
2. Assigns tasks to the most suitable member agent
3. Executes tasks by delegating to members
4. Collects results and provides a final summary

Run: .venvs/demo/bin/python cookbook/03_teams/02_modes/tasks/04_basic_task_mode.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    role="Research specialist who finds information on topics",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a research specialist.",
        "When given a topic, provide a clear, concise summary of key facts.",
        "Always cite what you know and be honest about limitations.",
    ],
)

writer = Agent(
    name="Writer",
    role="Content writer who creates well-structured text",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a skilled content writer.",
        "Take provided information and craft it into polished, engaging text.",
        "Use clear structure with headers and bullet points when appropriate.",
    ],
)

critic = Agent(
    name="Critic",
    role="Quality reviewer who provides constructive feedback",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "You are a constructive critic.",
        "Review content for accuracy, clarity, and completeness.",
        "Provide specific, actionable feedback.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

content_team = Team(
    name="Content Creation Team",
    mode=TeamMode.tasks,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[researcher, writer, critic],
    instructions=[
        "You are a content creation team leader.",
        "Break down the user's request into research, writing, and review tasks.",
        "Assign each task to the most appropriate team member.",
        "After all tasks are complete, synthesize the results into a final response.",
    ],
    show_members_responses=True,
    markdown=True,
    max_iterations=10,
    debug_mode=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    content_team.print_response(
        "Write a short briefing on the current state of quantum computing, "
        "covering recent breakthroughs, key challenges, and potential near-term applications."
    )
