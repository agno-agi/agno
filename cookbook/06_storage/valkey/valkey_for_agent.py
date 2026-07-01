"""
Example showing how to use Valkey as the database for an agent.

Run `uv pip install valkey-glide-sync openai ddgs` to install dependencies.

We can start Valkey locally using docker:
1. Start Valkey container
docker run --name my-valkey -p 6379:6379 -d valkey/valkey-bundle

2. Verify container is running
docker ps

3. Run the file
`python cookbook/06_storage/valkey/valkey_for_agent.py`
"""

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.valkey import ValkeyDb
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = ValkeyDb()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
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

    # Verify db contents
    print("\nVerifying db contents...")
    all_sessions = db.get_sessions(session_type=SessionType.AGENT)
    print(f"Total sessions in Valkey: {len(all_sessions)}")
