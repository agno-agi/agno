"""
Discord Agent with Media Input
==============================

Analyze images, audio, video, and documents sent through Discord. The ``/ask``
command's optional ``file`` option accepts an attachment, which is forwarded
to the agent as typed media (Image, Audio, Video, or File by content type).

Try: ``/ask question:What is in this image? file:<attach a photo>``

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
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import DiscordInteractions

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="discord_sessions", db_file="tmp/discord_media.db")

discord_agent = Agent(
    name="Discord Media Bot",
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
    interfaces=[DiscordInteractions(agent=discord_agent)],
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
    agent_os.serve(app="agent_with_media:app", reload=True)
