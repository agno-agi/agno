"""AgentOS HITL: Confirmation Rejected

AgentOS equivalent of cookbook/03_teams/20_human_in_the_loop/confirmation_rejected.py

Same setup as confirmation_required but demonstrates the rejection flow.
When the client rejects the tool call the model acknowledges the rejection
and responds accordingly.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/hitl/confirmation_rejected.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/agent_os_hitl.db",
    session_table="hitl_rejection_sessions",
)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def delete_user_account(username: str) -> str:
    """Permanently delete a user account and all associated data.

    Args:
        username (str): Username of the account to delete
    """
    return f"Account {username} has been permanently deleted"


# ---------------------------------------------------------------------------
# Create members
# ---------------------------------------------------------------------------

admin_agent = Agent(
    name="Admin Agent",
    role="Handles account administration tasks",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[delete_user_account],
    instructions=(
        "You MUST call the delete_user_account tool immediately when asked to "
        "delete an account. Do NOT refuse or ask for confirmation yourself - "
        "the tool handles confirmation."
    ),
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create team
# ---------------------------------------------------------------------------

team = Team(
    id="hitl-rejection-team",
    name="Admin Team",
    members=[admin_agent],
    instructions="Delegate all account administration requests to the Admin Agent immediately.",
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    telemetry=False,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="hitl-confirmation-rejected",
    description="AgentOS HITL: rejecting a member agent tool call",
    agents=[admin_agent],
    teams=[team],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="confirmation_rejected:app", port=7776, reload=True)
