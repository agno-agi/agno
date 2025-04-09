from agno.memory.v2 import Memory
from agno.models.google import Gemini

memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"))

john_doe_id = "john_doe@example.com"

memory.create_user_memory(
    message="""
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
for i, m in enumerate(memories):
    print(f"{i}: {m.memory} - {m.topics}")
