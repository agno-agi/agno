"""
User Profile: Memory Operations
===============================
Add, update, and delete memories.

This cookbook shows the full lifecycle of memories:
- Adding new memories
- Updating existing memories when info changes
- Deleting outdated memories
- The `clear_memories` operation (dangerous, disabled by default)

Run:
    python cookbook/15_learning/user_profile/05_memory_operations.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Full Memory Operations
# ============================================================================
agent = Agent(
    name="Memory Operations Agent",
    model=model,
    db=db,
    instructions="""\
You are an assistant with full control over user memories.

You can:
- ADD memories for new information
- UPDATE memories when information changes
- DELETE memories that are no longer relevant

Be thoughtful about updates and deletes:
- Update when the same thing changes (e.g., new job at same company → new company)
- Delete when information is explicitly wrong or no longer relevant
- Prefer updating over deleting + adding when the topic is the same
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
            agent_can_update_memories=True,
            # Enable all operations
            enable_add_memory=True,
            enable_update_memory=True,
            enable_delete_memory=True,
            enable_clear_memories=False,  # Keep this off (dangerous)
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Add → Update → Delete Lifecycle
# ============================================================================
def demo_memory_lifecycle():
    """Show the full lifecycle of a memory."""
    print("=" * 60)
    print("Demo: Memory Lifecycle (Add → Update → Delete)")
    print("=" * 60)

    user = "lifecycle_demo@example.com"

    # Step 1: Add initial information
    print("\n--- Step 1: Add initial info ---\n")
    agent.print_response(
        "I work at Google as a software engineer. Please remember this.",
        user_id=user,
        session_id="lifecycle_1",
        stream=True,
    )

    # Step 2: Update when it changes
    print("\n--- Step 2: Update (job change) ---\n")
    agent.print_response(
        "Actually, I just switched jobs! I now work at Anthropic as a research scientist. "
        "Please update my information.",
        user_id=user,
        session_id="lifecycle_2",
        stream=True,
    )

    # Check current state
    print("\n--- Check current state ---\n")
    agent.print_response(
        "What do you know about my job?",
        user_id=user,
        session_id="lifecycle_3",
        stream=True,
    )

    # Step 3: Delete outdated info
    print("\n--- Step 3: Delete (no longer relevant) ---\n")
    agent.print_response(
        "I'd like you to forget where I work - I prefer to keep that private now.",
        user_id=user,
        session_id="lifecycle_4",
        stream=True,
    )

    # Final state
    print("\n--- Final state ---\n")
    agent.print_response(
        "What do you remember about me?",
        user_id=user,
        session_id="lifecycle_5",
        stream=True,
    )


# ============================================================================
# Demo: Correction Flow
# ============================================================================
def demo_correction():
    """Show correcting wrong information."""
    print("\n" + "=" * 60)
    print("Demo: Correction Flow")
    print("=" * 60)

    user = "correction_demo@example.com"

    # Initial (with a mistake)
    print("\n--- Initial info (with mistake) ---\n")
    agent.print_response(
        "I'm a Python developer who uses Django. Remember this.",
        user_id=user,
        session_id="correct_1",
        stream=True,
    )

    # Correction
    print("\n--- Correction ---\n")
    agent.print_response(
        "Wait, I made a mistake. I use FastAPI, not Django. Please correct that.",
        user_id=user,
        session_id="correct_2",
        stream=True,
    )

    # Verify
    print("\n--- Verify correction ---\n")
    agent.print_response(
        "What framework do I use?",
        user_id=user,
        session_id="correct_3",
        stream=True,
    )


# ============================================================================
# Demo: Incremental Updates
# ============================================================================
def demo_incremental_updates():
    """Show adding more detail to existing memories."""
    print("\n" + "=" * 60)
    print("Demo: Incremental Updates")
    print("=" * 60)

    user = "incremental_demo@example.com"

    # Start simple
    print("\n--- Start simple ---\n")
    agent.print_response(
        "I like coffee.",
        user_id=user,
        session_id="incr_1",
        stream=True,
    )

    # Add detail
    print("\n--- Add detail ---\n")
    agent.print_response(
        "Specifically, I love oat milk lattes. Update what you know about my coffee preference.",
        user_id=user,
        session_id="incr_2",
        stream=True,
    )

    # Add more
    print("\n--- Add more context ---\n")
    agent.print_response(
        "And I always get a large. I'm very particular about this.",
        user_id=user,
        session_id="incr_3",
        stream=True,
    )

    # Final state
    print("\n--- Final memory ---\n")
    agent.print_response(
        "What do you know about my coffee preferences?",
        user_id=user,
        session_id="incr_4",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_memory_lifecycle()
    demo_correction()
    demo_incremental_updates()

    print("\n" + "=" * 60)
    print("✅ Memory operations: add, update, delete")
    print("   Update > delete+add for same topics")
    print("   clear_memories is disabled by default (dangerous)")
    print("=" * 60)
