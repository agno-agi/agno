"""Use SQLite as the database for an agent.

Run `uv pip install openai ddgs sqlalchemy aiosqlite` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = AsyncSqliteDb(db_file="tmp/data.db")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(agent.aprint_response("How many people live in Canada?"))
    asyncio.run(agent.aprint_response("What is their national anthem called?"))
