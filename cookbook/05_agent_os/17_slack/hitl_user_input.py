"""
Collect Structured User Input in Slack
======================================

Draft a support ticket from the conversation, then pause with a Slack form so
the requester supplies the priority and owning component.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/hitl_user_input.py
Try in Slack: Ask "Open a ticket: checkout returns 500 for an empty cart."
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from typing import Literal
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool

tickets = [
    {
        "id": "SUP-A1B2C3",
        "title": "Checkout 500 when cart is empty",
        "status": "open",
    }
]


@tool
def search_existing_tickets(query: str) -> list[dict[str, str]]:
    """Return open tickets whose title contains the query."""
    normalized = query.lower()
    return [
        ticket
        for ticket in tickets
        if normalized in ticket["title"].lower() and ticket["status"] == "open"
    ]


@tool(requires_user_input=True, user_input_fields=["priority", "component"])
def create_support_ticket(
    title: str,
    description: str,
    priority: Literal["P0", "P1", "P2", "P3"],
    component: str,
) -> str:
    """Create a support ticket after Slack collects its routing fields."""
    ticket_id = f"SUP-{uuid4().hex[:6].upper()}"
    tickets.append({"id": ticket_id, "title": title, "status": "open"})
    return (
        f"Opened {ticket_id}: {title} "
        f"(priority={priority}, component={component}). Description: {description}"
    )


# ---------------------------------------------------------------------------
# Create User-input Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-hitl-user-input-db",
    db_file="tmp/slack_hitl_user_input.db",
)

support_agent = Agent(
    id="slack-support-intake-agent",
    name="Slack Support Intake",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[search_existing_tickets, create_support_ticket],
    instructions=[
        "Search for a duplicate before filing a ticket.",
        "If no duplicate exists, draft a concise title and description.",
        "Call create_support_ticket with the title and description.",
        "Priority and component are excluded from the model-visible schema; "
        "Slack collects them through the tool requirement form.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="slack-hitl-user-input-os",
    description="AgentOS collecting required tool fields through a Slack form.",
    db=db,
    agents=[support_agent],
    interfaces=[Slack(agent=support_agent)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run User-input Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
