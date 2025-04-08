"""
This example shows how to use the Memory class to create a persistent memory.

Every time you run this, the `Memory` object will be re-initialized from the DB.
"""

from agno.agent.agent import Agent
from agno.memory_v2.db.memory.sqlite import SqliteMemoryDb
from agno.memory_v2.memory import Memory
from agno.models.google.gemini import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

# No need to set the model, it gets set by the agent to the agent's model
memory = Memory(memory_db=memory_db)

# Reset the memory for this example
memory.clear()

john_doe_id = "john_doe@example.com"

chat_agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    description="You are a helpful assistant that can chat with users",
    memory=memory,
    create_user_memories=True,
)

chat_agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
)

chat_agent.print_response("What are my hobbies?", stream=True, user_id=john_doe_id)


research_agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    description="You are a research assistant that can help users with their research questions",
    tools=[DuckDuckGoTools(cache_results=True)],
    memory=memory,
    create_user_memories=True,
)

research_agent.print_response(
    "I love asking questions about quantum computing. What is the latest news on quantum computing?",
    stream=True,
    user_id=john_doe_id,
)

memories = memory.get_user_memories(user_id=john_doe_id)
print("John Doe's memories:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")
