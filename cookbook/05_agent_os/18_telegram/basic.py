"""
Serve an Agent through Telegram
===============================

Expose one persistent Agent through AgentOS's Telegram webhook interface.
Streaming is enabled by default, and group chats only trigger the bot when it
is mentioned or when a user replies to one of its messages.

Prerequisites: TELEGRAM_TOKEN, OPENAI_API_KEY, and the `agno[telegram]` extra
Run: .venvs/demo/bin/python cookbook/05_agent_os/18_telegram/basic.py
Try in Telegram: Send /start, ask "Remember that my project is Cedar", then ask "What is my project?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.telegram import Telegram

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="telegram-basic-db",
    db_file="tmp/telegram_basic.db",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

telegram_assistant = Agent(
    id="telegram-assistant",
    name="Telegram Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a helpful assistant on Telegram.",
        "Keep responses concise, friendly, and easy to read in a chat.",
        "Remember facts from earlier messages in the same conversation.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="telegram-basic-os",
    description="AgentOS serving one persistent Telegram assistant.",
    agents=[telegram_assistant],
    interfaces=[
        Telegram(
            agent=telegram_assistant,
            prefix="/telegram",
            reply_to_mentions_only=True,
            reply_to_bot_messages=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
