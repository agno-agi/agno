"""
Workflow
========

Discord bot powered by a two-step Draft-then-Edit workflow.
The first step generates a draft and the second step refines it.

Prerequisites:
    export DISCORD_BOT_TOKEN="your-bot-token"
    export DISCORD_PUBLIC_KEY="your-public-key"
    export DISCORD_APPLICATION_ID="your-app-id"
    export OPENAI_API_KEY="your-openai-key"

Run:
    python cookbook/05_agent_os/interfaces/discord/workflow.py

Then expose via ngrok:
    ngrok http 7777

Set the Interactions Endpoint URL in the Discord Developer Portal to:
    https://<ngrok-url>/discord/interactions
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord
from agno.workflow import Workflow

workflow_db = SqliteDb(
    session_table="workflow_sessions", db_file="tmp/discord_workflow.db"
)

drafter = Agent(
    name="Drafter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You write a first draft based on the user's request.",
        "Be thorough but accept that this is a draft — it will be refined.",
    ],
    markdown=True,
)

editor = Agent(
    name="Editor",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You receive a draft and improve it.",
        "Fix grammar, improve clarity, tighten phrasing, and ensure accuracy.",
        "Return only the final polished version — no commentary.",
    ],
    markdown=True,
)


class DraftEditWorkflow(Workflow):
    drafter: Agent = drafter
    editor: Agent = editor

    async def arun(self, message: str, **kwargs):
        draft = await self.drafter.arun(message, **kwargs)
        draft_text = draft.content if draft and draft.content else message
        result = await self.editor.arun(
            f"Improve this draft:\n\n{draft_text}", **kwargs
        )
        return result


draft_edit_workflow = DraftEditWorkflow(
    name="Draft-Edit Workflow",
    db=workflow_db,
)

agent_os = AgentOS(
    workflows=[draft_edit_workflow],
    interfaces=[
        Discord(
            workflow=draft_edit_workflow,
            reply_in_thread=True,
        )
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="workflow:app", reload=True)
