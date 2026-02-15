"""
Multi-Run Session with Task Mode

Demonstrates that task state persists across multiple runs within the same
session. The first run creates and executes tasks; the second run can
reference prior task results.

Run: .venvs/demo/bin/python cookbook/03_teams/02_modes/tasks/10_multi_run_session.py
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
    role="Research specialist",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=["Provide concise, factual research summaries."],
)

analyst = Agent(
    name="Analyst",
    role="Data analyst who draws conclusions from research",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=["Analyze data and draw actionable conclusions."],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Research Analysis Team",
    mode=TeamMode.tasks,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[researcher, analyst],
    session_id="task-mode-demo-session",
    instructions=[
        "You are a research and analysis team leader.",
        "Decompose requests into research and analysis tasks.",
    ],
    show_members_responses=True,
    markdown=True,
    max_iterations=8,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("RUN 1: Initial research")
    print("=" * 60)
    response1 = team.run(
        "Research the pros and cons of microservices architecture "
        "vs monolithic architecture for a startup."
    )
    print(response1.content)

    print("\n" + "=" * 60)
    print("RUN 2: Follow-up request (same session)")
    print("=" * 60)
    response2 = team.run(
        "Based on the previous analysis, which architecture would you "
        "recommend for a team of 5 engineers building a B2B SaaS product? "
        "Provide a concrete recommendation."
    )
    print(response2.content)
