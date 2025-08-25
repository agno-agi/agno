"""
This example shows how to use the Memory class to create a persistent memory.

Every time you run this, the `Memory` object will be re-initialized from the DB.
"""

from typing import List

from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager, UserMemory
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

memory_db = PostgresDb(db_url=db_url)

memory = MemoryManager(db=memory_db)

john_doe_id = "john_doe@example.com"

# Run 1
memory.add_user_memory(
    memory=UserMemory(memory="The user's name is John Doe", topics=["name"]),
    user_id=john_doe_id,
)

# Run this the 2nd time
memory.add_user_memory(
    memory=UserMemory(
        memory="The user works at a software company called Agno", topics=["work"]
    ),
    user_id=john_doe_id,
)

memories: List[UserMemory] = memory.get_user_memories(user_id=john_doe_id)
print("All memories:")
pprint(memories)
