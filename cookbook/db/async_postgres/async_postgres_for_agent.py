"""Use Postgres as the database for an agent.

Run `pip install openai ddgs sqlalchemy psycopg` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.tools.duckduckgo import DuckDuckGoTools

db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"
db = AsyncPostgresDb(db_url=db_url)

agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    add_datetime_to_context=True,
)


asyncio.run(agent.aprint_response("How many people live in Canada?"))
asyncio.run(agent.aprint_response("What is their national anthem called?"))
