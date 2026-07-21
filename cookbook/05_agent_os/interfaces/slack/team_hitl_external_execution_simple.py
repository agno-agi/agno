"""
Slack Team HITL — External Execution (Simple)
==============================================

Simple port of AgentOS human_in_the_loop/team/external_tool_execution.py.

A team member's tool is marked for external execution. The run pauses and
Slack shows the tool name and arguments. The user executes the tool externally
and provides the result.

Try in Slack:
  @bot send an email to alice@example.com about the meeting

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
    db_file="tmp/team_hitl_external_execution_simple.db",
    session_table="team_sessions",
    approvals_table="approvals",
)


@tool(external_execution=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to someone. Executed externally by the user."""
    return ""


email_agent = Agent(
    name="EmailAgent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[send_email],
    instructions=[
        "You MUST call the send_email tool immediately when asked to send an email.",
        "Do NOT simulate or describe sending - use the tool.",
    ],
    db=db,
    telemetry=False,
)

team = Team(
    id="email-team-hitl-simple",
    name="CommunicationTeam",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[email_agent],
    instructions=["Delegate all email requests to the EmailAgent immediately."],
    db=db,
    add_history_to_context=True,
    telemetry=False,
)

agent_os = AgentOS(
    description="Slack Team HITL — external execution (simple)",
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
    agent_os.serve(app="team_hitl_external_execution_simple:app", reload=True)
