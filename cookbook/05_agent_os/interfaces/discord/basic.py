"""
Basic Discord Agent
===================

Minimal Discord bot that responds to an ``/ask`` slash command. The command
takes a required ``question`` string and an optional ``file`` attachment
(image, audio, video, or document) that is forwarded to the agent.

Setup:
  1. Create a Discord application at https://discord.com/developers/applications
  2. Set env vars:
       DISCORD_PUBLIC_KEY  - Application -> General Information -> Public Key
       DISCORD_APP_ID      - Application -> General Information -> Application ID
       DISCORD_BOT_TOKEN   - Application -> Bot -> Reset Token
  3. Run this script. The /ask slash command is registered on startup.
  4. Expose the server publicly (ngrok, cloudflared, etc.) and paste
     ``https://<your-host>/discord/interactions`` into Discord ->
     General Information -> Interactions Endpoint URL -> Save Changes.
  5. In Discord, type ``/ask question:hello``.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="discord_sessions", db_file="tmp/discord_basic.db")

discord_agent = Agent(
    name="Discord Bot",
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    instructions=[
        "You are a helpful assistant on Discord.",
        "Keep responses concise - Discord messages are capped at 2000 characters.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[discord_agent],
    interfaces=[Discord(agent=discord_agent)],
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
    agent_os.serve(app="basic:app", reload=True)
