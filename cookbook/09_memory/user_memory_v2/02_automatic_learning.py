"""Automatic Learning - Memory deepens through conversation.

This continues Sarah's story from 01_basic.py.
The agent AUTOMATICALLY extracts new information without explicit tools.

Run after 01_basic.py to see memory accumulate.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# Same database as 01_basic.py
DB_FILE = "tmp/user_memory.db"
USER_ID = "sarah"

db = SqliteDb(db_file=DB_FILE)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    update_memory_on_run=True,  # Automatic extraction enabled
    markdown=True,
)

# Show what we already know about Sarah from 01_basic.py
print("=" * 60)
print("EXISTING MEMORY (from previous cookbooks)")
print("=" * 60)
existing = agent.get_user_profile(USER_ID)
if existing:
    print("\nProfile:", existing.user_profile)
    print("Policies:", existing.memory_layers.get("policies", {}))
else:
    print("\n(No existing memory - run 01_basic.py first for full experience)")

# Conversation 1: Sarah shares more technical context
print("\n" + "=" * 60)
print("Conversation 1: Sarah shares migration plans")
agent.print_response(
    "We're migrating our legacy Flask services to FastAPI for better async support. "
    "The payment API I mentioned is the first one we're converting.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 2: Preference refinement (becomes policy)
print("\nConversation 2: Sarah refines her preferences")
agent.print_response(
    "By the way, I prefer seeing error handling patterns rather than just try/except blocks. "
    "Show me structured error responses with proper HTTP status codes.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 3: Technical question - agent uses accumulated context
print("\nConversation 3: Technical question")
agent.print_response(
    "How should I implement rate limiting for our payment API?",
    user_id=USER_ID,
    stream=True,
)

# Conversation 4: Positive feedback signal
print("\nConversation 4: Sarah gives feedback")
agent.print_response(
    "That was exactly what I needed - concise with real code. "
    "The FastAPI middleware approach is perfect for our use case.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 5: More context about team
print("\nConversation 5: Team context")
agent.print_response(
    "I'm the tech lead for a team of 4 backend engineers. "
    "We're also looking into implementing OAuth2 for our microservices.",
    user_id=USER_ID,
    stream=True,
)

# Show updated memory
print("\n" + "=" * 60)
print("UPDATED MEMORY (after automatic extraction)")
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

# Show compiled context (what agent sees)
print("\n" + "=" * 60)
print("COMPILED CONTEXT (injected into agent)")
print("=" * 60)
print(agent.memory_compiler.compile_user_memory(USER_ID))

print("\n" + "=" * 60)
print("Run 03_agentic_memory.py next to see explicit memory management!")
print("=" * 60)
