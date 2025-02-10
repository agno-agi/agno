"""Run `pip install duckduckgo-search sqlalchemy google.generativeai` to install dependencies."""

from agno.agent import Agent
from agno.models.vertexai import Gemini
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    storage=PostgresAgentStorage(table_name="agent_sessions", db_url=db_url),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
    debug_mode=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
