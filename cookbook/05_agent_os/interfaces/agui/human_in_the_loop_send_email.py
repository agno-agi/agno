"""Human in the Loop over AG-UI - Backend Confirmation (Shape B)
===============================================================

A `send_email` tool gated by `requires_confirmation=True`. The human approves or
declines in the dojo; on approval agno runs the tool (the send happens server-side
-> "Email sent to ..."), on rejection the tool is NOT run and the agent acknowledges
it. This is the "human decides -> agno executes" case, distinct from external-execution
HITL. The visible side effect makes accept and reject observably different.

Run:
    OPENAI_API_KEY=... python cookbook/05_agent_os/interfaces/agui/human_in_the_loop_send_email.py
Open the dojo `human_in_the_loop` feature (agno integration) and ask:
    "send an email to recipient@example.com"
The agent drafts a subject and body and pauses; Confirm -> email sent + agent confirms;
Reject -> not sent + agent acknowledges it was cancelled.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool


@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email. Pauses for human confirmation before agno runs it.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text.
    """
    return f"Email sent to {to} with subject '{subject}'."


hitl_agent = Agent(
    name="human_in_the_loop",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_hitl_send_email.db"),
    tools=[send_email],
    instructions=(
        "You help the user send emails. When the user asks to send an email, call the "
        "send_email tool with the recipient, a subject, and a body. If the user did not "
        "provide a subject or body, draft a reasonable one yourself - the user reviews "
        "and confirms before anything is sent. After a confirmed send, briefly tell the "
        "user the email was sent.\n\n"
        "When the user declines the confirmation, do not send the email and do not call "
        "the send_email tool again. Briefly acknowledge the decision and confirm the "
        "email was not sent. Do not re-attempt the send unless the user explicitly asks."
    ),
    add_history_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[hitl_agent],
    interfaces=[AGUI(agent=hitl_agent, prefix="/human_in_the_loop")],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=9001)
