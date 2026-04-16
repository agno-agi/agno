"""
Discord Channel Summarizer
==========================

An agent that reads recent Discord channel history and produces a
structured summary. Supports follow-up questions inside the same thread
via session history.

Key concepts:
  - ``DiscordTools`` with ``enable_get_channel_messages`` lets the agent
    pull channel history as a tool call; the live tool-call status in
    the thread will show ``Running tool: get_channel_messages...``.
  - The interface injects ``discord_channel_id`` as a dependency, so the
    agent knows which channel to summarize when the user says "this channel".
  - ``add_history_to_context`` + a ``db`` enables follow-up questions in
    the same Discord thread.

Setup: Set DISCORD_PUBLIC_KEY, DISCORD_APP_ID, DISCORD_BOT_TOKEN env vars.
Grant the bot **Read Message History** and **View Channels** so it can
fetch channel messages.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord
from agno.tools.discord import DiscordTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(
    session_table="discord_summarizer_sessions", db_file="tmp/discord_summarizer.db"
)

summarizer = Agent(
    name="Discord Channel Summarizer",
    model=OpenAIResponses(id="gpt-5.4"),
    db=agent_db,
    tools=[
        DiscordTools(
            enable_get_channel_messages=True,
            enable_get_channel_info=True,
            enable_list_channels=True,
            enable_send_message=False,
            enable_delete_message=False,
        ),
    ],
    instructions=[
        "You summarize Discord channel activity.",
        "Your context includes the ``discord_channel_id`` you are responding in.",
        "When the user says 'this channel', use that id; if they name a different",
        "channel, use ``list_channels`` to find its id first.",
        "Process:",
        "  1. Call ``get_channel_messages`` with the channel id (limit 50-100 depending on ask).",
        "  2. Group messages by topic, speaker, or thread.",
        "  3. Highlight decisions, action items, open questions, and blockers.",
        "Format the summary with clear sections (bullet points, not prose walls):",
        "  - Key Discussions",
        "  - Decisions Made",
        "  - Action Items",
        "  - Open Questions / Blockers",
        "Keep each chunk under 2000 characters.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[summarizer],
    interfaces=[Discord(agent=summarizer, reply_in_thread=False)],
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
    agent_os.serve(app="channel_summarizer:app", reload=True)
