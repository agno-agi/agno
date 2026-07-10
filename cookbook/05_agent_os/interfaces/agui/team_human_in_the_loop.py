"""
Team Human in the Loop
======================

Demonstrates team with member tool requiring confirmation.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="/tmp/agui_team_hitl.db")


@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email."""
    return f"Email sent to {to} with subject '{subject}'."


researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer factual questions concisely. You do not send emails.",
    markdown=True,
)

emailer = Agent(
    name="Emailer",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[send_email],
    instructions=(
        "You send emails. Call send_email with the recipient, a subject, and a body; "
        "if the user did not give a subject or body, draft a reasonable one. "
        "After a confirmed send, briefly say the email was sent. "
        "If the user declines, do not resend; acknowledge it was cancelled."
    ),
    markdown=True,
)

support_team = Team(
    name="support_team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[researcher, emailer],
    db=db,
    instructions="Route email requests to the Emailer and factual questions to the Researcher.",
    add_history_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    teams=[support_team],
    interfaces=[AGUI(team=support_team, prefix="/team_human_in_the_loop")],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="team_human_in_the_loop:app", port=9001, reload=True)
