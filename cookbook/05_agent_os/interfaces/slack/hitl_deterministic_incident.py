"""
Slack HITL — Deterministic Incident Commander
=============================================

Compound HITL cookbook with three determinism patterns layered on top of
the basic incident commander flow. Demonstrates how to run an incident
response via Slack with strong audit-trail guarantees and a clean exit.

Patterns demonstrated:
  1. Forced structured pauses — agent ALWAYS uses HITL pause tools
     (run_diagnostic, ask_user, etc.), NEVER asks via plain chat. This is
     enforced at the API level via tool_choice="required" and reinforced
     by explicit system-prompt rules + multishot examples.
  2. Echo of captured user_input values — bot's reply to the operator
     surfaces the priority + on_call_owner that were captured via the
     Slack pause form, so the audit trail is visible in chat.
  3. Clean termination — a conclude_incident tool decorated with
     stop_after_tool_call=True gives the agent a deterministic exit
     point. Without it, tool_choice="required" would loop forever after
     the retro is filed.

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/hitl_deterministic_incident.py

Try in Slack:
  @bot prod api returning 500s in eu-west, P1 incident

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Literal
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool
from agno.tools.user_feedback import UserFeedbackTools
from agno.tools.websearch import WebSearchTools

# Stand-in incident registry + service catalog


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


# Read-only context tools


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


# HITL tools — one per pause type


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


# Termination tool — gives the agent a clean exit when tool_choice="required"
# is set. Without this, the agent would loop forever after file_incident_retro
# because the API forces a tool call every turn and the agent has nothing else
# meaningful to call.


@tool(stop_after_tool_call=True)
def conclude_incident(summary: str) -> str:
    """Mark the incident as concluded. Call this AFTER file_incident_retro
    as the LAST action. The summary is shown verbatim to the operator
    and the run terminates here.

    Args:
        summary: Final human-readable summary shown to the operator.
    """
    return summary


# Agent + AgentOS + Slack interface

db = SqliteDb(
    db_file="tmp/hitl_deterministic_incident.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Deterministic Incident Commander",
    id="deterministic-incident-commander-agent",
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
        WebSearchTools(),
    ],
    instructions=[
        "You are an incident commander. Drive every incident through these "
        "phases, pausing for the human when the framework does:",
        "  1) Triage — call ask_user once to collect severity (single-select: "
        "P0/P1/P2/P3) and affected subsystems (multi-select: api, db, cache, "
        "queue, frontend). Call lookup_service for each subsystem named.",
        "  2) Diagnose — call run_diagnostic with a concrete command "
        "(curl against a health endpoint, kubectl describe, etc.). The "
        "engineer pastes output back; use it to form a hypothesis.",
        "  3) Remediate — if the fix is a restart, call restart_service. "
        "Slack will gate this with Approve / Deny; do NOT ask for extra "
        "confirmation yourself.",
        "  4) Retro — once the incident is stable, call "
        "file_incident_retro with a clean title + summary. Priority and "
        "on-call owner come from the Slack pause form, not from you.",
        "  5) Conclude — after file_incident_retro returns, call "
        "conclude_incident with a final summary. This is your LAST "
        "action; the run ends here.",
        "Use WebSearchTools only if lookup_service + list_recent_incidents "
        "give you nothing and the symptom is clearly a public library error.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — deterministic incident commander (audit-friendly compound flow)",
    agents=[agent],
    db=db,
    interfaces=[
        Slack(
            agent=agent,
            reply_to_mentions_only=True,
            token=os.environ["SLACK_BOT_TOKEN"],
            signing_secret=os.environ["SLACK_SIGNING_SECRET"],
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_deterministic_incident:app", reload=True)
