"""
This example shows how to use the Memory class to create a persistent memory.

Every time you run this, the `Memory` object will be re-initialized from the DB.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.google.gemini import Gemini

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

# No need to set the model, it gets set by the agent to the agent's model
memory = Memory(db=memory_db)

# Reset the memory for this example
memory.clear()

session_id_1 = "1001"
john_doe_id = "john_doe@example.com"

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    memory=memory,
    create_user_memories=True,
    create_session_summaries=True,
)

agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
    session_id=session_id_1,
)

agent.print_response(
    "What are my hobbies?", stream=True, user_id=john_doe_id, session_id=session_id_1
)


memories = memory.get_user_memories(user_id=john_doe_id)
print("John Doe's memories:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")
session_summary = memory.get_session_summary(
    user_id=john_doe_id, session_id=session_id_1
)
print(f"Session summary: {session_summary.summary}\n")


session_id_2 = "1002"
mark_gonzales_id = "mark@example.com"

agent.print_response(
    "My name is Mark Gonzales and I like anime and video games.",
    stream=True,
    user_id=mark_gonzales_id,
    session_id=session_id_2,
)

agent.print_response(
    "What are my hobbies?",
    stream=True,
    user_id=mark_gonzales_id,
    session_id=session_id_2,
)


memories = memory.get_user_memories(user_id=mark_gonzales_id)
print("Mark Gonzales's memories:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")
print(
    f"Session summary: {memory.get_session_summary(user_id=mark_gonzales_id, session_id=session_id_2).summary}\n"
)
