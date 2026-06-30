"""
Task Mode
=============================

Demonstrates autonomous task decomposition and execution using TeamMode.tasks.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team, TeamMode

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Research requirements and gather references",
)

architect = Agent(
    name="Architect",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Design execution plans and task dependencies",
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Write concise delivery summaries",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
tasks_team = Team(
    name="Task Execution Team",
    members=[researcher, architect, writer],
    model=OpenAIResponses(id="gpt-5.2"),
    mode=TeamMode.tasks,
    instructions=[
        "Break goals into clear tasks with dependencies before starting.",
        "Assign each task to the most appropriate member.",
        "Track task completion and surface blockers explicitly.",
        "Provide a final consolidated summary with completed tasks.",
    ],
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tasks_team.print_response(
        "Plan a launch checklist for a new AI feature, including engineering, QA, and rollout tasks.",
        stream=True,
    )
