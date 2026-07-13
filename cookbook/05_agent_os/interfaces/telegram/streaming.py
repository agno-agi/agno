"""
Streaming Telegram Agent
========================

Telegram bot that streams responses token-by-token, editing the message
in real time so the user sees incremental output instead of waiting for
the full response.

Key concepts:
  - ``streaming=True`` on the Telegram interface enables chunked message edits.
  - Uses OpenAI gpt-4o-mini for fast token generation.
  - SQLite session persistence keeps conversation history across restarts.

Setup: Set TELEGRAM_TOKEN env var from @BotFather.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(
    session_table="telegram_sessions", db_file="tmp/telegram_streaming.db"
)

telegram_agent = Agent(
    name="Telegram Streaming Bot",
    model=OpenAIChat(id="gpt-4o-mini"),
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
            streaming=True,
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
    agent_os.serve(app="streaming:app", reload=True)
