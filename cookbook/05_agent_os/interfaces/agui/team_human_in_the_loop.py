"""Human in the Loop over AG-UI - Team (member pause)
=====================================================

A Team whose member's tool pauses for confirmation, surfaced over AG-UI. When the team
delegates to the Emailer and its `send_email` tool (gated by `requires_confirmation=True`)
pauses, the pause surfaces as a `TOOL_CALL_*` for that tool - exactly like the single-agent
case - and the run finishes paused. The client answers with a `ToolMessage` {"accepted":
true/false} keyed by the tool_call_id; agno resolves it and - because the paused requirement
carries member_agent_id - routes the decision back to the RIGHT member, which runs (or skips)
the tool server-side, and the team continues.

This is the team analogue of human_in_the_loop_send_email.py: the emit + resolve + resume
machinery is entity-agnostic; only the paused-tool emission had to learn to read a team's
member pauses from active_requirements.

Run:
    OPENAI_API_KEY=... python cookbook/05_agent_os/interfaces/agui/team_human_in_the_loop.py
Open an AG-UI client at http://127.0.0.1:9001/team_human_in_the_loop/agui and ask:
    "email alice@example.com to say the quarterly report is ready"
The team routes to the Emailer, which drafts and pauses; Confirm -> email sent + the team
reports it; Reject -> not sent + the team acknowledges it.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team
from agno.tools import tool

MODEL_ID = "gpt-5.5"


@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email. Pauses for human confirmation before agno runs it.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text.
    """
    return f"Email sent to {to} with subject '{subject}'."


researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id=MODEL_ID),
    instructions="Answer factual questions concisely. You do not send emails.",
    markdown=True,
)

emailer = Agent(
    name="Emailer",
    model=OpenAIResponses(id=MODEL_ID),
    tools=[send_email],
    instructions=(
        "You send emails. Call send_email with the recipient, a subject, and a body; if the user "
        "did not give a subject or body, draft a reasonable one - the user confirms before anything "
        "is sent. After a confirmed send, briefly say the email was sent. If the user declines, do "
        "not resend; acknowledge it was cancelled."
    ),
    markdown=True,
)

support_team = Team(
    name="support_team",
    model=OpenAIResponses(id=MODEL_ID),
    members=[researcher, emailer],
    db=SqliteDb(db_file="/tmp/agui_team_hitl.db"),
    instructions="Route email requests to the Emailer and factual questions to the Researcher.",
    add_history_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    teams=[support_team],
    interfaces=[AGUI(team=support_team, prefix="/team_human_in_the_loop")],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=9001)
