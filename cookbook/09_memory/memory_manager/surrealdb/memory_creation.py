"""
Create user memories with an Agent by providing a either text or a list of messages.
"""

from agno.db.surrealdb import SurrealDb
from agno.memory import MemoryManager, UserMemory
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# Setup database and user
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "agno"
SURREALDB_DATABASE = "memories"

creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
memory_db = SurrealDb(
    None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE
)
memory = MemoryManager(model=OpenAIChat(id="gpt-4o"), db=memory_db)

john_doe_id = "john_doe@example.com"
memory.add_user_memory(
    memory=UserMemory(
        memory="""
I enjoy hiking in the mountains on weekends,
reading science fiction novels before bed,
cooking new recipes from different cultures,
playing chess with friends,
and attending live music concerts whenever possible.
Photography has become a recent passion of mine, especially capturing landscapes and street scenes.
I also like to meditate in the mornings and practice yoga to stay centered.
"""
    ),
    user_id=john_doe_id,
)


memories = memory.get_user_memories(user_id=john_doe_id)
print("John Doe's memories:")
pprint(memories)

jane_doe_id = "jane_doe@example.com"
# Send a history of messages and add memories
memory.create_user_memories(
    messages=[
        Message(role="user", content="My name is Jane Doe"),
        Message(role="assistant", content="That is great!"),
        Message(role="user", content="I like to play chess"),
        Message(role="assistant", content="That is great!"),
    ],
    user_id=jane_doe_id,
)

memories = memory.get_user_memories(user_id=jane_doe_id)
print("Jane Doe's memories:")
pprint(memories)
