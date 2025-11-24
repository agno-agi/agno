"""Use SQLite as the database for an agent.

Run `pip install openai ddgs sqlalchemy aiosqlite` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.tools.duckduckgo import DuckDuckGoTools

# Initialize AsyncSqliteDb
db = AsyncSqliteDb(db_file="tmp/data.db")

agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    add_datetime_to_context=True,
)


asyncio.run(agent.aprint_response("How many people live in Canada?"))
asyncio.run(agent.aprint_response("What is their national anthem called?"))
