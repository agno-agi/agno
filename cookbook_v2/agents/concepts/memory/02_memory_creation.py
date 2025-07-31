"""
Create user memories with an Agent by providing a either text or a list of messages.
"""

from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, user_memory_table="user_memories")

memory = MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=db)

memory.clear()

john_doe_id = "john_doe@example.com"

# 1. Create memories using string as an input
memory.create_user_memories(
    message="""\
I enjoy hiking in the mountains on weekends,
reading science fiction novels before bed,
cooking new recipes from different cultures,
playing chess with friends,
and attending live music concerts whenever possible.
Photography has become a recent passion of mine, especially capturing landscapes and street scenes.
I also like to meditate in the mornings and practice yoga to stay centered.
""",
    user_id=john_doe_id,
)

memories = memory.get_user_memories(user_id=john_doe_id)
print("John Doe's memories:")
pprint(memories)

# 2. Create memories using a list of messages
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
