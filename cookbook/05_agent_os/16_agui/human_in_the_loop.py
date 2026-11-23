"""
Confirm a Backend Tool over AG-UI
=================================

Pause a real server-side tool call with requires_confirmation, stream the
requirement to the frontend, and resume the persisted run after the user
accepts or rejects it.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/human_in_the_loop.py
Try: Ask to email ops@example.com through http://localhost:7777/human-in-the-loop/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Confirmation Tool and Agent
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Simulate sending one email after a user confirms its contents."""
    return f"Email sent to {to} with subject '{subject}'."


db = SqliteDb(
    id="agui-hitl-db",
    db_file="tmp/agui_hitl.db",
)

email_agent = Agent(
    id="agui-email-agent",
    name="AG-UI Email Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[send_email],
    instructions=[
        (
            "For every email request, call send_email immediately with the "
            "recipient, subject, and body."
        ),
        (
            "Do not ask for confirmation in prose. AgentOS pauses the tool call "
            "and lets the AG-UI frontend collect the confirmation."
        ),
        "Never claim send_email ran before its tool result is available.",
        "After a confirmed call, report the recipient and subject in one sentence.",
    ],
)

agent_os = AgentOS(
    id="agui-hitl-os",
    description="Backend tool confirmation and resume through AG-UI.",
    agents=[email_agent],
    interfaces=[AGUI(agent=email_agent, prefix="/human-in-the-loop")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Human-in-the-Loop Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
