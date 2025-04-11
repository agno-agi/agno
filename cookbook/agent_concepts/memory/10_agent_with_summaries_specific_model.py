"""
This example shows how to use the Memory class to create a persistent memory.

Every time you run this, the `Memory` object will be re-initialized from the DB.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.memory.v2.summarizer import SessionSummarizer
from agno.models.openai.chat import OpenAIChat
from agno.storage.sqlite import SqliteStorage

agent_storage = SqliteStorage(
    table_name="agent_sessions", db_file="tmp/persistent_memory.db"
)

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

memory = Memory(
    db=memory_db, summarizer=SessionSummarizer(model=OpenAIChat(id="gpt-4o-mini"))
)

# Reset the memory for this example
memory.clear()

session_id_1 = "1001"
john_doe_id = "john_doe@example.com"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_session_summaries=True,
    storage=agent_storage,
)

agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
    session_id=session_id_1,
)

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

print(
    f"Session summary: {memory.get_session_summary(user_id=mark_gonzales_id, session_id=session_id_2).summary}\n"
)
