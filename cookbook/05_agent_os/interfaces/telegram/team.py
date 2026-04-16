"""
Telegram Team Agent
===================

Multi-agent team on Telegram with a Researcher and a Writer. The team
leader coordinates: the Researcher gathers facts, then the Writer
produces a concise summary suitable for Telegram.

Key concepts:
  - ``Team`` with two specialist ``Agent`` members demonstrates delegation.
  - The team itself is passed to the Telegram interface, not individual agents.
  - SQLite session persistence keeps conversation history across restarts.

Setup: Set TELEGRAM_TOKEN env var from @BotFather.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(
    session_table="telegram_team_sessions", db_file="tmp/telegram_team.db"
)

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Researches topics and provides detailed factual information.",
    instructions=["Provide well-researched, factual information on the given topic."],
)

writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Takes research and writes clear, engaging summaries.",
    instructions=["Write concise, engaging summaries based on the research provided."],
)

telegram_team = Team(
    name="Telegram Research Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, writer],
    db=agent_db,
    instructions=[
        "You coordinate a research team on Telegram.",
        "Use the Researcher to gather facts, then the Writer to create a response.",
        "Keep responses concise for Telegram.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    teams=[telegram_team],
    interfaces=[
        Telegram(
            team=telegram_team,
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
    agent_os.serve(app="team:app", reload=True)
