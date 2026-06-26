"""
Slack Team HITL — Team Tool Confirmation (Simple)
==================================================

Simple port of AgentOS human_in_the_loop/team/team_tool_confirmation.py.

The confirmation-required tool is on the team itself (not a member agent).
When the team leader decides to use the tool, the run pauses and Slack shows
an Approve/Deny card.

Try in Slack:
  @bot deploy auth-service to production

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools import tool

db = SqliteDb(
    db_file="tmp/team_hitl_team_tool_simple.db",
    session_table="team_sessions",
    approvals_table="approvals",
)


@tool(requires_confirmation=True)
def approve_deployment(environment: str, service: str) -> str:
    """Approve and execute a deployment to an environment.

    Args:
        environment: Target environment (staging, production)
        service: Service to deploy
    """
    return f"Deployment of {service} to {environment} approved and executed"


research_agent = Agent(
    name="ResearchAgent",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=["Research deployment readiness when asked."],
    db=db,
    telemetry=False,
)

team = Team(
    id="release-team-hitl-simple",
    name="ReleaseTeam",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[research_agent],
    tools=[approve_deployment],
    instructions=[
        "You manage releases. Use the approve_deployment tool to deploy services.",
        "Call the tool immediately when asked to deploy.",
    ],
    db=db,
    add_history_to_context=True,
    telemetry=False,
)

agent_os = AgentOS(
    description="Slack Team HITL — team tool confirmation (simple)",
    teams=[team],
    db=db,
    interfaces=[
        Slack(
            team=team,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="team_hitl_team_tool_simple:app", reload=True)
