from agno.agent.agent import Agent
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai.chat import OpenAIChat
from agno.storage.postgres import PostgresStorage

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

memory = Memory(db=PostgresMemoryDb(table_name="agent_memories", db_url=db_url))

session_id = "postgres_memories"
user_id = "postgres_user"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    storage=PostgresStorage(table_name="agent_sessions", db_url=db_url),
    enable_user_memories=True,
    enable_session_summaries=True,
)

agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=user_id,
    session_id=session_id,
)

agent.print_response(
    "What are my hobbies?", stream=True, user_id=user_id, session_id=session_id
)
