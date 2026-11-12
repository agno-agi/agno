"""
Control Who Runs, Approves, and Stops in Slack
==============================================

Map Slack users to AgentOS principals with users=, and name the Slack users who
may approve or stop anyone's run with approvers=.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, JWT_VERIFICATION_KEY, SLACK_OPERATOR_ID, SLACK_APPROVER_ID
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/access_control.py
Try in Slack: As the operator, ask "Cancel C-42 because pricing no longer fits."; approve as the approver, then try the same message from an unmapped account
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization
from agno.os.interfaces.slack import Slack
from agno.tools import tool


def required_env(name: str) -> str:
    value = getenv(name)
    if not value:
        raise ValueError(f"{name} is required for this example")
    return value


subscriptions = {"C-42": "active", "C-77": "active"}


@tool(requires_confirmation=True)
def cancel_subscription(customer_id: str, reason: str) -> str:
    """Cancel a subscription after an allowed Slack user approves the tool call."""
    if customer_id not in subscriptions:
        return f"No subscription found for {customer_id}."
    subscriptions[customer_id] = "cancelled"
    return f"Cancelled {customer_id}. Reason: {reason}"


# ---------------------------------------------------------------------------
# Create Access-Controlled Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-access-control-db",
    db_file="tmp/slack_access_control.db",
)

billing_agent = Agent(
    id="slack-access-billing-agent",
    name="Slack Billing Operations",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[cancel_subscription],
    instructions=[
        "Call cancel_subscription when asked to cancel a subscription.",
        "Do not ask for confirmation in chat; the tool requirement creates the Slack card.",
    ],
    markdown=True,
)

authz = Authorization(
    verification_keys=[required_env("JWT_VERIFICATION_KEY")],
    algorithm="HS256",
)
authz.define_role(
    "billing-operator",
    [
        "agents:slack-access-billing-agent:run",
        "agents:slack-access-billing-agent:read",
    ],
)
authz.assign("billing-operator-1", "billing-operator")

agent_os = AgentOS(
    id="slack-access-control-os",
    description="AgentOS mapping Slack users to principals and naming Slack approvers.",
    db=db,
    agents=[billing_agent],
    authorization=authz,
    interfaces=[
        Slack(
            agent=billing_agent,
            users={required_env("SLACK_OPERATOR_ID"): "billing-operator-1"},
            approvers=[required_env("SLACK_APPROVER_ID")],
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Access-Controlled Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
