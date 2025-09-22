"""
This example shows you how to use persistent memory with an Agent.

After each run, user memories are created/updated.

To enable this, set `enable_user_memories=True` in the Agent config.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager  # noqa: F401
from agno.models.openai import OpenAIChat
from agno.team import Team
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

session_id = str(uuid4())
john_doe_id = "john_doe@example.com"

memory_manager = MemoryManager(model=OpenAIChat(id="o3-mini"))

memory_manager.clear()

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
)
team = Team(
    model=OpenAIChat(id="o3-mini"),
    memory_manager=memory_manager,
    members=[agent],
    db=db,
    enable_user_memories=True,
)

team.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
    session_id=session_id,
)
team.print_response(
    "What are my hobbies?", stream=True, user_id=john_doe_id, session_id=session_id
)

# # You can also get the user memories from the agent
memories = team.get_user_memories(user_id=john_doe_id)
print("John Doe's memories:")
pprint(memories)
