"""
Discord Research Assistant
==========================

An agent that combines Discord channel/server introspection with web
search to answer research questions. The agent can list channels in
the server, fetch recent channel history, and search the web for
external context.

Key concepts:
  - ``DiscordTools`` exposes list_channels, get_channel_messages,
    and get_channel_info as callable tools.
  - ``WebSearchTools`` provides external web search.
  - The interface injects ``discord_channel_id`` and ``discord_guild_id``
    as dependencies, so the agent can act on "this channel" / "this server"
    without the user having to paste IDs.

Setup: Set DISCORD_PUBLIC_KEY, DISCORD_APP_ID, DISCORD_BOT_TOKEN env vars.
Grant the bot the **Read Message History** and **View Channels** permissions.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import DiscordInteractions
from agno.tools.discord import DiscordTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(
    session_table="discord_research_sessions", db_file="tmp/discord_research.db"
)

research_assistant = Agent(
    name="Discord Research Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    tools=[
        DiscordTools(
            enable_list_channels=True,
            enable_get_channel_messages=True,
            enable_get_channel_info=True,
            enable_send_message=False,
            enable_delete_message=False,
        ),
        WebSearchTools(),
    ],
    instructions=[
        "You are a research assistant on Discord.",
        "Your context includes ``discord_channel_id`` and ``discord_guild_id`` -",
        "use those when the user says 'this channel' or 'this server'.",
        "When asked to research something:",
        "  1. Check Discord for relevant channel history if it looks server-specific.",
        "  2. Use web search for external context.",
        "  3. Synthesize findings into a clear summary.",
        "Keep the final reply under 2000 characters per chunk.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[research_assistant],
    interfaces=[DiscordInteractions(agent=research_assistant)],
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
    agent_os.serve(app="research_assistant:app", reload=True)
