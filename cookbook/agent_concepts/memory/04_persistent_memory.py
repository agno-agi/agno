"""
This example shows how to use the Memory class to create a persistent memory.

Every time you run this, the `Memory` object will be re-initialized from the DB.
"""

from typing import List

from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.memory.v2.memory import Memory
from agno.models.google.gemini import Gemini

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")
memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"), db=memory_db)

john_doe_id = "john_doe@example.com"

# Run 1
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

# Run this the 2nd time
# memory.create_user_memory(
#     message="""
#     I work at a software company called Agno and code in Python.
#     """,
#     user_id=john_doe_id
# )


memories: List[MemoryRow] = memory_db.read_memories()
print("All the DB memories:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory['memory']} ({m.last_updated})")
