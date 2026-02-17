"""
Load Agent from Database
========================

Demonstrates loading an agent from the database by ID and running it.
"""

from agno.agent.agent import get_agent_by_id, get_agents  # noqa: F401
from agno.db.postgres import PostgresDb

# ---------------------------------------------------------------------------
# Create Database Client
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Run Agent Load Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent = get_agent_by_id(db=db, id="agno-agent")

    if agent:
        agent.print_response("How many people live in Canada?")
    else:
        print("Agent not found")

    # You can also get all agents from the database
    # agents = get_agents(db=db)
    # for agent in agents:
    #     print(agent)
