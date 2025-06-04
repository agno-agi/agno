"""
How to search for user memories using different retrieval methods

- last_n: Retrieves the last n memories
- first_n: Retrieves the first n memories
- semantic: Retrieves memories using semantic search
"""

from agno.memory.v2 import Memory, UserMemory
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.models.google.gemini import Gemini
from rich.pretty import pprint

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")
# Reset for this example
memory_db.clear()

memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"), db=memory_db)

john_doe_id = "john_doe@example.com"
memory.add_user_memory(
    memory=UserMemory(memory="The user enjoys hiking in the mountains on weekends"),
    user_id=john_doe_id,
)
memory.add_user_memory(
    memory=UserMemory(
        memory="The user enjoys reading science fiction novels before bed"
    ),
    user_id=john_doe_id,
)
print("John Doe's memories:")
pprint(memory.memories)

memories = memory.search_user_memories(
    user_id=john_doe_id, limit=1, retrieval_method="last_n"
)
print("\nJohn Doe's last_n memories:")
pprint(memories)

memories = memory.search_user_memories(
    user_id=john_doe_id, limit=1, retrieval_method="first_n"
)
print("\nJohn Doe's first_n memories:")
pprint(memories)

memories = memory.search_user_memories(
    user_id=john_doe_id,
    query="What does the user like to do on weekends?",
    retrieval_method="agentic",
)
print("\nJohn Doe's memories similar to the query (agentic):")
pprint(memories)
