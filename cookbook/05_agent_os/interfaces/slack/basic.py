"""
Basic
=====

Demonstrates basic.
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/persistent_memory.db")

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-5.2"),
    db=agent_db,debug_mode=True, debug_level=2,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    agents=[basic_agent],
    interfaces=[
        Slack(
            agent=basic_agent,
            streaming=False,
            reply_to_mentions_only=False
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
