"""
Confirm a Destructive Tool in Slack
===================================

Look up a subscription, then pause the persisted run with Approve and Deny
actions before an irreversible cancellation tool executes.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/hitl_confirmation.py
Try in Slack: Ask "Cancel C-42 because pricing no longer fits."
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from dataclasses import dataclass

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool


@dataclass
class Subscription:
    customer_id: str
    plan: str
    monthly_rate: float
    status: str


subscriptions = {
    "C-42": Subscription("C-42", "Team", 399.0, "active"),
    "C-77": Subscription("C-77", "Enterprise", 2499.0, "active"),
}


@tool
def lookup_subscription(customer_id: str) -> str:
    """Return a customer's current subscription."""
    subscription = subscriptions.get(customer_id)
    if subscription is None:
        return f"No subscription found for {customer_id}."
    return (
        f"{subscription.customer_id}: plan={subscription.plan}, "
        f"rate=${subscription.monthly_rate}/month, status={subscription.status}"
    )


@tool(requires_confirmation=True)
def cancel_subscription(customer_id: str, reason: str) -> str:
    """Cancel a subscription after the operator approves the tool call."""
    subscription = subscriptions.get(customer_id)
    if subscription is None:
        return f"No subscription found for {customer_id}."
    subscription.status = "cancelled"
    return f"Cancelled {customer_id}. Reason: {reason}"


# ---------------------------------------------------------------------------
# Create Confirmation Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-hitl-confirmation-db",
    db_file="tmp/slack_hitl_confirmation.db",
)

billing_agent = Agent(
    id="slack-billing-ops-agent",
    name="Slack Billing Operations",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[lookup_subscription, cancel_subscription],
    instructions=[
        "Look up the subscription before trying to cancel it.",
        "Summarize the plan and price, then call cancel_subscription.",
        "Do not ask for confirmation in chat; the tool requirement creates the Slack card.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="slack-hitl-confirmation-os",
    description="AgentOS rendering a confirmation pause in Slack.",
    db=db,
    agents=[billing_agent],
    interfaces=[Slack(agent=billing_agent)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Confirmation Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
