"""Use Oracle as the database for an agent.

Run `uv pip install openai` to install dependencies."""

from agno.agent import Agent
from agno.db.oracle import OracleDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1"
db = OracleDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    db=db,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("How many people live in Canada?")
    agent.print_response("What is their national anthem called?")
