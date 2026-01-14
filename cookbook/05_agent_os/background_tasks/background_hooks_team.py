"""
Example: Background Hooks with Teams in AgentOS

This example demonstrates how to use background hooks with a Team.
Background hooks execute after the API response is sent, making them non-blocking.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.hooks.decorator import hook
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run.team import TeamRunOutput
from agno.team import Team


@hook(run_in_background=True)
async def log_team_result(run_output: TeamRunOutput, team: Team) -> None:
    """
    Background post-hook that logs team execution results.
    Runs after the response is sent to the user.
    """
    print(f"[Background Hook] Team '{team.name}' completed run: {run_output.run_id}")
    print(f"[Background Hook] Content length: {len(str(run_output.content))} chars")

    # Simulate async work (e.g., storing metrics)
    await asyncio.sleep(2)
    print("[Background Hook] Team metrics logged successfully!")


# Create team members
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You research topics and provide factual information.",
)

writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You write clear, engaging content based on research.",
)

# Create the team with background hooks
content_team = Team(
    id="content-team",
    name="ContentTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, writer],
    instructions="Coordinate between researcher and writer to create content.",
    db=AsyncSqliteDb(db_file="tmp/team.db"),
    post_hooks=[log_team_result],
    markdown=True,
)

# Create AgentOS with background hooks enabled
agent_os = AgentOS(
    teams=[content_team],
    run_hooks_in_background=True,
)

app = agent_os.get_app()

# Example request:
# curl -X POST http://localhost:7777/teams/content-team/runs \
#   -F "message=Write a short paragraph about Python" \
#   -F "stream=false"

if __name__ == "__main__":
    agent_os.serve(app="background_hooks_team:app", port=7777, reload=True)
