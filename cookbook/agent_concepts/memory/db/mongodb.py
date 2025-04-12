from agno.agent.agent import Agent
from agno.memory.v2.db.mongodb import MongoMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.storage.mongodb import MongoDbStorage

db_url = "mongodb://mongoadmin:secret@localhost:27017"

memory = Memory(db=MongoMemoryDb(collection_name="agent_memories", db_url=db_url))

session_id = "mongodb_memories"
user_id = "mongodb_user"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    storage=MongoDbStorage(collection_name="agent_sessions", db_url=db_url),
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
