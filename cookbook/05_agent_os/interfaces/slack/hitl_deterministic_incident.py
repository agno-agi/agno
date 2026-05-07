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
