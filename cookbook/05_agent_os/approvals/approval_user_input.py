"""
Approval User Input
=============================

Approval + user input HITL: @approval + @tool(requires_user_input=True).
"""

import os

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools import tool

DB_FILE = "tmp/approvals_test.db"


@approval(type="required")
@tool(requires_user_input=True, user_input_fields=["recipient", "note"])
def send_money(amount: float, recipient: str, note: str) -> str:
    """Send money to a recipient.

    Args:
        amount (float): The amount of money to send.
        recipient (str): The recipient to send money to (provided by user).
        note (str): A note to include with the transfer.

    Returns:
        str: Confirmation of the transfer.
    """
    return f"Sent ${amount} to {recipient}: {note}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[send_money],
    markdown=True,
    db=db,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Clean up from previous runs
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    os.makedirs("tmp", exist_ok=True)

    # Re-create after cleanup
    db = SqliteDb(
        db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
    )
    agent = Agent(
        model=OpenAIResponses(id="gpt-5-mini"),
        tools=[send_money],
        markdown=True,
        db=db,
    )
agent_os = AgentOS(
    description="Example app for tracing with multiple models, agents, teams, and workflows",
    agents=[
        agent,
    ],
    tracing=True,
    db=db,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="approval_user_input:app", reload=True)
