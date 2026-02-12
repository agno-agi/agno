"""
Sql Tools
=============================

Demonstrates sql tools.
"""

from agno.agent import Agent
from agno.tools.sql import SQLTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agent = Agent(tools=[SQLTools(db_url=db_url)])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List the tables in the database. Tell me about contents of one of the tables",
        markdown=True,
    )
