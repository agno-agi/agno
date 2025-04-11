"""
This example shows you how to use persistent memory with an Agent.

During each run the Agent can create/update/delete user memories.

To enable this, set `enable_agentic_memory=True` in the Agent config.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic.claude import Claude

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

# No need to set the model, it gets set by the agent to the agent's model
memory = Memory(db=memory_db)

# Reset the memory for this example
memory.clear()

john_doe_id = "john_doe@example.com"

agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20241022"),
    memory=memory,
    enable_agentic_memory=True,
)

agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
)

agent.print_response("What are my hobbies?", stream=True, user_id=john_doe_id)

memories = memory.get_user_memories(user_id=john_doe_id)
print("Memories about John Doe:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")


agent.print_response(
    "Remove all existing memories of me. Completely clear the DB.",
    stream=True,
    user_id=john_doe_id,
)

memories = memory.get_user_memories(user_id=john_doe_id)

print("Memories about John Doe:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")

agent.print_response(
    "My name is John Doe and I like to paint.", stream=True, user_id=john_doe_id
)

memories = memory.get_user_memories(user_id=john_doe_id)

print("Memories about John Doe:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")


agent.print_response("Remove any memory of my name.", stream=True, user_id=john_doe_id)

memories = memory.get_user_memories(user_id=john_doe_id)

print("Memories about John Doe:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")
