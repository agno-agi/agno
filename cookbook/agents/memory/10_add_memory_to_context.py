"""
This example shows how to use the `add_memories_to_context` parameter in the Agent config to
add references to the user memories to the Agent.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager, UserMemory
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, memory_table="user_memories")

memory_manager = MemoryManager(model=OpenAIChat(id="gpt-4o"), db=db)

memory_manager.add_user_memory(
    memory=UserMemory(memory="I like to play soccer", topics=["soccer"]),
    user_id="john_doe@example.com",
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    add_memories_to_context=True,  # Add pre existing memories to the Agent but don't create new ones
)

# Alternatively, you can create/update user memories but not add them to the Agent
# agent = Agent(
#     model=OpenAIChat(id="gpt-4o"),
#     memory_manager=memory_manager,
#     db=db,
#     add_memories_to_context=False,
# )

agent.print_response("What are my hobbies?", user_id="john_doe@example.com")
