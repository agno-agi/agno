"""Run `pip install ddgs sqlalchemy openai` to install dependencies."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.meta import LlamaOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(
    model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    db=PostgresDb(db_url=db_url, session_table="llama_openai_sessions"),
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
