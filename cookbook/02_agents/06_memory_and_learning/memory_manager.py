"""
Memory Manager
=============================

Use a MemoryManager to give agents persistent memory across sessions.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory.manager import MemoryManager
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/memory_demo.db")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    # Enable agentic memory so the agent can store and retrieve memories
    enable_agentic_memory=True,
    # Provide a MemoryManager for structured memory operations
    memory_manager=MemoryManager(
        db=db,
        model=OpenAIResponses(id="gpt-5-mini"),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # First interaction: tell the agent something to remember
    agent.print_response(
        "My name is Alice and I prefer Python over JavaScript.",
        stream=True,
    )

    print("\n--- Second interaction ---\n")

    # Second interaction: the agent should recall the preference
    agent.print_response(
        "What programming language do I prefer?",
        stream=True,
    )
