"""
Agno Gateway - user memories
============================

User memories and session summaries are model-agnostic, so they work unchanged through
the gateway. The agent extracts and stores facts about the user across turns.

Run `./cookbook/scripts/run_pgvector.sh` to start Postgres, then
`uv pip install sqlalchemy 'psycopg[binary]'` to install dependencies.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.agno import Agno
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    user_id="test_user",
    session_id="test_session",
    db=db,
    update_memory_on_run=True,
    enable_session_summaries=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("My name is john billings and I live in nyc")
    if agent.db:
        pprint(agent.get_user_memories(user_id="test_user"))

    agent.print_response("What do you know about me?")
