"""
Create user memories with an Agent by providing a either text or a list of messages.
"""

from agno.memory.v2 import Memory
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.models.google import Gemini
from agno.models.message import Message
from rich.pretty import pprint

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")
# Reset for this example
memory_db.clear()

memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"), db=memory_db)

john_doe_id = "john_doe@example.com"

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
