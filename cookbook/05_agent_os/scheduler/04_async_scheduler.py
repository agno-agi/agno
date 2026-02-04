"""
Async Scheduler Example

This example demonstrates using the scheduler with an async database.
Async databases provide non-blocking database operations which is
important for high-throughput scenarios.

Requirements:
    pip install agno[scheduler] aiosqlite

Run:
    python cookbook/05_agent_os/scheduler/04_async_scheduler.py
"""

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Create a simple agent
agent = Agent(
    id="async-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a helpful assistant. Be concise.",
)

# Create an async SQLite database
# The scheduler will automatically use async methods when available
async_db = AsyncSqliteDb(db_file="async_scheduler.db")

# Create AgentOS with scheduler enabled
agent_os = AgentOS(
    agents=[agent],
    db=async_db,  # Async database
    enable_scheduler=True,
    scheduler_poll_interval=10,
)

if __name__ == "__main__":
    print("Starting AgentOS with async scheduler...")
    print("\nUsing AsyncSqliteDb for non-blocking database operations.")
    print("The scheduler poller and executor will use async methods.")
    print("\nCreate schedules via POST /v1/schedules")

    agent_os.run(port=7777)
