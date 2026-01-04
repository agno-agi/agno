"""
Session Context: Summary Mode
=============================
Basic session summarization for conversation continuity.

Session Context captures state for the current session:
- Summary: What has happened so far
- (Optional) Goal, Plan, Progress with `enable_planning=True`

Summary-only mode (default) is lightweight and fast. It maintains
a running summary of the conversation without the overhead of
tracking goals and plans.

Key behavior: The summary builds on itself. Each extraction sees
the previous summary and updates it, ensuring continuity even if
message history is truncated.

Run:
    python cookbook/15_learning/session_context/01_summary_mode.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# ============================================================================
# Agent with Summary-Only Session Context
# ============================================================================
agent = Agent(
    name="Session Summary Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,  # Focus on session context
        session_context=SessionContextConfig(
            enable_planning=False,  # Summary only (default)
        ),
    ),
    markdown=True,
)


# ============================================================================
# Helper: Show session context
# ============================================================================
def show_session_context(session_id: str) -> None:
    """Display the current session context."""
    store = agent.learning.session_context_store
    context = store.get(session_id=session_id) if store else None

    print("\n" + "-" * 40)
    print("📋 Session Context:")
    print("-" * 40)

    if not context:
        print("  (no context yet)")
        return

    print(f"  Summary: {context.summary or '(none)'}")
    if hasattr(context, "goal") and context.goal:
        print(f"  Goal: {context.goal}")
    if hasattr(context, "plan") and context.plan:
        print(f"  Plan: {context.plan}")
    if hasattr(context, "progress") and context.progress:
        print(f"  Progress: {context.progress}")


# ============================================================================
# Demo: Multi-Turn Conversation
# ============================================================================
def demo_multi_turn():
    """Show summary building across turns."""
    print("=" * 60)
    print("Demo: Multi-Turn Conversation Summary")
    print("=" * 60)

    user = "summary_demo@example.com"
    session = "summary_session_001"

    # Turn 1
    print("\n--- Turn 1: Initial question ---\n")
    agent.print_response(
        "I'm trying to debug a memory leak in my Python application. "
        "It's a FastAPI web server that processes large JSON payloads.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_session_context(session)

    # Turn 2
    print("\n--- Turn 2: More context ---\n")
    agent.print_response(
        "The memory usage grows steadily over time, even when there's no traffic. "
        "I've already checked for obvious issues like unclosed file handles.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_session_context(session)

    # Turn 3
    print("\n--- Turn 3: Follow-up question ---\n")
    agent.print_response(
        "Could it be related to how I'm handling the JSON parsing? "
        "I'm using Pydantic models for validation.",
        user_id=user,
        session_id=session,
        stream=True,
    )
    show_session_context(session)


# ============================================================================
# Demo: Session Continuity
# ============================================================================
def demo_session_continuity():
    """Show how session context persists across reconnections."""
    print("\n" + "=" * 60)
    print("Demo: Session Continuity")
    print("=" * 60)

    user = "continuity_demo@example.com"
    session = "continuity_session_001"

    # First interaction
    print("\n--- First interaction ---\n")
    agent.print_response(
        "I want to learn about Kubernetes. Let's start with the basics.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Second interaction ---\n")
    agent.print_response(
        "What are pods exactly?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Simulate reconnection - same session_id
    print("\n" + "-" * 40)
    print("Simulating reconnection (same session_id)...")
    print("-" * 40)

    print("\n--- After reconnection ---\n")
    agent.print_response(
        "What were we talking about?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Separate Sessions
# ============================================================================
def demo_separate_sessions():
    """Show that different sessions are isolated."""
    print("\n" + "=" * 60)
    print("Demo: Session Isolation")
    print("=" * 60)

    user = "isolation_demo@example.com"

    # Session A: Cooking
    print("\n--- Session A: Cooking topic ---\n")
    agent.print_response(
        "I want to learn how to make pasta from scratch.",
        user_id=user,
        session_id="cooking_session",
        stream=True,
    )

    # Session B: Coding
    print("\n--- Session B: Coding topic ---\n")
    agent.print_response(
        "How do I use async/await in Python?",
        user_id=user,
        session_id="coding_session",
        stream=True,
    )

    # Check Session A still remembers cooking
    print("\n--- Back to Session A ---\n")
    agent.print_response(
        "What were we making?",
        user_id=user,
        session_id="cooking_session",
        stream=True,
    )

    # Check Session B still remembers coding
    print("\n--- Back to Session B ---\n")
    agent.print_response(
        "What were we discussing?",
        user_id=user,
        session_id="coding_session",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_multi_turn()
    demo_session_continuity()
    demo_separate_sessions()

    print("\n" + "=" * 60)
    print("✅ Session summaries track conversation state")
    print("   - Different sessions are isolated")
    print("   - Context persists across reconnections")
    print("   - Summary builds incrementally")
    print("=" * 60)
