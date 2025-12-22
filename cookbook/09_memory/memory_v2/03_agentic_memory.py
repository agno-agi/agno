"""Agentic Memory - Sarah explicitly manages her memory.

This continues Sarah's story from 02_automatic_learning.py.
The agent has TOOLS to save, update, and delete memory on request.

Run after 02_automatic_learning.py to see memory accumulate.
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
)

existing = agent.get_user_profile(USER_ID)
if existing:
    print("Existing profile:")
    pprint(existing.to_dict())

agent.print_response(
    "Please remember that I prefer using Pydantic for data validation in all my APIs.",
    user_id=USER_ID,
    stream=True,
)

agent.print_response(
    "Actually, I've been promoted. Update my role - I'm now a Staff Engineer, not just tech lead.",
    user_id=USER_ID,
    stream=True,
)

agent.print_response(
    "Forget that I work on the payment service. I've moved to the authentication team now.",
    user_id=USER_ID,
    stream=True,
)

agent.print_response(
    "Add to my context: I'm now implementing OAuth2 and OpenID Connect for our platform. "
    "We're using authlib as the main library.",
    user_id=USER_ID,
    stream=True,
)

agent.print_response(
    "What's my current role and what project am I working on now?",
    user_id=USER_ID,
    stream=True,
)

agent.print_response(
    "From now on, always include security considerations when discussing auth code.",
    user_id=USER_ID,
    stream=True,
)

print("\n" + "=" * 60)
print("FINAL MEMORY STATE")
print("=" * 60)

user = agent.get_user_profile(USER_ID)
if user:
    pprint(user.to_dict())
