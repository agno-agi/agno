"""
Slack HITL — Confirmation
=========================

Billing ops agent that can cancel customer subscriptions. Cancellation is
irreversible, so the destructive tool is wrapped with
`@tool(requires_confirmation=True)` — Slack pauses with Approve / Deny
buttons before the cancellation runs. The agent also has read-only
lookup tools so it can show the customer's context before asking to
confirm.

Try in Slack:
  @bot cancel C-42's subscription — they've been asking all week, churn reason pricing

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from dataclasses import dataclass
from typing import Dict, List

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool

# Stand-in billing data — replace with real Stripe / internal client


@dataclass
class Subscription:
    customer_id: str
    plan: str
    monthly_rate: float
    status: str
    seat_count: int


_FAKE_DB: Dict[str, Subscription] = {
    "C-42": Subscription("C-42", "Team", 399.0, "active", 12),
    "C-77": Subscription("C-77", "Enterprise", 2499.0, "active", 120),
    "C-91": Subscription("C-91", "Starter", 49.0, "past_due", 3),
}


# Read-only tools — no HITL needed, agent uses these to build context


@tool
def lookup_customer(customer_id: str) -> str:
    """Return the customer's current subscription summary.

    Args:
        customer_id: Customer identifier (e.g. "C-42").
    """
    sub = _FAKE_DB.get(customer_id)
    if not sub:
        return f"No record for {customer_id}."
    return (
        f"{sub.customer_id}: plan={sub.plan}, rate=${sub.monthly_rate}/mo, "
        f"status={sub.status}, seats={sub.seat_count}."
    )


@tool
def list_active_subscriptions() -> List[Dict[str, str]]:
    """Return every active subscription. Useful when the user refers to
    a customer by something other than their id."""
    return [
        {"customer_id": s.customer_id, "plan": s.plan, "status": s.status}
        for s in _FAKE_DB.values()
        if s.status == "active"
    ]


# Destructive tool — pauses for human approval


@tool(requires_confirmation=True)
def cancel_subscription(customer_id: str, reason: str) -> str:
    """Cancel a customer subscription. Irreversible — stops billing and
    revokes access at the end of the current cycle.

    Args:
        customer_id: Customer identifier (e.g. "C-42").
        reason: Short human-readable cancellation reason.
    """
    sub = _FAKE_DB.get(customer_id)
    if not sub:
        return f"No record for {customer_id} — nothing to cancel."
    sub.status = "cancelled"
    return f"Subscription for {customer_id} cancelled. Reason logged: {reason!r}."


# Agent + AgentOS + Slack interface

db = SqliteDb(
    db_file="tmp/hitl_confirmation.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Billing Ops Agent",
    id="billing-ops-agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[lookup_customer, list_active_subscriptions, cancel_subscription],
    instructions=[
        "You are a billing operations assistant embedded in Slack.",
        "Before calling cancel_subscription, use lookup_customer (or "
        "list_active_subscriptions if the user didn't give an id) so you can "
        "show plan + rate in your summary.",
        "When ready to cancel, call cancel_subscription with the customer_id "
        "and a short reason drawn from the user's message. Do NOT ask the user "
        "for final confirmation yourself — the Slack interface will pause the "
        "run and show an Approve / Deny card.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — confirmation (subscription cancellation)",
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
    agent_os.serve(app="hitl_confirmation:app", reload=True)
