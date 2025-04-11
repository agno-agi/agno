"""
This example shows how to use the `add_session_summary_references` parameter in the Agent config to
add references to the session summaries to the Agent.

Start the postgres db locally on Docker by running: cookbook/scripts/run_pgvector.sh

Note: Session summaries are stored in the storage table along with the session, not the memory table.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.google.gemini import Gemini
from agno.storage.postgres import PostgresStorage

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

memory_db = PostgresMemoryDb(table_name="memory", db_url=db_url)

# Reset for this example
memory_db.clear()

memory = Memory(db=memory_db)

user_id = "john_doe@example.com"
session_id = "session_summaries"

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    memory=memory,
    storage=PostgresStorage(table_name="agent_sessions", db_url=db_url),
    enable_session_summaries=True,
    session_id=session_id,
)

# This will create a new session summary
agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    user_id=user_id,
)

# You can use existing session summaries from session storage without creating or updating any new ones.
agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    memory=memory,
    storage=PostgresStorage(table_name="agent_sessions", db_url=db_url),
    add_session_summary_references=True,
    session_id=session_id,
)

# agent = Agent(
#     model=Gemini(id="gemini-2.0-flash-exp"),
#     memory=memory,
#     storage=SqliteStorage(table_name="agent_sessions", db_file="tmp/persistent_memory.db"),
#     enable_session_summaries=True,
#     add_session_summary_references=False,
# )

agent.print_response("What are my hobbies?", user_id=user_id)
