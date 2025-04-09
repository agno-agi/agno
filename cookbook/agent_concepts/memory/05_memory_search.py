from agno.memory.v2.memory import Memory, UserMemory

memory = Memory()

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

memories = memory.search_user_memories(
    user_id=john_doe_id, limit=1, retrieval_method="last_n"
)
print("John Doe's last_n memories:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")


memories = memory.search_user_memories(
    user_id=john_doe_id, limit=1, retrieval_method="first_n"
)
print("John Doe's first_n memories:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")
