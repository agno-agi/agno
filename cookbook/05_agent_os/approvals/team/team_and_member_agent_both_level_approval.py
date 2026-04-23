"""
Both Member + Team Level Approval (Case 3)
============================================

Approval tools on both the member agent AND the team.
This creates a two-pause flow with two separate admin approvals.

Flow:
  1. User says "deploy services"
  2. Team delegates to Deployment Spec Collector member
  3. Member calls collect_deployment_specs -> member pauses -> team pauses (PAUSE 1)
  4. User fills in the form, admin approves
  5. User clicks Continue Run -> member tool executes -> member returns values to team
  6. Team calls approve_deployment with the collected values -> team pauses (PAUSE 2)
  7. Admin approves in Approvals page
  8. User clicks Continue Run -> team tool executes -> team responds with final result
"""

from typing import Optional

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

DB_FILE = "tmp/both_level_approval.db"

session_db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)


# --- Member agent tool: collects deployment specs via user input form ---


@approval(type="required")
@tool(
    name="collect_deployment_specs",
    description="Collect deployment fields from the user via a form.",
    requires_user_input=True,
    user_input_fields=["service", "environment", "version"],
)
def collect_deployment_specs(
    service: Optional[str] = None,
    environment: Optional[str] = None,
    version: Optional[str] = None,
) -> str:
    return (
        f"Deployment specs collected: "
        f"service={service}, environment={environment}, version={version}"
    )


# --- Team tool: requires confirmation before deploying ---


@approval(type="required")
@tool(
    name="approve_deployment",
    description="Request human approval to deploy a service. Call after collecting specs from the member.",
    requires_confirmation=True,
)
def approve_deployment(service: str, environment: str, version: str) -> str:
    return (
        f"Deployment approved for service={service}, "
        f"environment={environment}, version={version}"
    )


spec_collector = Agent(
    name="Deployment Spec Collector",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[collect_deployment_specs],
    instructions=[
        "Call collect_deployment_specs to gather deployment details from the user.",
        "Always call it even if the user provided some values. Pass known values and None for missing ones.",
        "After the tool returns, output only the final values in one short line.",
    ],
    telemetry=False,
)

approval_team = Team(
    id="both-level-approval",
    name="Deployment Approval Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[spec_collector],
    tools=[approve_deployment],
    instructions=[
        "Delegate to Deployment Spec Collector first to gather specs via its form.",
        "Once the member returns service, environment, and version, call approve_deployment immediately.",
        "Do not ask for extra confirmation in chat. Use the tools.",
    ],
    add_history_to_context=True,
    store_member_responses=True,
    db=session_db,
    telemetry=False,
)

agent_os = AgentOS(
    id="both-level-approval-demo",
    description="Both-level approval: member collects specs (approval 1), team approves deployment (approval 2)",
    agents=[spec_collector],
    teams=[approval_team],
    db=session_db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        app="team_and_member_agent_both_level_approval:app", port=7777, reload=True
    )
