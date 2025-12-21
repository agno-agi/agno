"""Basic Memory V2 - First meeting with Sarah.

This is the first cookbook in the memory evolution series.
Sarah introduces herself as a backend engineer and states her preferences.

Run cookbooks in order (01 -> 02 -> 03 -> 05) to see memory accumulate.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# Shared database for all cookbooks
DB_FILE = "tmp/user_memory.db"
USER_ID = "sarah"

db = SqliteDb(db_file=DB_FILE)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_agentic_memory_v2=True,  # Auto-creates MemoryCompiler
    markdown=True,
)

# Conversation 1: Sarah introduces herself
print("Conversation 1: Sarah introduces herself")
agent.print_response(
    "Hi, I'm Sarah, a backend engineer at TechCorp. I work with Python and Go.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 2: States preferences (becomes policy)
print("\nConversation 2: Sarah states her preferences")
agent.print_response(
    "Please be concise and always include code examples when explaining things.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 3: Forget where I work
print("\nConversation 3: Forget where I work")
agent.print_response(
    "Forget my workplace details.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 4: Shares current project (becomes knowledge)
print("\nConversation 4: Sarah shares her current project")
agent.print_response(
    "I'm currently building a REST API for our payment service using FastAPI.",
    user_id=USER_ID,
    stream=True,
)

# Conversation 4: Test that agent uses memory
print("\nConversation 5: Technical question (agent should use context)")
agent.print_response(
    "What's a good way to structure API endpoints?",
    user_id=USER_ID,
    stream=True,
)

# Conversation 5: Test recall
print("\nConversation 6: Test memory recall")
agent.print_response(
    "What do you know about me and my work?",
    user_id=USER_ID,
    stream=True,
)

# Print all 4 memory layers
print("\n" + "=" * 60)
print("SARAH'S MEMORY PROFILE (after 01_basic.py)")
print("=" * 60)

user = agent.get_user_profile(USER_ID)
if user:
    print("\n1. POLICIES (preferences/constraints):")
    policies = user.memory_layers.get("policies", {})
    if policies:
        for key, value in policies.items():
            print(f"   {key}: {value}")
    else:
        print("   (none)")

    print("\n2. PROFILE (identity info):")
    if user.user_profile:
        for key, value in user.user_profile.items():
            print(f"   {key}: {value}")
    else:
        print("   (none)")

    print("\n3. KNOWLEDGE (context/facts):")
    knowledge = user.memory_layers.get("knowledge", [])
    if knowledge:
        for item in knowledge:
            if isinstance(item, dict):
                print(f"   {item.get('key', 'unknown')}: {item.get('value', item)}")
            else:
                print(f"   - {item}")
    else:
        print("   (none)")

    print("\n4. FEEDBACK (what works/doesn't):")
    feedback = user.memory_layers.get("feedback", {})
    if feedback:
        if isinstance(feedback, dict):
            positive = feedback.get("positive", [])
            negative = feedback.get("negative", [])
            if positive:
                print("   positive:")
                for item in positive:
                    print(f"     - {item}")
            if negative:
                print("   negative:")
                for item in negative:
                    print(f"     - {item}")
            if not positive and not negative:
                print("   (none)")
        else:
            for item in feedback:
                print(f"   - {item}")
    else:
        print("   (none)")
else:
    print("No user memory found")

print("\n" + "=" * 60)
print("Run 02_automatic_learning.py next to see memory evolve!")
print("=" * 60)
