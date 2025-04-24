"""
This example shows you how to use persistent memory with an Agent.

After each run, user memories are created/updated.

To enable this, set `enable_user_memories=True` in the Agent config.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from rich.pretty import pprint
from utils import print_chat_history

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

# No need to set the model, it gets set by the agent to the agent's model
memory = Memory(db=memory_db)

# Reset the memory for this example
memory.clear()

session_id = "session_1"
john_doe_id = "john_doe@example.com"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    storage=SqliteStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
    enable_user_memories=True,
)

agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
    session_id=session_id,
)

agent.print_response(
    "What are my hobbies?", stream=True, user_id=john_doe_id, session_id=session_id
)

# -*- Print the chat history
session_run = memory.runs[session_id][-1]
print_chat_history(session_run)

memories = memory.get_user_memories(user_id=john_doe_id)
print("John Doe's memories:")
pprint(memories)

agent.print_response(
    "Ok i dont like hiking anymore, i like to play soccer instead.",
    stream=True,
    user_id=john_doe_id,
    session_id=session_id,
)

# -*- Print the chat history
session_run = memory.runs[session_id][-1]
print_chat_history(session_run)

# You can also get the user memories from the agent
memories = agent.get_user_memories(user_id=john_doe_id)
print("John Doe's memories:")
pprint(memories)
