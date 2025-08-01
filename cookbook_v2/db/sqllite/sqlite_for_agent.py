"""Run `pip install duckduckgo-search sqlalchemy openai` to install dependencies."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.tools.duckduckgo import DuckDuckGoTools

db = SqliteDb(db_file="tmp/data.db")

agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
    add_datetime_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem?")
agent.print_response("List my messages one by one")
