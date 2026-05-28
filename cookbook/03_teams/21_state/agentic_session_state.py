"""
Agentic Session State
=====================

Demonstrates team and member agentic state updates on shared session state.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agents.db")

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
shopping_agent = Agent(
    name="Shopping List Agent",
    role="Manage the shopping list",
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    add_session_state_to_context=True,
    enable_agentic_state=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    members=[shopping_agent],
    session_state={"shopping_list": []},
    db=db,
    add_session_state_to_context=True,
    enable_agentic_state=True,
    description="You are a team that manages a shopping list and chores",
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response("Add milk, eggs, and bread to the shopping list")
    team.print_response("I picked up the eggs, now what's on my list?")
    print(f"Session state: {team.get_session_state()}")
