"""
Slack HITL — Incident Commander
===============================

Compound HITL cookbook showing all four pause types inside one realistic
incident-response flow. The agent is summoned during a production
incident and walks the on-call through triage, diagnostics, remediation,
and retrospective ticket filing — pausing whenever it needs the human
judgment only the requester has.

Pause points in this flow:
  1. user_feedback    → severity + affected subsystems (up front)
  2. external_execution → engineer runs a diagnostic command and pastes output
  3. confirmation     → restart a production service (destructive, gated)
  4. user_input       → retrospective ticket priority + on-call owner

Try in Slack:
  @bot prod api returning 500s in eu-west, help me triage

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
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.user_feedback import UserFeedbackTools

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
        service_name (str): Logical service name (e.g. "api-gateway").
    """
    svc = _SERVICES.get(service_name)
    if not svc:
        known = ", ".join(_SERVICES) or "(none)"
        return f"No service {service_name!r}. Known: {known}."
    return (
        f"{svc.name}: region={svc.region}, replicas={svc.replicas}, "
        f"runbook={svc.runbook}"
    )


@tool
def list_recent_incidents() -> List[Dict[str, str]]:
    """Return the most recent incidents filed in this session (newest first)."""
    return list(reversed(_INCIDENTS[-5:]))


# HITL tools — one per pause type


@tool(external_execution=True)
def run_diagnostic(command: str, note: str = "") -> str:
    """Run a diagnostic command against production (human executes and pastes output).

    Args:
        command (str): Shell or kubectl command to run.
        note (str): Optional context for the engineer.
    """
    return f"[ran] {command} {note}".strip()


@tool(requires_confirmation=True)
def restart_service(service_name: str, reason: str) -> str:
    """Roll-restart every replica of a service (requires approval).

    Args:
        service_name (str): Service to restart.
        reason (str): Justification for the restart.
    """
    svc = _SERVICES.get(service_name)
    if not svc:
        return f"No service {service_name!r} — nothing restarted."
    return (
        f"Rolled {svc.replicas} replicas of {svc.name} in {svc.region}. "
        f"Reason: {reason!r}."
    )


@tool(requires_user_input=True, user_input_fields=["priority", "on_call_owner"])
def file_incident_retro(
    title: str,
    summary: str,
    priority: Literal["P0", "P1", "P2", "P3"],
    on_call_owner: str,
) -> str:
    """File an incident retrospective ticket (human fills priority + owner).

    Args:
        title (str): Short incident title (agent drafts).
        summary (str): Timeline and resolution notes (agent drafts).
        priority (str): P0-P3 severity tier (human fills).
        on_call_owner (str): Engineer who owns the retro (human fills).
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


# Agent + AgentOS + Slack interface

db = SqliteDb(
    db_file="tmp/hitl_incident_commander.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Incident Commander",
    id="incident-commander-agent",
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
        "You are an incident commander. Drive every incident through these "
        "phases, pausing for the human when the framework does:",
        "  1) Triage — call ask_user once to collect severity (single-select: "
        "P0/P1/P2/P3) and affected subsystems (multi-select: api, db, cache, "
        "queue, frontend). Call lookup_service for each subsystem named.",
        "  2) Diagnose — call run_diagnostic with a concrete command (curl "
        "against a health endpoint, kubectl describe, etc.). The engineer "
        "pastes output back; use it to form a hypothesis.",
        "  3) Remediate — if the fix is a restart, call restart_service. "
        "Slack will gate this with Approve / Deny; do NOT ask for extra "
        "confirmation yourself.",
        "  4) Retro — once the incident is stable, call file_incident_retro "
        "with a clean title + summary. Priority and on-call owner come from "
        "the Slack pause form, not from you.",
        "Use DuckDuckGo only if lookup_service + list_recent_incidents give "
        "you nothing and the symptom is clearly a public library error.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — incident commander (all four pause types)",
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
    agent_os.serve(app="hitl_incident_commander:app", reload=True)
