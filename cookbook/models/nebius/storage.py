"""Run `pip install duckduckgo-search sqlalchemy cerebras_cloud_sdk` to install dependencies."""

from agno.agent import Agent
from agno.models.nebius import Nebius
from agno.storage.postgres import PostgresStorage
from agno.tools.duckduckgo import DuckDuckGoTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(
    model=Nebius(),
    storage=PostgresStorage(table_name="agent_sessions", db_url=db_url),
    tools=[DuckDuckGoTools()],
    debug_mode=True,
    show_tool_calls=True,
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
