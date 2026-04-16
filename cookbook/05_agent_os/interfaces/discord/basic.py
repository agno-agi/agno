"""
Basic Discord Bot
=================

Minimal Discord bot that responds to the ``/ask`` slash command with
conversation history persisted to SQLite. ``/new`` resets the conversation.

Setup: Set DISCORD_PUBLIC_KEY, DISCORD_APP_ID, DISCORD_BOT_TOKEN env vars.
  1. Create app at https://discord.com/developers/applications
  2. Copy Public Key, Application ID, and Bot Token into the env vars above
  3. Run this script, then expose via ngrok: ``ngrok http 7777``
  4. Set Interactions Endpoint URL in the Discord Developer Portal to:
     ``https://<ngrok-url>/discord/interactions``
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord

agent_db = SqliteDb(session_table="discord_sessions", db_file="tmp/discord_basic.db")

agent = Agent(
    name="Discord Bot",
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    instructions=[
        "You are a helpful assistant on Discord.",
        "Keep responses concise — Discord messages are capped at 2000 characters.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[Discord(agent=agent)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic:app", port=7777, reload=True)
