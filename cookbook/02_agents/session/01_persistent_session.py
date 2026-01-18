"""Persistent Session Example

Demonstrates how to create an agent with persistent session storage using PostgreSQL.
The agent will remember conversation history across runs when using the same session_id.

Requirements:
- PostgreSQL with PgVector running (./cookbook/scripts/run_pgvector.sh)
- OPENAI_API_KEY environment variable
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    session_id="session_storage",
    add_history_to_context=True,
)

agent.print_response("Tell me a new interesting fact about space")
