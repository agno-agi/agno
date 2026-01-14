"""Run `pip install ddgs sqlalchemy` to install dependencies."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.lmstudio import LMStudio
from agno.tools.duckduckgo import DuckDuckGoTools

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

agent = Agent(
    model=LMStudio(id="qwen2.5-7b-instruct-1m"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
