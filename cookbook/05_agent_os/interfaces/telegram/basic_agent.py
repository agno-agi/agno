"""Basic Telegram bot agent with group chat support.

Requires:
    TELEGRAM_TOKEN — Bot token from @BotFather
    GOOGLE_API_KEY — Google Gemini API key
    APP_ENV=development — Skip webhook secret validation for local testing

Run:
    python cookbook/05_agent_os/interfaces/telegram/basic_agent.py

Then expose via ngrok:
    ngrok http 7777

Set webhook:
    curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook?url=https://<ngrok-url>/telegram/webhook"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram

agent_db = SqliteDb(session_table="telegram_sessions", db_file="tmp/telegram_e2e.db")

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

if __name__ == "__main__":
    agent_os.serve(app="basic_agent:app", reload=True)
