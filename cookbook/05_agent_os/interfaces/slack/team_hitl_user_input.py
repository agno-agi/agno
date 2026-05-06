"""
Slack Team HITL — User Input
============================

Support intake team with a Triage Agent and a Ticket Agent. The triage
agent investigates duplicates, the ticket agent creates tickets. The
ticket tool has `@tool(requires_user_input=True)` with fields the user
must fill in — Slack shows an input form when the agent tries to create
the ticket.

This demonstrates team-level HITL: member agent pauses for user input,
pause propagates to the team, Slack shows the form, user submits, team
continues.

Try in Slack:
  @bot open a ticket — users are seeing 500 errors on the checkout page

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from typing import Dict, List, Literal
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools import tool

# Stand-in ticket store

_TICKETS: List[Dict[str, str]] = [
    {
        "id": "SUP-001",
        "title": "Checkout 500 on empty cart",
        "status": "open",
        "component": "payments",
    },
    {
        "id": "SUP-002",
        "title": "Apple Pay button misaligned",
        "status": "open",
        "component": "mobile",
    },
]


# Read-only tool for triage agent


@tool
def search_tickets(query: str) -> List[Dict[str, str]]:
    """Search open tickets for duplicates. Call before creating a new ticket.

    Args:
        query: Search term to match in ticket titles.
    """
    q = query.lower()
    return [t for t in _TICKETS if q in t["title"].lower() and t["status"] == "open"]


# Ticket creation tool — pauses for user input


@tool(requires_user_input=True, user_input_fields=["priority", "component"])
def create_ticket(
    title: str,
    description: str,
    priority: Literal["P0", "P1", "P2", "P3"],
    component: str,
) -> str:
    """Create a support ticket. Priority and component are filled by the user.

    Args:
        title: Short ticket title. The agent drafts this.
        description: Detailed description. The agent drafts this.
        priority: One of P0/P1/P2/P3. User provides via Slack form.
        component: Team or subsystem. User provides via Slack form.
    """
    ticket_id = f"SUP-{uuid4().hex[:6].upper()}"
    _TICKETS.append(
        {"id": ticket_id, "title": title, "status": "open", "component": component}
    )
    return f"Ticket {ticket_id} created: {title} (priority={priority}, component={component})"


# Member agents

triage_agent = Agent(
    name="Triage Agent",
    role="Searches for duplicate tickets",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[search_tickets],
    instructions=[
        "You search for existing tickets that might be duplicates.",
        "Use search_tickets with key terms from the issue description.",
        "Report any potential duplicates to the team leader.",
    ],
)

ticket_agent = Agent(
    name="Ticket Agent",
    role="Creates support tickets",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[create_ticket],
    instructions=[
        "You create support tickets.",
        "Draft a clear title and description from the conversation.",
        "Pass empty strings for priority and component — the user fills those in Slack.",
    ],
)


# Team + storage + Slack interface

db = SqliteDb(
    db_file="tmp/team_hitl_user_input.db",
    session_table="team_sessions",
    approvals_table="approvals",
)

support_team = Team(
    id="support-team-hitl",
    name="Support Intake Team",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[triage_agent, ticket_agent],
    instructions=[
        "You handle support ticket intake.",
        "First, ask the Triage Agent to search for duplicates.",
        "If no duplicate, ask the Ticket Agent to create a ticket.",
        "The ticket creation will pause for the user to provide priority and component.",
    ],
    db=db,
    add_history_to_context=True,
    telemetry=False,
)

agent_os = AgentOS(
    description="Slack Team HITL — user input (ticket intake)",
    teams=[support_team],
    db=db,
    interfaces=[
        Slack(
            team=support_team,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="team_hitl_user_input:app", reload=True)
