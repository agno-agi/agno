"""
User Profile: Memory Operations
===============================
Add, update, and delete memories programmatically.

Memories in UserProfile are a list of observations. This cookbook
shows how to manage them:
- Add new memories
- Update existing memories
- Delete memories
- Clear all memories (dangerous!)

Run:
    python cookbook/15_learning/user_profile/05_memory_operations.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# ============================================================================
# Agent with Full Memory Operations
# ============================================================================
agent = Agent(
    name="Memory Operations Agent",
    model=model,
    db=db,
    instructions="""\
You manage user memories. You can:
- Add new memories about the user
- Update existing memories if info changes
- Delete memories if user asks
- List current memories

Be careful with deletions - confirm with the user first.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
            agent_can_update_memories=True,
            agent_can_update_profile=True,
            enable_add_memory=True,
            enable_update_memory=True,
            enable_delete_memory=True,
            enable_clear_memories=False,  # Dangerous - keep disabled
        ),
    ),
    markdown=True,
)


# ============================================================================
# Helper
# ============================================================================
def show_memories(user_id: str) -> None:
    """Display current memories."""
    store = agent.learning.user_profile_store
    profile = store.get(user_id=user_id) if store else None

    print("\n" + "-" * 40)
    print("📝 Current Memories:")
    print("-" * 40)

    if not profile or not profile.memories:
        print("  (no memories)")
        return

    for mem in profile.memories:
        if isinstance(mem, dict):
            mem_id = mem.get("id", "?")
            content = mem.get("content", str(mem))
            print(f"  [{mem_id}] {content}")
        else:
            print(f"  - {mem}")


# ============================================================================
# Demo: Add Memories
# ============================================================================
def demo_add_memories():
    """Show adding memories via the agent."""
    print("=" * 60)
    print("Demo: Adding Memories")
    print("=" * 60)

    user = "memory_ops@example.com"

    # Add first memory
    print("\n--- Add first memory ---\n")
    agent.print_response(
        "Remember that I prefer Python for scripting tasks.",
        user_id=user,
        session_id="add_1",
        stream=True,
    )
    show_memories(user)

    # Add second memory
    print("\n--- Add second memory ---\n")
    agent.print_response(
        "Also remember that I work best in the mornings.",
        user_id=user,
        session_id="add_2",
        stream=True,
    )
    show_memories(user)

    # Add third memory
    print("\n--- Add third memory ---\n")
    agent.print_response(
        "One more thing: I'm currently learning Rust.",
        user_id=user,
        session_id="add_3",
        stream=True,
    )
    show_memories(user)

    return user


# ============================================================================
# Demo: Update Memory
# ============================================================================
def demo_update_memory(user_id: str):
    """Show updating an existing memory."""
    print("\n" + "=" * 60)
    print("Demo: Updating a Memory")
    print("=" * 60)

    print("\n--- Update: No longer learning Rust ---\n")
    agent.print_response(
        "Update my memory: I've finished learning Rust basics, "
        "now I'm proficient in it.",
        user_id=user_id,
        session_id="update_1",
        stream=True,
    )
    show_memories(user_id)


# ============================================================================
# Demo: Delete Memory
# ============================================================================
def demo_delete_memory(user_id: str):
    """Show deleting a specific memory."""
    print("\n" + "=" * 60)
    print("Demo: Deleting a Memory")
    print("=" * 60)

    print("\n--- Delete: Morning preference no longer true ---\n")
    agent.print_response(
        "Please delete the memory about me working best in mornings - "
        "my schedule changed and that's no longer accurate.",
        user_id=user_id,
        session_id="delete_1",
        stream=True,
    )
    show_memories(user_id)


# ============================================================================
# Demo: Programmatic Operations
# ============================================================================
def demo_programmatic_operations():
    """Show direct manipulation via the store API."""
    print("\n" + "=" * 60)
    print("Demo: Programmatic Memory Operations")
    print("=" * 60)

    user = "programmatic@example.com"
    store = agent.learning.user_profile_store

    # Create profile with memories directly
    print("\n--- Create profile with memories ---\n")
    from agno.learn.schemas import UserProfile

    profile = UserProfile(user_id=user)

    # Add memories programmatically
    mem1_id = profile.add_memory("Prefers dark mode")
    mem2_id = profile.add_memory("Uses VS Code")
    mem3_id = profile.add_memory("Learning Kubernetes")

    print(f"Added memory 1: {mem1_id}")
    print(f"Added memory 2: {mem2_id}")
    print(f"Added memory 3: {mem3_id}")

    # Save to store
    store.save(user_id=user, profile=profile)
    show_memories(user)

    # Update a memory
    print("\n--- Update memory programmatically ---\n")
    profile.update_memory(mem3_id, "Expert in Kubernetes now")
    store.save(user_id=user, profile=profile)
    show_memories(user)

    # Delete a memory
    print("\n--- Delete memory programmatically ---\n")
    profile.delete_memory(mem1_id)
    store.save(user_id=user, profile=profile)
    show_memories(user)

    # Get specific memory
    print("\n--- Get specific memory ---\n")
    mem = profile.get_memory(mem2_id)
    print(f"Memory {mem2_id}: {mem}")


# ============================================================================
# API Reference
# ============================================================================
def api_reference():
    """Print the memory operations API."""
    print("\n" + "=" * 60)
    print("Memory Operations API Reference")
    print("=" * 60)
    print("""
# Via UserProfile object:

profile = UserProfile(user_id="alice")

# Add memory
mem_id = profile.add_memory("Some observation")

# Get memory by ID
mem = profile.get_memory(mem_id)  # Returns dict or None

# Update memory
success = profile.update_memory(mem_id, "Updated content")

# Delete memory
success = profile.delete_memory(mem_id)

# Get all memories as text
text = profile.get_memories_text()

# Memory structure:
{
    "id": "abc123",
    "content": "The observation text",
    # Optional fields:
    "source": "conversation",
    "timestamp": "2024-01-15T10:30:00Z",
}

# Via Store:

store = agent.learning.user_profile_store

# Get profile (returns UserProfile or None)
profile = store.get(user_id="alice")

# Save profile
store.upsert(profile=profile)

# Delete profile entirely
store.delete(user_id="alice")
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    user_id = demo_add_memories()
    demo_update_memory(user_id)
    demo_delete_memory(user_id)
    demo_programmatic_operations()
    api_reference()

    print("\n" + "=" * 60)
    print("✅ Memory Operations:")
    print("   - add_memory(): Create new memory")
    print("   - update_memory(): Modify existing")
    print("   - delete_memory(): Remove specific memory")
    print("   - get_memory(): Retrieve by ID")
    print("=" * 60)
