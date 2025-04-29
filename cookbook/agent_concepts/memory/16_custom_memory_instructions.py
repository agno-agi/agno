"""
Create user memories with an Agent by providing a either text or a list of messages.
"""

from textwrap import dedent

from agno.memory.v2 import Memory
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.manager import MemoryManager
from agno.models.google import Gemini
from rich.pretty import pprint

memory = Memory(
    db=SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db"),
    memory_manager=MemoryManager(
        model=Gemini(id="gemini-2.0-flash-exp"),
        memory_capture_instructions=dedent("""\
            Memories should only include details about the user's academic interests.
            Ignore names, hobbies, and personal interests.
            """),
    ),
)
# Reset the memory for this example
memory.clear()

user_id = "ava@ava.com"

memory.create_user_memories(
    message=dedent("""\
    My name is Ava and I like to ski.
    I live in San Francisco and study geometric neuron architecture.
    """),
    user_id=user_id,
)


memories = memory.get_user_memories(user_id=user_id)
print("Ava's memories:")
pprint(memories)
