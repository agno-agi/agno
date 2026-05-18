"""
Slack HITL — Audit Flow
========================

Incident response with tool_choice="required" — every turn must call a
tool, no plain-chat escape. Uses conclude_incident for clean exit.

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
from agno.tools.user_feedback import UserFeedbackTools
from agno.tools.websearch import WebSearchTools

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
        service_name (str): Logical service name (e.g. "api-gateway").
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
    return f"Rolled {svc['replicas']} replicas of {service_name} in {svc['region']}. Reason: {reason!r}."


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
    return f"Incident {incident_id} filed: {title} (priority={priority}, owner={on_call_owner}).\nSummary: {summary}"


# Required for clean exit when tool_choice="required" — otherwise loops forever
@tool(stop_after_tool_call=True)
def conclude_incident(summary: str) -> str:
    """Mark the incident as concluded and terminate the run.

    Args:
        summary (str): Final summary shown to the operator.
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
