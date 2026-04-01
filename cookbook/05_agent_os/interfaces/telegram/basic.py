"""
Basic Telegram Agent
====================

Minimal Telegram bot that responds to messages in private chats and
when mentioned in groups. Uses SQLite for session persistence so the
agent remembers conversation history across restarts.

Key concepts:
  - ``reply_to_mentions_only=True`` ignores regular group messages and
    only responds when the bot is mentioned with @.
  - ``add_history_to_context=True`` feeds the last N runs back into the prompt.

Setup: Set TELEGRAM_TOKEN env var from @BotFather.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="telegram_sessions", db_file="tmp/telegram_basic.db")

telegram_agent = Agent(
    name="Telegram Bot",
    model=Gemini(id="gemini-2.5-pro"),
    db=agent_db,
    instructions=[
        "You are a helpful assistant on Telegram.",
        "Keep responses concise and friendly.",
        "When in a group, you respond only when mentioned with @.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[telegram_agent],
    interfaces=[
        Telegram(
            agent=telegram_agent,
            reply_to_mentions_only=True,
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
    agent_os.serve(app="basic:app", reload=True)
