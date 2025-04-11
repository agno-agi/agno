from agno.memory.v2 import Memory
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.models.openrouter.openrouter import OpenRouter

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

# Reset for this example
memory_db.clear()

memory = Memory(
    model=OpenRouter(id="meta-llama/llama-3.3-70b-instruct"),
    db=memory_db,
    debug_mode=True,
)

john_doe_id = "john_doe@example.com"

memory.create_user_memories(
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
    print(f"{i}: {m.memory}")
