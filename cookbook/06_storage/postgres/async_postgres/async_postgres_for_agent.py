"""Use Postgres as the database for an agent.

Run `uv pip install openai ddgs sqlalchemy psycopg` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"
db = AsyncPostgresDb(db_url=db_url)

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
async def main():
    await agent.aprint_response("How many people live in Canada?")
    await agent.aprint_response("What is their national anthem called?")


if __name__ == "__main__":
    asyncio.run(main())
