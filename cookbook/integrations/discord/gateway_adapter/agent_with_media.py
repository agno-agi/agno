"""
Discord Gateway Agent with Media Input
======================================

Analyze images, audio, video, and documents sent through Discord. Attach a
file to any message that reaches the bot (a mention, a thread reply, or a DM)
and it is forwarded to the agent as typed media (Image, Audio, Video, or File
by content type).

Try: DM the bot a photo with the caption "What is in this image?"

Setup:
  1. Create a Discord application at https://discord.com/developers/applications
  2. Under Bot, enable the "Message Content Intent" (privileged intent toggle).
  3. Set env vars:
       DISCORD_BOT_TOKEN   - Application -> Bot -> Reset Token
  4. Install the gateway dependency: pip install discord.py
  5. Invite the bot to a server with Send Messages, Create Public Threads,
     and Send Messages in Threads permissions.
  6. Run this script, then @mention the bot with an attachment or DM it one.

Note: keep reload=False - auto-reload reconnects the gateway socket on every
file change, which is noisy and can hit Discord's session limits.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import DiscordGateway

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(
    session_table="discord_sessions", db_file="tmp/discord_gateway_media.db"
)

discord_agent = Agent(
    name="Discord Gateway Media Bot",
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    instructions=[
        "You are a helpful assistant on Discord that can analyze media.",
        "When the user attaches an image or document, describe and analyze it.",
        "Keep responses concise - Discord messages are capped at 2000 characters.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[discord_agent],
    interfaces=[DiscordGateway(agent=discord_agent)],
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
    agent_os.serve(app="agent_with_media:app", reload=False)
