"""
This example shows how to use the Memory class to create a persistent memory.

Every time you run this, the `Memory` object will be re-initialized from the DB.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic.claude import Claude
from agno.models.google.gemini import Gemini

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

memory = Memory(model=Claude(id="claude-3-5-sonnet-20241022"), db=memory_db)

# Reset the memory for this example
memory.clear()

mark_gonzales_id = "mark@example.com"

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    memory=memory,
    create_user_memories=True,
    user_id=mark_gonzales_id,
)

agent.print_response(
    "My name is Mark Gonzales and I like anime and video games.", stream=True
)

agent.print_response("What are my hobbies?", stream=True)


memories = memory.get_user_memories(user_id=mark_gonzales_id)
print("Mark Gonzales's memories:")
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")
