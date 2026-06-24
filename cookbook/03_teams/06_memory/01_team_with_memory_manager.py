"""
Team With Memory Manager
========================

Demonstrates persistent team memory updates through MemoryManager.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager
from agno.models.openai import OpenAIResponses
from agno.team import Team
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

session_id = str(uuid4())
john_doe_id = "john_doe@example.com"

memory_manager = MemoryManager(model=OpenAIResponses(id="gpt-5-mini"))
memory_manager.clear()

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    model=OpenAIResponses(id="gpt-5-mini"),
    memory_manager=memory_manager,
    members=[agent],
    db=db,
    update_memory_on_run=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response(
        "My name is John Doe and I like to hike in the mountains on weekends.",
        stream=True,
        user_id=john_doe_id,
        session_id=session_id,
    )
    team.print_response(
        "What are my hobbies?",
        stream=True,
        user_id=john_doe_id,
        session_id=session_id,
    )

    memories = team.get_user_memories(user_id=john_doe_id)
    print("John Doe's memories:")
    pprint(memories)
