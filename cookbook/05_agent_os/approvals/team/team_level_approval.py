"""
Team-Level Approval (Case 1)
=============================

Approval tool lives on the team itself (not on a member agent).

Flow:
  1. User says "deploy payment to prod v2.5"
  2. Team calls approve_deployment -> run pauses
  3. Admin approves in Approvals page
  4. User clicks Continue Run -> tool executes -> team responds
"""

from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

DB_FILE = "tmp/team_level_approval.db"

session_db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)


@approval(type="required")
@tool(
    name="approve_deployment",
    description="Request human approval to deploy a service.",
    requires_confirmation=True,
)
def approve_deployment(service: str, environment: str, version: str) -> str:
    return (
        f"Deployment approved for service={service}, "
        f"environment={environment}, version={version}"
    )


approval_team = Team(
    id="team-level-approval",
    name="Deployment Approval Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[],
    tools=[approve_deployment],
    instructions=[
        "When the user asks to deploy, call approve_deployment with the service, environment, and version they provide.",
        "Do not ask for extra confirmation in chat. Just call the tool.",
    ],
    add_history_to_context=True,
    store_member_responses=True,
    db=session_db,
    telemetry=False,
)

agent_os = AgentOS(
    id="team-level-approval-demo",
    description="Team-level approval: the team has a tool that requires admin approval before executing",
    teams=[approval_team],
    db=session_db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="team_level_approval:app", port=7777, reload=True)
