"""AgentOS + Team HITL with approvals.

The run should pause twice: (1) collect_deployment_specs fills missing fields
in the UI, (2) approve_deployment triggers the team confirmation pause.

If the team finishes with a long chat message asking for "confirmations" or
infrastructure details (Helm, rollout, migrations) but never calls
approve_deployment, the run completes without pause—that is what we avoid below.
"""

from typing import Optional

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

DB_FILE = "tmp/agent_os_team_hitl.db"

session_db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)


@approval(type="required")
@tool(
    name="collect_deployment_specs",
    description="Collect the only three deployment fields this demo supports: service, environment, version.",
    instructions=(
        "This demo supports exactly three inputs: service, environment, version. "
        "Never request any other field. If a value is unknown, leave it None so the HITL form asks for it."
    ),
    requires_user_input=True,
    user_input_fields=["service", "environment", "version"],
)
def collect_deployment_specs(
    service: Optional[str] = None,
    environment: Optional[str] = None,
    version: Optional[str] = None,
) -> str:
    return (
        "Deployment specs collected: "
        f"service={service}, environment={environment}, version={version}"
    )


@approval(type="required")
@tool(
    name="approve_deployment",
    description="Request human approval to deploy. This is the only approval step; calling it pauses the team in AgentOS.",
    instructions=(
        "Call this in the same turn once service, environment, and version are decided. "
        "Do not ask the user for extra confirmations in chat before this call. "
        "Chat questions do not pause the run; only this tool does."
    ),
    requires_confirmation=True,
)
def approve_deployment(service: str, environment: str, version: str) -> str:
    return (
        f"Deployment approved for service={service}, "
        f"environment={environment}, version={version}"
    )


spec_collector_agent = Agent(
    name="Deployment Spec Collector",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[collect_deployment_specs],
    instructions=[
        "Follow this strict protocol for every run: (1) call collect_deployment_specs exactly once first, (2) return only service, environment, version to the team.",
        "Always call collect_deployment_specs even when all three values appear in the user message. Pass known values from the user and None for unknown values.",
        "You are forbidden from asking for deployment details in free text. The only allowed missing-value collection method is collect_deployment_specs.",
        "After the tool returns, output only the final service/environment/version values in one short line and stop. Do not ask for confirmation, do not provide plans, and do not produce a final deployment status.",
        "If the user later corrects a value, call collect_deployment_specs again with corrected arguments before returning values.",
    ],
    # db=session_db,
    telemetry=False,
)

approval_team = Team(
    id="agent-os-hitl-team",
    name="Deployment Approval Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[spec_collector_agent],
    tools=[approve_deployment],
    instructions=[
        "Enforce a mandatory two-tool sequence on every run: member must call collect_deployment_specs, then team must call approve_deployment.",
        "Delegate to Deployment Spec Collector first on every run, even if the user already gave values.",
        "As soon as member output includes service, environment, version, call approve_deployment(service, environment, version) immediately in the same turn.",
        "Never complete with text before approve_deployment is called. A text-only completion is invalid for this demo.",
        "Forbidden: requesting any fields beyond service/environment/version, asking for free-form confirmations, or adding Helm/Kubernetes/rollout/migration checklists.",
        "Pause behavior requirement: collect_deployment_specs should trigger member HITL when needed, and approve_deployment must trigger team confirmation HITL.",
    ],
    add_history_to_context=True,
    # Persist member runs on the team run so HITL tool state reloads from the DB (matches AgentOS team router).
    store_member_responses=True,
    db=session_db,
    telemetry=False,
)

agent_os = AgentOS(
    id="agent-os-hitl-demo",
    description="AgentOS app where an agent collects deployment specs and a team approves the deployment",
    agents=[spec_collector_agent],
    teams=[approval_team],
    db=session_db,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="team_approval_user_input:app", port=7776, reload=True)