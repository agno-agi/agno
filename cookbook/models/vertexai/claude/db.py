"""Run `pip install ddgs sqlalchemy anthropic` to install dependencies."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.vertexai.claude import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

# Setup the database
db = SqliteDb(db_file="tmp/data.db")

agent = Agent(
    model=Claude(id="claude-sonnet-4@20250514"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
