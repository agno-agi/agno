"""
Member-Level Approval (Case 2)
===============================

Approval tool lives on the member agent. The team has no approval tools.

Flow:
  1. User says "deploy services"
  2. Team delegates to Deployment Spec Collector member
  3. Member calls collect_deployment_specs -> member pauses -> team pauses
  4. User fills in the form fields (service, environment, version)
  5. Admin approves in Approvals page
  6. User clicks Continue Run -> member tool executes -> member returns result -> team responds
"""

from typing import Optional

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

DB_FILE = "tmp/member_level_approval.db"

session_db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)


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
    id="member-level-approval",
    name="Deployment Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[spec_collector],
    tools=[],
    instructions=[
        "Delegate to Deployment Spec Collector to gather deployment specs from the user.",
        "After the member returns, summarize the collected values.",
    ],
    add_history_to_context=True,
    store_member_responses=True,
    db=session_db,
    telemetry=False,
)

agent_os = AgentOS(
    id="member-level-approval-demo",
    description="Member-level approval: a member agent has a tool that requires admin approval",
    agents=[spec_collector],
    teams=[approval_team],
    db=session_db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="member_agent_level_approval:app", port=7777, reload=True)
