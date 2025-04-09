from agno.memory.v2 import Memory, UserMemory

memory = Memory()

# Add a memory for the default user
memory.add_user_memory(
    memory=UserMemory(memory="The user's name is John Doe", topics=["name"]),
)

for user_id, user_memories in memory.memories.items():
    print(f"User: {user_id}")
    for um in user_memories.values():
        print(um.memory)
print()


# Add memories for Jane Doe
jane_doe_id = "jane_doe@example.com"
print(f"User: {jane_doe_id}")
memory_id_1 = memory.add_user_memory(
    memory=UserMemory(memory="The user's name is Jane Doe", topics=["name"]),
    user_id=jane_doe_id,
)
memory_id_2 = memory.add_user_memory(
    memory=UserMemory(memory="She likes to play tennis", topics=["hobbies"]),
    user_id=jane_doe_id,
)

memories = memory.get_user_memories(user_id=jane_doe_id)
for m in memories:
    print(m.memory)
print()

# Delete a memory
memory.delete_user_memory(user_id=jane_doe_id, memory_id=memory_id_2)
print("Memory deleted\n")
memories = memory.get_user_memories(user_id=jane_doe_id)
for m in memories:
    print(m.memory)
print()
# Replace a memory
memory.replace_user_memory(
    memory_id=memory_id_1,
    memory=UserMemory(memory="The user's name is Jane Mary Doe", topics=["name"]),
    user_id=jane_doe_id,
)
print("Memory replaced\n")
memories = memory.get_user_memories(user_id=jane_doe_id)
for m in memories:
    print(m.memory)
