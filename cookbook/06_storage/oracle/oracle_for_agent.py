"""Use Oracle Database as the storage backend for an Agent.

Requires Oracle Database 19c or later. Start one locally with:
    ./cookbook/scripts/run_oracle.sh

Run `uv pip install "agno[oracle]" openai` to install dependencies.
"""

from agno.agent import Agent
from agno.db.oracle import OracleDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the database connection
# ---------------------------------------------------------------------------
# On Oracle a schema is a user, so tables are created in the connecting
# user's own schema by default. See the README for how db_schema and
# create_schema behave differently here than on Postgres.
db = OracleDb(db_url="oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    db=db,
    model=OpenAIResponses(id="gpt-5.6-luna"),
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the capital of France?")
    agent.print_response("What did I just ask you?")
