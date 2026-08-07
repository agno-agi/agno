"""
Personal Assistant - User Install + Ephemeral
=============================================

The two things only the Interactions transport can do:

- ``user_install=True`` (the default) registers the command for user accounts
  as well as servers. Install the app to YOUR account and ``/ask`` works
  everywhere on Discord - any server, group DMs, bot DMs - even where the bot
  was never invited.
- ``ephemeral=True`` makes every reply visible only to you, with no thread and
  no channel message. Ask anything in a busy public channel without anyone
  seeing the question or the answer. (Without the interface default, users can
  still opt in per command with ``/ask ... ephemeral:True``.)

Together they make a private personal AI that follows you around Discord.
The assistant carries web search and a calculator, so it can look things up
and crunch numbers - and since replies are ephemeral, nobody in the channel
sees you asking. While tools run, their live status shows on the (private)
deferred reply.

Try: install the app to your account (Discord app -> Add App -> "Use this app
everywhere"), then ``/ask question:hello`` in any server - the reply is
visible only to you.

Setup:
  1. Create a Discord application at https://discord.com/developers/applications
  2. Under Installation, enable "User Install" as an authorization method.
  3. Set env vars:
       DISCORD_PUBLIC_KEY  - Application -> General Information -> Public Key
       DISCORD_APP_ID      - Application -> General Information -> Application ID
       DISCORD_BOT_TOKEN   - Application -> Bot -> Reset Token
  4. Run this script. The /ask slash command is registered on startup.
  5. Expose the server publicly (ngrok, cloudflared, etc.) and paste
     ``https://<your-host>/discord/interactions`` into Discord ->
     General Information -> Interactions Endpoint URL -> Save Changes.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import DiscordInteractions
from agno.tools.calculator import CalculatorTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="discord_sessions", db_file="tmp/discord_personal.db")

personal_assistant = Agent(
    name="Personal Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    tools=[
        WebSearchTools(),
        CalculatorTools(),
    ],
    instructions=[
        "You are the user's private personal assistant on Discord.",
        "Your replies are ephemeral - only the asker sees them, so answer candidly.",
        "Search the web for anything current or factual; use the calculator for math.",
        "Keep responses concise - Discord messages are capped at 2000 characters.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[personal_assistant],
    interfaces=[
        DiscordInteractions(
            agent=personal_assistant,
            user_install=True,  # usable anywhere once installed to your account
            ephemeral=True,  # every reply visible only to the asker
        )
    ],
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
    agent_os.serve(app="personal_assistant:app", reload=True)
