"""
Telegram Reasoning Agent
========================

Telegram bot powered by Claude with chain-of-thought reasoning and web
search. Uses ReasoningTools for structured thinking and DuckDuckGo for
live information retrieval.

Key concepts:
  - ``ReasoningTools`` gives the agent explicit think/reason tool calls.
  - ``DuckDuckGoTools`` provides web search for up-to-date information.
  - SQLite session persistence keeps conversation history across restarts.

Setup: Set TELEGRAM_TOKEN env var from @BotFather.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(db_file="tmp/persistent_memory.db")

reasoning_agent = Agent(
    name="Reasoning Research Agent",
    model=OpenAIChat(id="gpt-5.2"),
    db=agent_db,
    tools=[
        ReasoningTools(add_instructions=True),
        DuckDuckGoTools(),
    ],
    instructions="Use tables to display data. When you use thinking tools, keep the thinking brief.",
    add_datetime_to_context=True,
    markdown=True,
)


agent_os = AgentOS(
    agents=[reasoning_agent],
    interfaces=[Telegram(agent=reasoning_agent)],
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
    agent_os.serve(app="reasoning_agent:app", reload=True)
