from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryManagerV2
from agno.models.openai import OpenAIChat

db = SqliteDb(db_file="tmp/memory.db")
memory = MemoryManagerV2(db=db)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory_manager_v2=memory,
    enable_agentic_memory_v2=True,
    user_id="sarah",
    debug_mode=True,
    markdown=True,
)

# Conversation 1: Profile + Policy info
agent.print_response(
    "Hi, I'm Sarah, a data scientist at TechCorp. Please be concise and always include code examples.",
    stream=True,
)

# Conversation 2: Knowledge (context)
agent.print_response(
    "I'm working on a fraud detection project using Python and Spark.",
    stream=True,
)

# Conversation 3: Test that agent uses memory
agent.print_response(
    "How do I handle missing values?",
    stream=True,
)

# Conversation 4: Feedback signal
agent.print_response(
    "Perfect! That was exactly what I needed - short and with code.",
    stream=True,
)

# Conversation 5: Test recall
agent.print_response(
    "What do you know about me and my preferences?",
    stream=True,
)

# Print all 4 memory layers (in authority order)
print("\n" + "=" * 60)
print("USER MEMORY LAYERS (in authority order)")
print("=" * 60)

user = memory.get_user("sarah")
if user:
    print("\n1. POLICIES (highest authority - preferences/constraints):")
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

    print("\n3. KNOWLEDGE (learned patterns/context):")
    knowledge = user.memory_layers.get("knowledge", [])
    if knowledge:
        for item in knowledge:
            if isinstance(item, dict):
                print(f"   {item.get('key', 'unknown')}: {item.get('value', item)}")
            else:
                print(f"   - {item}")
    else:
        print("   (none)")

    print("\n4. FEEDBACK (lowest authority - what works/doesn't):")
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
