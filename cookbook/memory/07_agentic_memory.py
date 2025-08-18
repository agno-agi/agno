"""
This example shows you how to use persistent memory with an Agent.

During each run the Agent can create/update/delete user memories.

To enable this, set `enable_agentic_memory=True` in the Agent config.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

# No need to set the model, it gets set by the agent to the agent's model
memory_manager = MemoryManager(db=db)

john_doe_id = "john_doe@example.com"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    memory_manager=memory_manager,
    enable_agentic_memory=True,
)

agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
)

agent.print_response("What are my hobbies?", stream=True, user_id=john_doe_id)

memories = memory_manager.get_user_memories(user_id=john_doe_id)
print("Memories about John Doe:")
pprint(memories)


agent.print_response(
    "Remove all existing memories of me.",
    stream=True,
    user_id=john_doe_id,
)

memories = memory_manager.get_user_memories(user_id=john_doe_id)
print("Memories about John Doe:")
pprint(memories)

agent.print_response(
    "My name is John Doe and I like to paint.", stream=True, user_id=john_doe_id
)

memories = memory_manager.get_user_memories(user_id=john_doe_id)
print("Memories about John Doe:")
pprint(memories)


agent.print_response(
    "I don't paint anymore, i draw instead.", stream=True, user_id=john_doe_id
)

memories = memory_manager.get_user_memories(user_id=john_doe_id)

print("Memories about John Doe:")
pprint(memories)
