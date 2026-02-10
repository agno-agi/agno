"""
Custom Memory Manager Configuration
===================================

This example shows how to configure a MemoryManager separately from the Agent
and apply custom memory capture instructions.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Memory Manager
# ---------------------------------------------------------------------------
memory_manager = MemoryManager(
    model=OpenAIChat(id="gpt-4o"),
    additional_instructions="""
    IMPORTANT: Don't store any memories about the user's name. Just say "The User" instead of referencing the user's name.
    """,
    db=db,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    memory_manager=memory_manager,
    update_memory_on_run=True,
    user_id="john_doe@example.com",
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    john_doe_id = "john_doe@example.com"

    agent.print_response(
        "My name is John Doe and I like to swim and play soccer.", stream=True
    )

    agent.print_response("I dont like to swim", stream=True)

    memories = agent.get_user_memories(user_id=john_doe_id)
    print("John Doe's memories:")
    pprint(memories)
