from agno.memory.v2.memory import Memory, UserMemory
from agno.models.google.gemini import Gemini

memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"), debug_mode=True)

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

# This searches using a model
memories = memory.search_user_memories(
    user_id=john_doe_id,
    query="What does the user like to do on weekends?",
    retrieval_method="semantic",
)
print("John Doe's last_n memories:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")
