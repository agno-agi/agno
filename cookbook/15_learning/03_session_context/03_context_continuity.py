"""
Session Context: Context Continuity
===================================
How context persists even when message history is truncated.

The key insight: Session context is extracted and stored separately
from message history. This means:

1. Even if messages are truncated for context limits
2. The summary/goal/plan/progress persists
3. The agent can reference prior context

This is crucial for long conversations.

Run:
    python cookbook/15_learning/session_context/03_context_continuity.py
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
# Agent with Session Context
# ============================================================================
agent = Agent(
    name="Continuity Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Helper
# ============================================================================
def show_context(session_id: str) -> None:
    """Display session context."""
    store = agent.learning.session_context_store
    context = store.get(session_id=session_id) if store else None

    print("\n📋 Stored Context:")
    if context:
        print(
            f"  Summary: {context.summary[:100]}..."
            if context.summary and len(context.summary) > 100
            else f"  Summary: {context.summary}"
        )
        print(f"  Goal: {context.goal}")
    else:
        print("  (none)")


# ============================================================================
# Demo: Context Survives Truncation
# ============================================================================
def demo_context_survives():
    """Show that context persists even without message history."""
    print("=" * 60)
    print("Demo: Context Survives Message Truncation")
    print("=" * 60)

    user = "continuity@example.com"
    session = "continuity_001"

    # Build up context through multiple messages
    print("\n--- Building context (Turn 1) ---\n")
    agent.print_response(
        "I'm building a recommendation engine for an e-commerce site. "
        "We have millions of products and need real-time suggestions.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Building context (Turn 2) ---\n")
    agent.print_response(
        "We've decided to use collaborative filtering as the main approach.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Building context (Turn 3) ---\n")
    agent.print_response(
        "The data pipeline is set up and we're collecting click events.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    show_context(session)

    # Simulate a fresh connection (no message history)
    print("\n" + "-" * 40)
    print("🔄 Simulating fresh connection...")
    print("   (Imagine message history is empty)")
    print("-" * 40)

    # Even without history, context should inform the response
    print("\n--- Fresh connection asks about progress ---\n")
    agent.print_response(
        "What's the status of our project?",
        user_id=user,
        session_id=session,  # Same session_id = same context
        stream=True,
    )


# ============================================================================
# Demo: Incremental Context Building
# ============================================================================
def demo_incremental_building():
    """Show how context builds incrementally."""
    print("\n" + "=" * 60)
    print("Demo: Incremental Context Building")
    print("=" * 60)

    user = "incremental@example.com"
    session = "incremental_001"

    conversations = [
        "I need help writing a blog post about AI safety.",
        "The target audience is non-technical executives.",
        "It should be about 1500 words.",
        "I want to cover 3 main risks and 3 potential solutions.",
        "Let's start with the introduction.",
    ]

    for i, msg in enumerate(conversations, 1):
        print(f"\n--- Turn {i} ---\n")
        agent.print_response(
            msg,
            user_id=user,
            session_id=session,
            stream=True,
        )
        show_context(session)


# ============================================================================
# Demo: Context vs Messages
# ============================================================================
def demo_context_vs_messages():
    """Explain the difference between context and messages."""
    print("\n" + "=" * 60)
    print("Understanding: Context vs Messages")
    print("=" * 60)
    print("""
📨 MESSAGE HISTORY:
   - Actual conversation turns
   - Stored in database (agent_sessions table)
   - May be truncated for context window limits
   - Contains full user messages and assistant responses

📋 SESSION CONTEXT:
   - Extracted summary/goal/plan/progress
   - Stored separately (learning system)
   - Never truncated, always available
   - Injected into system prompt

The flow:
1. User sends message
2. Agent receives: system prompt + context + recent messages
3. Agent responds
4. Background extraction updates context
5. Context persists even if old messages are dropped

This means:
- Long conversations maintain context
- Users can "reconnect" and continue
- Agent remembers the goal even without full history

Example:
   Turn 1-50: Building a web app
   Turn 51: "What framework are we using?"
   
   Even if turns 1-40 are truncated:
   - Context says "Building web app with React"
   - Agent can answer correctly
""")


# ============================================================================
# Demo: Same User, Different Sessions
# ============================================================================
def demo_session_isolation():
    """Show that different sessions have independent context."""
    print("\n" + "=" * 60)
    print("Demo: Session Isolation")
    print("=" * 60)

    user = "isolation@example.com"

    # Session A
    print("\n--- Session A: Work project ---\n")
    agent.print_response(
        "Help me design an API for our inventory system.",
        user_id=user,
        session_id="work_session",
        stream=True,
    )

    # Session B
    print("\n--- Session B: Personal project ---\n")
    agent.print_response(
        "Help me plan a birthday party for 20 people.",
        user_id=user,
        session_id="personal_session",
        stream=True,
    )

    # Check both contexts
    print("\n--- Work session context ---")
    show_context("work_session")

    print("\n--- Personal session context ---")
    show_context("personal_session")

    # Query each session
    print("\n--- Query work session ---\n")
    agent.print_response(
        "What are we building?",
        user_id=user,
        session_id="work_session",
        stream=True,
    )

    print("\n--- Query personal session ---\n")
    agent.print_response(
        "What are we planning?",
        user_id=user,
        session_id="personal_session",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_context_survives()
    demo_incremental_building()
    demo_context_vs_messages()
    demo_session_isolation()

    print("\n" + "=" * 60)
    print("✅ Key Takeaways:")
    print("   - Context persists separately from messages")
    print("   - Survives message truncation")
    print("   - Builds incrementally over conversation")
    print("   - Sessions are isolated from each other")
    print("=" * 60)
