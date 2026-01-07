"""
How to search for user memories using different retrieval methods

- last_n: Retrieves the last n memories
- first_n: Retrieves the first n memories
- semantic: Retrieves memories using semantic search
"""

from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager, UserMemory
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

memory_db = PostgresDb(db_url=db_url)

memory = MemoryManager(model=OpenAIChat(id="gpt-4o"), db=memory_db)

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
pprint(memory.get_user_memories(user_id=john_doe_id))

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
