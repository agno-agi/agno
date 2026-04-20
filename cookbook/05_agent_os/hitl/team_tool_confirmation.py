"""AgentOS HITL: Team-Level Tool Confirmation

AgentOS equivalent of cookbook/03_teams/20_human_in_the_loop/team_tool_confirmation.py

The confirmation-required tool is on the team itself (not a member agent).
When the team leader decides to use the tool, the run pauses until the
client confirms or rejects.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/hitl/team_tool_confirmation.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/agent_os_hitl.db",
    session_table="hitl_team_tool_sessions",
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def approve_deployment(environment: str, service: str) -> str:
    """Approve and execute a deployment to an environment.

    Args:
        environment (str): Target environment (staging, production)
        service (str): Service to deploy
    """
    return f"Deployment of {service} to {environment} approved and executed"


# ---------------------------------------------------------------------------
# Create members
# ---------------------------------------------------------------------------

research_agent = Agent(
    name="Research Agent",
    role="Researches deployment readiness",
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create team
# ---------------------------------------------------------------------------

team = Team(
    id="hitl-team-tool-confirmation",
    name="Release Team",
    members=[research_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[approve_deployment],
    instructions="You manage releases. Use the approve_deployment tool to deploy services. Call it immediately when asked to deploy.",
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="hitl-team-tool-confirmation",
    description="AgentOS HITL: team-level tool requiring confirmation",
    teams=[team],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="team_tool_confirmation:app", port=7776, reload=True)
