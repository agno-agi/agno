"""Run `pip install duckduckgo-search sqlalchemy ibm-watsonx-ai` to install dependencies."""

from agno.agent import Agent
from agno.models.ibm import WatsonX
from agno.storage.postgres import PostgresStorage
from agno.tools.duckduckgo import DuckDuckGoTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(
    model=WatsonX(id="ibm/granite-20b-code-instruct"),
    storage=PostgresStorage(table_name="agent_sessions", db_url=db_url),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
