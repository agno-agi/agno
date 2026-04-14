"""
Multiple Telegram Bot Instances
================================

Runs two agents behind a single Telegram bot using URL path prefixes
to route messages. Each agent gets its own webhook endpoint and can
optionally use a separate bot token for full isolation.

Key concepts:
  - ``prefix="/basic"`` and ``prefix="/web-research"`` give each agent its own webhook path.
  - Pass ``token=`` per instance to use separate bot tokens, or omit to share one.
  - Both agents share the same AgentOS server and SQLite database.

Setup: Set TELEGRAM_TOKEN env var from @BotFather.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(db_file="tmp/persistent_memory.db")

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-5.2"),
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

web_research_agent = Agent(
    name="Web Research Agent",
    model=OpenAIChat(id="gpt-5.2"),
    db=agent_db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
)

# Each Telegram interface can use a different prefix (and optionally a different bot token).
# If you want truly separate bots, pass token= to each instance:
#   Telegram(agent=basic_agent, prefix="/basic", token="BOT_TOKEN_1"),
#   Telegram(agent=web_research_agent, prefix="/web-research", token="BOT_TOKEN_2"),
# When token is omitted, TELEGRAM_TOKEN env var is used for all instances.
agent_os = AgentOS(
    agents=[basic_agent, web_research_agent],
    interfaces=[
        Telegram(agent=basic_agent, prefix="/basic"),
        Telegram(agent=web_research_agent, prefix="/web-research"),
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
    agent_os.serve(app="multiple_instances:app", reload=True)
