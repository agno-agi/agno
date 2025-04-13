"""
This example shows how to use the Memory class to create a persistent memory.

Every time you run this, the `Memory` object will be re-initialized from the DB.
"""

from typing import List

from agno.memory.v2.db.schema import MemoryRow
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.memory.v2.schema import UserMemory
from rich.pretty import pprint

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

# Clear the DB
memory_db.clear()

memory = Memory(db=memory_db)

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

memories: List[MemoryRow] = memory_db.read_memories()
print("All memories:")
pprint(memories)
