"""
Discord Gateway Workflow
========================

Two-step draft-and-edit workflow with fluid chat. Mention the bot in a
channel (or DM it) and a Drafter agent writes an initial response, then an
Editor agent polishes it before the final reply lands in your thread.

Key concepts:
  - ``Workflow`` with sequential ``Steps`` chains multiple agents.
  - The workflow (not individual agents) is passed to the gateway interface.
  - Each step runs as a tool call from the workflow's perspective, so the
    live status inside the thread flips between ``Running tool: draft...``
    and ``Running tool: edit...`` before the final answer appears.

Setup: Set DISCORD_BOT_TOKEN, enable the Message Content Intent under Bot
settings, and install discord.py. No public URL or tunnel needed.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import DiscordGateway
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

workflow_db = SqliteDb(
    session_table="discord_workflow_sessions", db_file="tmp/discord_gw_workflow.db"
)

drafter = Agent(
    name="Drafter",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Draft a response to the user's message. Be helpful and informative.",
)

editor = Agent(
    name="Editor",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=[
        "Review and polish the draft for clarity and conciseness.",
        "Keep it under 2000 characters so it fits in a single Discord message.",
    ],
)

draft_step = Step(
    name="draft",
    agent=drafter,
    description="Draft an initial response",
)

edit_step = Step(
    name="edit",
    agent=editor,
    description="Edit and polish the draft",
)

discord_workflow = Workflow(
    name="Discord Draft-Edit Workflow",
    description="A two-step workflow that drafts then edits responses for Discord.",
    steps=[
        Steps(
            name="draft_and_edit",
            description="Draft then edit a response",
            steps=[draft_step, edit_step],
        )
    ],
    db=workflow_db,
)

agent_os = AgentOS(
    workflows=[discord_workflow],
    interfaces=[DiscordGateway(workflow=discord_workflow)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="workflow:app", reload=False)
