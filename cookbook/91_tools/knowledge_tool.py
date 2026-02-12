"""
Knowledge Tool
=============================

Demonstrates knowledge tool.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.team.team import Team
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

kb = Knowledge(
    vector_db=PgVector(
        table_name="documents",
        db_url=db_url,
    ),
)

agent = Agent(
    knowledge=kb,
    update_knowledge=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Update your knowledge with the fact that cats and dogs are pets", markdown=True
    )

    team = Team(
        name="Knowledge Team",
        members=[agent],
        knowledge=kb,
        update_knowledge=True,
    )
    team.print_response(
        "Update your knowledge with the fact that cats don't like water", markdown=True
    )
