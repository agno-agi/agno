"""
Mount Multiple Telegram Bots
============================

Mount two independently credentialed Telegram bots on one AgentOS server.
Each bot uses its own URL prefix and bot token because Telegram registers one
webhook URL per bot.

Prerequisites: ASSISTANT_TELEGRAM_TOKEN, RESEARCH_TELEGRAM_TOKEN, OPENAI_API_KEY, and the `agno[telegram]` extra
Run: .venvs/demo/bin/python cookbook/05_agent_os/18_telegram/multiple_instances.py
Try in Telegram: Ask the assistant bot for a concise explanation, then ask the research bot for sourced facts
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Load Bot Tokens
# ---------------------------------------------------------------------------

assistant_token = getenv("ASSISTANT_TELEGRAM_TOKEN")
research_token = getenv("RESEARCH_TELEGRAM_TOKEN")

if not assistant_token:
    raise ValueError("ASSISTANT_TELEGRAM_TOKEN is required")
if not research_token:
    raise ValueError("RESEARCH_TELEGRAM_TOKEN is required")

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="telegram-multiple-db",
    db_file="tmp/telegram_multiple.db",
)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

assistant = Agent(
    id="telegram-concise-assistant",
    name="Concise Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer clearly in three short paragraphs or fewer.",
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

researcher = Agent(
    id="telegram-web-researcher",
    name="Web Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[WebSearchTools()],
    instructions=[
        "Search the web for current facts when needed.",
        "Return a concise answer with source links.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="telegram-multiple-os",
    description="AgentOS serving two Telegram bots on separate prefixes.",
    agents=[assistant, researcher],
    interfaces=[
        Telegram(
            agent=assistant,
            prefix="/assistant",
            token=assistant_token,
        ),
        Telegram(
            agent=researcher,
            prefix="/research",
            token=research_token,
        ),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
