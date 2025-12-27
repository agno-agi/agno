"""
This example shows you how to use persistent memory with an Agent.

During each run the Agent can create/update/delete user memories.

To enable this, set `enable_agentic_memory=True` in the Agent config.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager  # noqa: F401
from agno.models.openai import OpenAIChat
from agno.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

john_doe_id = "john_doe@example.com"

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
)

team = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[agent],
    db=db,
    enable_agentic_memory=True,
)

team.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
)

team.print_response("What are my hobbies?", stream=True, user_id=john_doe_id)

# More examples:
# agent.print_response(
#     "Remove all existing memories of me.",
#     stream=True,
#     user_id=john_doe_id,
# )

# agent.print_response(
#     "My name is John Doe and I like to paint.", stream=True, user_id=john_doe_id
# )

# agent.print_response(
#     "I don't pain anymore, i draw instead.", stream=True, user_id=john_doe_id
# )
