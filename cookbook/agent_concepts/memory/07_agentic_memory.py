"""
This example shows you how to use persistent memory with an Agent.

During each run the Agent can create/update/delete user memories.

To enable this, set `enable_agentic_memory=True` in the Agent config.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

# No need to set the model, it gets set by the agent to the agent's model
memory = Memory(db=memory_db)

# Reset the memory for this example
memory.clear()

john_doe_id = "john_doe@example.com"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
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
pprint(memories)


agent.print_response(
    "Remove all existing memories of me.",
    stream=True,
    user_id=john_doe_id,
)

memories = memory.get_user_memories(user_id=john_doe_id)
print("Memories about John Doe:")
pprint(memories)

agent.print_response(
    "My name is John Doe and I like to paint.", stream=True, user_id=john_doe_id
)

memories = memory.get_user_memories(user_id=john_doe_id)
print("Memories about John Doe:")
pprint(memories)


agent.print_response(
    "I don't pain anymore, i draw instead.", stream=True, user_id=john_doe_id
)

memories = memory.get_user_memories(user_id=john_doe_id)

print("Memories about John Doe:")
pprint(memories)
