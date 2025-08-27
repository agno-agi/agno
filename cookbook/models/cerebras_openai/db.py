"""Run `pip install ddgs sqlalchemy cerebras_cloud_sdk` to install dependencies."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.cerebras import CerebrasOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

agent = Agent(
    model=CerebrasOpenAI(id="llama-4-scout-17b-16e-instruct"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
