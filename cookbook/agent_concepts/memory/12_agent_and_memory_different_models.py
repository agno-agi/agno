"""
This example shows how to use the Memory class to create a persistent memory.

Every time you run this, the `Memory` object will be re-initialized from the DB.
"""

from agno.agent.agent import Agent
from agno.memory_v2.db.memory.sqlite import SqliteMemoryDb
from agno.memory_v2.memory import Memory
from agno.models.anthropic.claude import Claude
from agno.models.google.gemini import Gemini
from agno.models.openai.chat import OpenAIChat

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

# No need to set the model, it gets set by the agent to the agent's model
memory = Memory(model=Claude(id="claude-3-5-sonnet-20241022"), memory_db=memory_db)

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
