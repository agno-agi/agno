"""
Slack HITL — Incident Walkthrough
==================================

All four HITL pause types in one incident-response flow: user_feedback,
external_execution, confirmation, and user_input.

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from typing import Literal
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.user_feedback import UserFeedbackTools

_SERVICES = {
    "api-gateway": {"region": "eu-west", "replicas": 12, "runbook": "rb/api-gateway"},
    "order-worker": {"region": "eu-west", "replicas": 6, "runbook": "rb/order-worker"},
    "user-profile": {"region": "us-east", "replicas": 4, "runbook": "rb/user-profile"},
}

_INCIDENTS = []


@tool
def lookup_service(service_name: str) -> str:
    """Return replica count, region, and runbook link for a service.

    Args:
        service_name: Logical service name (e.g. "api-gateway").
    """
    svc = _SERVICES.get(service_name)
    if not svc:
        return f"No service {service_name!r}. Known: {', '.join(_SERVICES)}."
    return f"{service_name}: region={svc['region']}, replicas={svc['replicas']}, runbook={svc['runbook']}"


@tool
def list_recent_incidents() -> list[dict[str, str]]:
    """Return the most recent incidents filed in this session (newest first)."""
    return list(reversed(_INCIDENTS[-5:]))


@tool(external_execution=True)
def run_diagnostic(command: str, note: str = "") -> str:
    """Run a diagnostic command against production. The agent does NOT
    execute this — the on-call engineer runs it on their jumpbox and
    pastes the raw output back into the Slack card.

    Args:
        command: Exact shell / kubectl command to run.
        note: Optional short note about what the agent wants to see.
    """
    # Unreachable — external_execution=True pauses before the body runs.
    return f"[ran] {command} {note}".strip()


@tool(requires_confirmation=True)
def restart_service(service_name: str, reason: str) -> str:
    """Roll-restart every replica of a service. Destructive — briefly
    drops in-flight requests, so the Slack interface pauses for Approve
    / Deny before running.

    Args:
        service_name: Service to restart (matches lookup_service).
        reason: One-line justification, recorded in the audit log.
    """
    svc = _SERVICES.get(service_name)
    if not svc:
        return f"No service {service_name!r} — nothing restarted."
    return f"Rolled {svc['replicas']} replicas of {service_name} in {svc['region']}. Reason: {reason!r}."


@tool(requires_user_input=True, user_input_fields=["priority", "on_call_owner"])
def file_incident_retro(
    title: str,
    summary: str,
    priority: Literal["P0", "P1", "P2", "P3"],
    on_call_owner: str,
) -> str:
    """Open a retrospective ticket linking the incident timeline and
    action items. The agent drafts title + summary; the human supplies
    priority and the on-call owner who should drive the follow-up.

    Args:
        title: Short incident title (agent drafts).
        summary: Timeline + resolution notes (agent drafts).
        priority: One of "P0" | "P1" | "P2" | "P3".
        on_call_owner: Email / handle of the engineer who owns the retro.
    """
    incident_id = f"INC-{uuid4().hex[:6].upper()}"
    _INCIDENTS.append(
        {
            "id": incident_id,
            "title": title,
            "priority": priority,
            "owner": on_call_owner,
        }
    )
    return (
        f"Incident {incident_id} filed: {title} "
        f"(priority={priority}, owner={on_call_owner}).\nSummary: {summary}"
    )


db = SqliteDb(
    db_file="tmp/hitl_incident_walkthrough.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Incident Walkthrough",
    id="incident-walkthrough-agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        UserFeedbackTools(),
        lookup_service,
        list_recent_incidents,
        run_diagnostic,
        restart_service,
        file_incident_retro,
        DuckDuckGoTools(),
    ],
    instructions=[
        "You are an incident commander. Follow this flow:",
        "1) Triage: ask_user for severity + affected services",
        "2) Diagnose: run_diagnostic for engineer to execute",
        "3) Remediate: restart_service if needed",
        "4) Retro: file_incident_retro with summary",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — incident walkthrough (all four pause types)",
    agents=[agent],
    db=db,
    interfaces=[
        Slack(
            agent=agent,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_incident_walkthrough:app", reload=True)
