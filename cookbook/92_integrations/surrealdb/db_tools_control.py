"""
SurrealDB Memory DB Tools Control
"""

from agno.agent.agent import Agent
from agno.db.surrealdb import SurrealDb
from agno.memory.manager import MemoryManager
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "agno"
SURREALDB_DATABASE = "memories"

creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
memory_db = SurrealDb(
    None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
john_doe_id = "john_doe@example.com"

memory_manager_full = MemoryManager(
    model=OpenAIChat(id="gpt-4o"),
    db=memory_db,
    add_memories=True,
    update_memories=True,
)

agent_full = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory_manager=memory_manager_full,
    enable_agentic_memory=True,
    db=memory_db,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    # Add initial memory
    agent_full.print_response(
        "My name is John Doe and I like to hike in the mountains on weekends. I also enjoy photography.",
        stream=True,
        user_id=john_doe_id,
    )

    # Test memory recall
    agent_full.print_response("What are my hobbies?", stream=True, user_id=john_doe_id)

    # Test memory update
    agent_full.print_response(
        "I no longer enjoy photography. Instead, I've taken up rock climbing.",
        stream=True,
        user_id=john_doe_id,
    )

    print("\nMemories after update:")
    memories = memory_manager_full.get_user_memories(user_id=john_doe_id)
    pprint([m.memory for m in memories] if memories else [])


if __name__ == "__main__":
    run_example()
