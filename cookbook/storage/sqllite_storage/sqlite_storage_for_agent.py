"""Run `pip install duckduckgo-search sqlalchemy openai` to install dependencies."""

from agno.agent import Agent
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    storage=SqliteStorage(
        table_name="agent_sessions", db_file="tmp/data.db", auto_upgrade_schema=True
    ),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem?")
agent.print_response("List my messages one by one")
