"""Basic Memory V2 - First meeting with Sarah.

This is the first cookbook in the memory evolution series.
Sarah introduces herself as a backend engineer and states her preferences.

Run cookbooks in order (01 -> 02 -> 03 -> 05) to see memory accumulate.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

DB_FILE = "tmp/user_memory.db"
USER_ID = "sarah"

db = SqliteDb(db_file=DB_FILE)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_agentic_memory_v2=True,
    markdown=True,
    user_id=USER_ID,
)

agent.print_response(
    "Hi, I'm Sarah, a backend engineer at TechCorp. I work with Python and Go.",
)

agent.print_response(
    "Please be concise and always include code examples when explaining things.",
)

agent.print_response(
    "Forget my workplace details.",
)

agent.print_response(
    "I'm currently building a REST API for our payment service using FastAPI.",
)

agent.print_response(
    "What's a good way to structure API endpoints?",
)

agent.print_response(
    "What do you know about me and my work?",
)

agent.print_response(
    "I don't like a lot of code. Focus on explaining to me the concept in detail without code examples.",
)

print("\n" + "=" * 60)
print("SARAH'S MEMORY PROFILE")
print("=" * 60)

user = agent.get_user_profile(USER_ID)
if user:
    pprint(user.to_dict())
else:
    print("No user memory found")
