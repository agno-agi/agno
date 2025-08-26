"""Run `pip install ddgs sqlalchemy cohere` to install dependencies."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.cohere import Cohere
from agno.tools.duckduckgo import DuckDuckGoTools

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

agent = Agent(
    model=Cohere(id="command-a-03-2025"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
