"""
Slack HITL — User Input
=======================

Support agent that opens engineering tickets from Slack chatter. The agent
extracts `title` and `description` from the conversation, but `priority`
and `component` are fields the requester must fill in — they're listed in
`user_input_fields`, so Slack pauses with an input form before the tool
runs. Read-only tools help the agent avoid duplicates and search web
docs before filing.

Try in Slack:
  @bot open a ticket — checkout page throws 500 when the cart is empty

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from typing import Dict, List, Literal
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools

# Stand-in ticket store — replace with Jira / Linear client


_TICKETS: List[Dict[str, str]] = [
    {
        "id": "SUP-A1B2C3",
        "title": "Checkout 500 when cart empty",
        "status": "open",
        "component": "payments",
    },
    {
        "id": "SUP-F7E5D9",
        "title": "Apple Pay button misaligned on iOS",
        "status": "open",
        "component": "mobile-web",
    },
]


# Read-only helpers


@tool
def search_existing_tickets(query: str) -> List[Dict[str, str]]:
    """Return open tickets whose title contains the query (case-insensitive).
    Use this before filing a new ticket to avoid duplicates.

    Args:
        query: Free-text fragment to match in existing ticket titles.
    """
    q = query.lower()
    return [t for t in _TICKETS if q in t["title"].lower() and t["status"] == "open"]


# Ticket creation — pauses for priority + component


@tool(requires_user_input=True, user_input_fields=["priority", "component"])
def create_support_ticket(
    title: str,
    description: str,
    priority: Literal["P0", "P1", "P2", "P3"],
    component: str,
) -> str:
    """Open a support / engineering ticket.

    Args:
        title: Short ticket title. The agent drafts this from the chat.
        description: Longer body. The agent drafts this from the chat.
        priority: One of "P0" | "P1" | "P2" | "P3". Requester picks.
        component: Subsystem or team name the ticket should be routed to.
    """
    ticket_id = f"SUP-{uuid4().hex[:6].upper()}"
    _TICKETS.append(
        {"id": ticket_id, "title": title, "status": "open", "component": component}
    )
    return (
        f"Ticket {ticket_id} opened: {title} "
        f"(priority={priority}, component={component}).\n"
        f"Description: {description}"
    )


# Agent + AgentOS + Slack interface

db = SqliteDb(
    db_file="tmp/hitl_user_input.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Support Intake Agent",
    id="support-intake-agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        search_existing_tickets,
        DuckDuckGoTools(),
        create_support_ticket,
    ],
    instructions=[
        "You are a Slack support-intake assistant.",
        "Workflow: (1) call search_existing_tickets with a fragment of the "
        "issue description — if you find a live duplicate, surface it and ask "
        "the user whether to still open a new one; (2) if the issue looks like "
        "a known library error, optionally use DuckDuckGo for a link to docs; "
        "(3) call create_support_ticket with a concise title and clean multi-"
        "line description. Pass empty strings for priority and component — the "
        "user will supply those via the Slack pause form.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — user input (support ticket intake)",
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
    agent_os.serve(app="hitl_user_input:app", reload=True)
