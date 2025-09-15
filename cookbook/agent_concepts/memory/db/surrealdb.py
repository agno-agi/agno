from agno.agent.agent import Agent
from agno.memory.v2.db.surrealdb import SurrealMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.ollama import OllamaChat
from agno.storage.surrealdb import SurrealDbStorage

memory = Memory(db=SurrealMemoryDb(table="agent_memories", client=client))

session_id = "mongodb_memories"
user_id = "mongodb_user"

agent = Agent(
    model=OllamaChat(id="llama3.2"),
    memory=memory,
    storage=SurrealDbStorage(collection_name="agent_sessions", client=client),
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
