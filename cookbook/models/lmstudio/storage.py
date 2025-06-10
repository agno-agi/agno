"""Run `pip install duckduckgo-search sqlalchemy` to install dependencies."""

from agno.agent import Agent
from agno.models.lmstudio import LMStudio
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(
    model=LMStudio(id="qwen2.5-7b-instruct-1m"),
    storage=PostgresAgentStorage(table_name="agent_sessions", db_url=db_url),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
