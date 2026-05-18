"""
Slack HITL — Audit Flow
========================

Audit-ready incident response with tool_choice="required" — agent NEVER
asks questions in plain chat; every interaction goes through HITL tools.

Key patterns:
  1. tool_choice="required" — forces tool call every turn, no chat escape
  2. conclude_incident(stop_after_tool_call=True) — clean deterministic exit
  3. Explicit echo of captured values in final summary for audit trail

See hitl_incident_walkthrough.py for the basic version without these guards.

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/hitl_audit_flow.py

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from dataclasses import dataclass
from typing import Dict, List, Literal
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool
from agno.tools.websearch import WebSearchTools
from agno.tools.user_feedback import UserFeedbackTools

@dataclass
class Service:
    name: str
    region: str
    replicas: int
    runbook: str


_SERVICES: Dict[str, Service] = {
    "api-gateway": Service("api-gateway", "eu-west", 12, "rb/api-gateway"),
    "order-worker": Service("order-worker", "eu-west", 6, "rb/order-worker"),
    "user-profile": Service("user-profile", "us-east", 4, "rb/user-profile"),
}

_INCIDENTS: List[Dict[str, str]] = []


@tool
def lookup_service(service_name: str) -> str:
    """Return replica count, region, and runbook link for a service.

    Args:
        service_name: Logical service name (e.g. "api-gateway").
    """
    svc = _SERVICES.get(service_name)
    if not svc:
        known = ", ".join(_SERVICES) or "(none)"
        return f"No service {service_name!r}. Known: {known}."
    return f"{svc.name}: region={svc.region}, replicas={svc.replicas}, runbook={svc.runbook}"


@tool
def list_recent_incidents() -> List[Dict[str, str]]:
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
    return f"Rolled {svc.replicas} replicas of {svc.name} in {svc.region}. Reason: {reason!r}."


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
        priority: Severity tier. Requester picks via the Slack pause form.
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
    return f"Incident {incident_id} filed: {title} (priority={priority}, owner={on_call_owner}).\nSummary: {summary}"


# Required for clean exit when tool_choice="required" — otherwise loops forever
@tool(stop_after_tool_call=True)
def conclude_incident(summary: str) -> str:
    """Mark the incident as concluded. Call this AFTER file_incident_retro
    as the LAST action. The summary is shown verbatim to the operator
    and the run terminates here.

    Args:
        summary: Final human-readable summary shown to the operator.
    """
    return summary


db = SqliteDb(
    db_file="tmp/hitl_audit_flow.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Audit Flow",
    id="audit-flow-agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        UserFeedbackTools(),
        lookup_service,
        list_recent_incidents,
        run_diagnostic,
        restart_service,
        file_incident_retro,
        conclude_incident,
        WebSearchTools(),  # backend="auto" multi-backend fallback (more reliable than DuckDuckGo)
    ],
    instructions=[
        "You are an incident commander. Follow this flow:",
        "1) Triage: ask_user for severity + affected services",
        "2) Diagnose: run_diagnostic for engineer to execute",
        "3) Remediate: restart_service if needed",
        "4) Retro: file_incident_retro with summary",
        "5) Conclude: conclude_incident to end the run",
    ],
    markdown=True,
    tool_choice="required",  # Forces tool call every turn — no plain-chat escape
)

agent_os = AgentOS(
    description="Slack HITL — audit flow (tool_choice=required, no chat escape)",
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
    agent_os.serve(app="hitl_audit_flow:app", reload=True)
