"""
Create user memories with an Agent by providing a either text or a list of messages.
"""

from textwrap import dedent

from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager, UserMemory
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

memory_manager = MemoryManager(
    db=db,
    model=OpenAIChat(id="gpt-4o"),
    memory_capture_instructions=dedent("""\
            Memories should only include details about the user's academic interests.
            Ignore names, hobbies, and personal interests.
            """),
)

user_id = "ava@ava.com"

memory_manager.add_user_memory(
    memory=UserMemory(
        memory=dedent("""\
    My name is Ava and I like to ski.
    I live in San Francisco and study geometric neuron architecture.
    """)
    ),
    user_id=user_id,
)


memories = memory_manager.get_user_memories(user_id=user_id)
print("Ava's memories:")
pprint(memories)
