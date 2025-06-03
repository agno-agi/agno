"""Run `pip install sqlalchemy` and ensure Postgres is running (`./cookbook/scripts/run_pgvector.sh`)."""

from agno.agent import Agent
from agno.models.vllm import Vllm
from agno.storage.postgres import PostgresStorage
from agno.tools.duckduckgo import DuckDuckGoTools

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(
    model=Vllm(id="microsoft/Phi-3-mini-4k-instruct"),
    storage=PostgresStorage(table_name="agent_sessions", db_url=DB_URL),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)

agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
