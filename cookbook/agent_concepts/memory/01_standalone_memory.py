"""
How to add, get, delete, and replace user memories manually
"""

from agno.memory.v2 import Memory, UserMemory
from rich.pretty import pprint

memory = Memory()

# Add a memory for the default user
memory.add_user_memory(
    memory=UserMemory(memory="The user's name is John Doe", topics=["name"]),
)
print("Memories:")
pprint(memory.memories)

# Add memories for Jane Doe
jane_doe_id = "jane_doe@example.com"
print(f"\nUser: {jane_doe_id}")
memory_id_1 = memory.add_user_memory(
    memory=UserMemory(memory="The user's name is Jane Doe", topics=["name"]),
    user_id=jane_doe_id,
)
memory_id_2 = memory.add_user_memory(
    memory=UserMemory(memory="She likes to play tennis", topics=["hobbies"]),
    user_id=jane_doe_id,
)
memories = memory.get_user_memories(user_id=jane_doe_id)
print("Memories:")
pprint(memories)

# Delete a memory
print("\nDeleting memory")
memory.delete_user_memory(user_id=jane_doe_id, memory_id=memory_id_2)
print("Memory deleted\n")
memories = memory.get_user_memories(user_id=jane_doe_id)
print("Memories:")
pprint(memories)

# Replace a memory
print("\nReplacing memory")
memory.replace_user_memory(
    memory_id=memory_id_1,
    memory=UserMemory(memory="The user's name is Jane Mary Doe", topics=["name"]),
    user_id=jane_doe_id,
)
print("Memory replaced")
memories = memory.get_user_memories(user_id=jane_doe_id)
print("Memories:")
pprint(memories)
