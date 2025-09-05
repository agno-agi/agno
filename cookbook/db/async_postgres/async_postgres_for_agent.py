"""Use Postgres as the database for an agent.

Run `pip install openai` to install dependencies."""

from agno.agent import Agent
from agno.db.async_postgres import AsyncPostgresDb
from agno.tools.duckduckgo import DuckDuckGoTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = AsyncPostgresDb(db_url=db_url)

agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
