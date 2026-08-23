"""
Agno Gateway - persistence and history
======================================

Agent-level features are model-agnostic, so they work unchanged through the gateway.
Here we attach a database and replay conversation history across turns.

Run `./cookbook/scripts/run_pgvector.sh` to start Postgres, then
`uv pip install ddgs sqlalchemy 'psycopg[binary]'` to install dependencies.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.agno import Agno
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("How many people live in Canada?")
    agent.print_response("What is their national anthem called?")
