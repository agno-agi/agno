"""
Session Context: Context Continuity
===================================
Building on previous context.

The key insight: Session context builds on itself.

Each extraction:
1. Receives the previous context
2. Sees the new messages
3. Updates the context (not replaces)

This means:
- Even if message history is truncated, context persists
- Important details from early in the conversation aren't lost
- The agent maintains awareness of the full conversation arc

Run:
    python cookbook/15_learning/session_context/03_context_continuity.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Session Context
# ============================================================================
agent = Agent(
    name="Context Continuity Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
    # Keep only recent messages in context
    num_history_runs=3,  # Simulates truncation
    markdown=True,
)


# ============================================================================
# Demo: Information Preservation
# ============================================================================
def demo_info_preservation():
    """Show how early information is preserved in context."""
    print("=" * 60)
    print("Demo: Information Preservation Across Turns")
    print("=" * 60)

    user = "preservation_demo@example.com"
    session = "preservation_session"

    # Turn 1: Important constraint
    print("\n--- Turn 1: State important constraint ---\n")
    agent.print_response(
        "I'm building an API for a healthcare company. "
        "HIPAA compliance is absolutely critical - we can't store any PHI "
        "outside of our encrypted database.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 2: Technical discussion
    print("\n--- Turn 2: Technical details ---\n")
    agent.print_response(
        "Should I use REST or GraphQL for the API?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 3: More details
    print("\n--- Turn 3: More discussion ---\n")
    agent.print_response(
        "Let's go with REST. What about authentication?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 4: Even more
    print("\n--- Turn 4: Logging question ---\n")
    agent.print_response(
        "How should I handle logging in this application?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 5: Check if HIPAA constraint is remembered
    print("\n--- Turn 5: Test constraint recall ---\n")
    agent.print_response(
        "What constraints should I keep in mind for logging?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n💡 Note: Even if early messages are truncated from context,")
    print("   the HIPAA constraint should still be remembered via session context.")


# ============================================================================
# Demo: Context Evolution
# ============================================================================
def demo_context_evolution():
    """Show how context evolves and accumulates."""
    print("\n" + "=" * 60)
    print("Demo: Context Evolution")
    print("=" * 60)

    user = "evolution_demo@example.com"
    session = "evolution_session"

    # Phase 1: Discovery
    print("\n--- Phase 1: Discovery ---\n")
    agent.print_response(
        "I'm having performance issues with my Django app. "
        "Page loads are taking 5+ seconds.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Phase 2: Investigation
    print("\n--- Phase 2: Investigation ---\n")
    agent.print_response(
        "I checked and it's the database queries. "
        "I'm seeing 100+ queries per page load.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Phase 3: Root cause
    print("\n--- Phase 3: Root cause ---\n")
    agent.print_response(
        "Found it! The N+1 query problem in my serializers. "
        "Each item triggers a separate query for related objects.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Phase 4: Solution
    print("\n--- Phase 4: Solution ---\n")
    agent.print_response(
        "I added select_related and prefetch_related. "
        "Now down to 3 queries per page!",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Summary: Context should include full evolution
    print("\n--- Summary: Full context ---\n")
    agent.print_response(
        "Can you summarize the journey we went through to fix this?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_info_preservation()
    demo_context_evolution()

    print("\n" + "=" * 60)
    print("✅ Session context builds on itself")
    print("   Important info persists even with message truncation")
    print("   Context captures the full conversation arc")
    print("=" * 60)
