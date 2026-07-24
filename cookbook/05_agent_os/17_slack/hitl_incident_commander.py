"""
Coordinate a Compound Incident in Slack
=======================================

Combine user feedback, external execution, confirmation, and required user
input in one persisted incident run. tool_choice="required" keeps each turn
auditable; conclude_incident provides the explicit terminal tool.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/hitl_incident_commander.py
Try in Slack: Ask "Production api-gateway returns 500s in eu-west; help me triage."
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool
from agno.tools.user_feedback import UserFeedbackTools
from agno.tools.websearch import WebSearchTools


@dataclass
class Service:
    region: str
    replicas: int
    runbook: str


services = {
    "api-gateway": Service("eu-west", 12, "rb/api-gateway"),
    "order-worker": Service("eu-west", 6, "rb/order-worker"),
    "user-profile": Service("us-east", 4, "rb/user-profile"),
}
incidents: list[dict[str, str]] = []


@tool
def lookup_service(service_name: str) -> str:
    """Return deployment context for a production service."""
    service = services.get(service_name)
    if service is None:
        return (
            f"No service named {service_name}. Known services: {', '.join(services)}."
        )
    return (
        f"{service_name}: region={service.region}, replicas={service.replicas}, "
        f"runbook={service.runbook}"
    )


@tool(external_execution=True)
def run_diagnostic(command: str, note: str = "") -> str:
    """Represent a production command that the operator executes externally."""
    return f"{command}\nContext: {note}".strip()


@tool(requires_confirmation=True)
def restart_service(service_name: str, reason: str) -> str:
    """Restart a production service only after explicit approval."""
    service = services.get(service_name)
    if service is None:
        return f"No service named {service_name}; nothing restarted."
    return (
        f"Restarted {service.replicas} replicas of {service_name} "
        f"in {service.region}. Reason: {reason}"
    )


@tool(requires_user_input=True, user_input_fields=["priority", "on_call_owner"])
def file_incident_retro(
    title: str,
    summary: str,
    priority: Literal["P0", "P1", "P2", "P3"],
    on_call_owner: str,
) -> str:
    """File the retrospective after Slack collects priority and ownership."""
    incident_id = f"INC-{uuid4().hex[:6].upper()}"
    incidents.append(
        {
            "id": incident_id,
            "title": title,
            "priority": priority,
            "owner": on_call_owner,
        }
    )
    return (
        f"Filed {incident_id}: {title} "
        f"(priority={priority}, owner={on_call_owner}). Summary: {summary}"
    )


@tool(stop_after_tool_call=True)
def conclude_incident(summary: str) -> str:
    """End the required-tool run with a final operator-facing summary."""
    return summary


# ---------------------------------------------------------------------------
# Create Incident-command Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-hitl-incident-db",
    db_file="tmp/slack_hitl_incident.db",
)

incident_commander = Agent(
    id="slack-incident-commander",
    name="Slack Incident Commander",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[
        UserFeedbackTools(),
        lookup_service,
        run_diagnostic,
        restart_service,
        file_incident_retro,
        conclude_incident,
        WebSearchTools(),
    ],
    instructions=[
        "Drive the incident through five phases:",
        "1. Triage: call ask_user for severity and affected systems.",
        "2. Context: call lookup_service for the affected service.",
        "3. Diagnose: call run_diagnostic with the exact operator command in its "
        "command argument; Slack collects the external result.",
        "4. Remediate: call restart_service only when the evidence supports a restart.",
        "5. Retro: call file_incident_retro, then call conclude_incident.",
        "Do not ask in chat for values enforced by a tool requirement.",
        "Use web search only when internal service context does not explain the symptom.",
    ],
    tool_choice="required",
    markdown=True,
)

agent_os = AgentOS(
    id="slack-hitl-incident-os",
    description="AgentOS rendering all four run pause types through Slack.",
    db=db,
    agents=[incident_commander],
    interfaces=[Slack(agent=incident_commander)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Incident-command Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
