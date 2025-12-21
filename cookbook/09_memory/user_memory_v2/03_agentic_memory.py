"""Agentic Memory - Sarah explicitly manages her memory.

This continues Sarah's story from 02_automatic_learning.py.
The agent has TOOLS to save, update, and delete memory on request.

Run after 02_automatic_learning.py to see memory accumulate.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# Same database as previous cookbooks
DB_FILE = "tmp/user_memory.db"
USER_ID = "sarah"

db = SqliteDb(db_file=DB_FILE)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_agentic_memory_v2=True,  # Auto-creates MemoryCompiler with tools
    markdown=True,
)

# Show what we already know about Sarah
print("=" * 60)
print("EXISTING MEMORY (from previous cookbooks)")
print("=" * 60)
existing = agent.get_user_profile(USER_ID)
if existing:
    print("\nProfile:", existing.user_profile)
    print("Knowledge:", existing.memory_layers.get("knowledge", []))
else:
    print("\n(No existing memory - run 01 and 02 first for full experience)")

# Conversation 1: Sarah asks agent to remember something
print("\n" + "=" * 60)
print("Conversation 1: Explicit save request")
agent.print_response(
    "Please remember that I prefer using Pydantic for data validation in all my APIs.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 2: Sarah asks to update/correct information
print("\nConversation 2: Update existing information")
agent.print_response(
    "Actually, I've been promoted. Update my role - I'm now a Staff Engineer, not just tech lead.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 3: Sarah asks to forget something
print("\nConversation 3: Forget request")
agent.print_response(
    "Forget that I work on the payment service. I've moved to the authentication team now.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 4: Add new context
print("\nConversation 4: Add new project context")
agent.print_response(
    "Add to my context: I'm now implementing OAuth2 and OpenID Connect for our platform. "
    "We're using authlib as the main library.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 5: Test recall with updated memory
print("\nConversation 5: Verify updates")
agent.print_response(
    "What's my current role and what project am I working on now?",
    user_id=USER_ID,
    stream=True,
)

# Conversation 6: Add a policy
print("\nConversation 6: Add a preference")
agent.print_response(
    "From now on, always include security considerations when discussing auth code.",
    user_id=USER_ID,
    stream=True,
)

# Show final memory state
print("\n" + "=" * 60)
print("FINAL MEMORY STATE (after agentic updates)")
print("=" * 60)

user = agent.get_user_profile(USER_ID)
if user:
    print("\nProfile:")
    pprint(user.user_profile)

    print("\nPolicies:")
    pprint(user.memory_layers.get("policies", {}))

    print("\nKnowledge:")
    pprint(user.memory_layers.get("knowledge", []))

    print("\nFeedback:")
    pprint(user.memory_layers.get("feedback", {}))

# Show compiled context
print("\n" + "=" * 60)
print("COMPILED CONTEXT (what agent sees)")
print("=" * 60)
print(agent.memory_compiler.compile_user_memory(USER_ID))

print("\n" + "=" * 60)
print("Run 05_persistence.py to see memory survive app restart!")
print("=" * 60)
