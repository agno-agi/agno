"""
MySQL Database Backend
======================

Demonstrates AgentOS with MySQL storage using both sync and async setups.
"""

from agno.agent import Agent
from agno.db.mysql import AsyncMySQLDb, MySQLDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
sync_db = MySQLDb(
    id="mysql-demo",
    db_url="mysql+pymysql://ai:ai@localhost:3306/ai",
    session_table="sessions",
    eval_table="eval_runs",
    memory_table="user_memories",
    metrics_table="metrics",
)

async_db = AsyncMySQLDb(
    id="mysql-demo",
    db_url="mysql+asyncmy://ai:ai@localhost:3306/ai",
    session_table="sessions",
    eval_table="eval_runs",
    memory_table="user_memories",
    metrics_table="metrics",
)

# ---------------------------------------------------------------------------
# Create Sync Agent, Team, Eval, And AgentOS
# ---------------------------------------------------------------------------
sync_agent = Agent(
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    db=sync_db,
    update_memory_on_run=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

sync_team = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=sync_db,
    members=[sync_agent],
)

sync_evaluation = AccuracyEval(
    db=sync_db,
    name="Calculator Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    agent=sync_agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)
# sync_evaluation.run(print_results=True)

sync_agent_os = AgentOS(
    description="Example OS setup",
    agents=[sync_agent],
    teams=[sync_team],
)

# ---------------------------------------------------------------------------
# Create Async Agent, Team, And AgentOS
# ---------------------------------------------------------------------------
async_agent = Agent(
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    db=async_db,
    update_memory_on_run=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

async_team = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=async_db,
    members=[async_agent],
)

async_agent_os = AgentOS(
    description="Example OS setup",
    agents=[async_agent],
    teams=[async_team],
)

# ---------------------------------------------------------------------------
# Create AgentOS App
# ---------------------------------------------------------------------------
# Default to the sync setup. Switch to async_agent_os to run the async variant.
agent_os = sync_agent_os
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="mysql:app", reload=True)
