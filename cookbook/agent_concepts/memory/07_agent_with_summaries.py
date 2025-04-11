"""
This example demonstrates how to create session summaries.

To enable this, set `enable_session_summaries=True` in the Agent config.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.memory.v2.summarizer import SessionSummarizer
from agno.models.anthropic.claude import Claude

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

memory = Memory(
    db=memory_db,
    summarizer=SessionSummarizer(model=Claude(id="claude-3-5-sonnet-20241022")),
)

# Reset the memory for this example
memory.clear()

session_id_1 = "1001"
john_doe_id = "john_doe@example.com"

agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20241022"),
    memory=memory,
    enable_user_memories=True,
    enable_session_summaries=True,
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
