"""
How to add, get, delete, and replace user memories manually
"""

from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager, UserMemory
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, memory_table="standalone_memories")

memory = MemoryManager(db=db)

# 1. Add a memory for the default user
memory.add_user_memory(
    memory=UserMemory(
        memory="The user's name is John Doe",
        topics=["name"],
    ),
)
print("\nUser: default")
print("Memories:")
pprint(memory.get_user_memories())

# 2. Add memories for a specific user (Jane Doe)
jane_doe_id = "jane_doe@example.com"
print(f"\nUser: {jane_doe_id}")
memory_id_1 = memory.add_user_memory(
    memory=UserMemory(
        memory="The user's name is Jane Doe",
        topics=["name"],
    ),
    user_id=jane_doe_id,
)
memory_id_2 = memory.add_user_memory(
    memory=UserMemory(memory="She likes to play tennis", topics=["hobbies"]),
    user_id=jane_doe_id,
)
memories = memory.get_user_memories(user_id=jane_doe_id)
print("Memories for Jane Doe:")
pprint(memories)

# 3. Delete a memory
print("\nDeleting second memory for Jane Doe")
memory.delete_user_memory(user_id=jane_doe_id, memory_id=memory_id_2)
print("Memory deleted\n")
memories = memory.get_user_memories(user_id=jane_doe_id)
print("Memories for Jane Doe:")
pprint(memories)

# 4. Replace a memory
print("\nReplacing memory")
memory.replace_user_memory(
    memory_id=memory_id_1,
    memory=UserMemory(memory="The user's name is Jane Mary Doe", topics=["name"]),
    user_id=jane_doe_id,
)
print("Memory replaced")
memories = memory.get_user_memories(user_id=jane_doe_id)
print("Memories for Jane Doe:")
pprint(memories)
