"""
This example shows how to use the `add_memory_references` parameter in the Agent config to
add references to the user memories to the Agent.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory, UserMemory
from agno.models.google.gemini import Gemini

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

memory = Memory(db=memory_db)

memory.add_user_memory(
    memory=UserMemory(memory="I like to play soccer", topics=["soccer"]),
    user_id="john_doe@example.com",
)

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    memory=memory,
    add_memory_references=True,  # Add pre existing memories to the Agent but don't create new ones
)

# Alternatively, you can create/update user memories but not add them to the Agent
# agent = Agent(
#     model=Gemini(id="gemini-2.0-flash-exp"),
#     memory=memory,
#     enable_user_memories=True,
#     add_memory_references=False,
# )

agent.print_response("What are my hobbies?", user_id="john_doe@example.com")
