"""
Session Context: Long Conversations
===================================
Handling conversations that exceed context limits.

Long conversations pose challenges:
- Context window limits force message truncation
- Important early context may be lost
- Users expect continuity

Session Context solves this by:
- Extracting and storing a summary
- Summary persists regardless of message count
- Agent always has access to key context

Run:
    python cookbook/15_learning/session_context/04_long_conversations.py
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
# Agent
# ============================================================================
agent = Agent(
    name="Long Conversation Agent",
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
# Demo: Simulated Long Conversation
# ============================================================================
def demo_long_conversation():
    """Simulate a long conversation with many turns."""
    print("=" * 60)
    print("Demo: Long Conversation")
    print("=" * 60)

    user = "long_conv@example.com"
    session = "long_session_001"

    # Simulate a debugging session with many turns
    messages = [
        "I have a bug where users can't log in after password reset.",
        "The reset email sends correctly and the link works.",
        "When they click the link, they can set a new password.",
        "The password saves to the database (I verified with a query).",
        "But when they try to log in with the new password, it fails.",
        "The login endpoint returns 401 Unauthorized.",
        "I checked the password hash and it looks correct.",
        "The bcrypt comparison is returning false though.",
        "Wait, I think I found it - we're using different salt rounds.",
        "The reset uses 12 rounds but login expects 10 rounds.",
        "Let me fix that and test again.",
        "Fixed it! The issue was mismatched bcrypt salt rounds.",
        "Now I need to migrate existing passwords to 12 rounds.",
    ]

    for i, msg in enumerate(messages, 1):
        print(f"\n--- Turn {i}/{len(messages)} ---")
        print(f"User: {msg[:50]}...")
        agent.print_response(
            msg,
            user_id=user,
            session_id=session,
            stream=False,  # Faster for simulation
        )

    # Show final context
    print("\n" + "=" * 60)
    print("Final Session Context")
    print("=" * 60)

    store = agent.learning.session_context_store
    context = store.get(session_id=session) if store else None

    if context:
        print(f"\n📄 Summary:\n{context.summary}")
        if context.goal:
            print(f"\n🎯 Goal: {context.goal}")
        if context.progress:
            print(f"\n✅ Progress:")
            for p in context.progress:
                print(f"   ✓ {p}")


# ============================================================================
# Demo: Context Compression
# ============================================================================
def demo_context_compression():
    """Show how session context compresses information."""
    print("\n" + "=" * 60)
    print("Demo: Context Compression")
    print("=" * 60)
    print("""
Without Session Context:
   - 50 message turns = ~50,000 tokens
   - May hit context limits
   - Old messages get dropped
   - Important early context lost

With Session Context:
   - Summary = ~200-500 tokens
   - Always fits in context
   - Captures key information
   - Persists indefinitely

The summary is like a "compression" of the conversation:

Before (raw messages):
   Turn 1: "I need to build a REST API..."
   Turn 2: "It should handle user authentication..."
   Turn 3: "We're using PostgreSQL for the database..."
   ... 47 more turns ...

After (session context):
   Summary: "Building a REST API with authentication,
   using PostgreSQL. Completed: schema design,
   auth endpoints. Current: rate limiting."

Same information, 100x fewer tokens!
""")


# ============================================================================
# Demo: Reconnection After Long Gap
# ============================================================================
def demo_reconnection():
    """Show reconnecting to a session after time has passed."""
    print("\n" + "=" * 60)
    print("Demo: Reconnection After Gap")
    print("=" * 60)

    user = "reconnect@example.com"
    session = "project_alpha"

    # Initial conversation
    print("\n--- Day 1: Start project ---\n")
    agent.print_response(
        "Starting a new project: build a CLI tool for database migrations. "
        "It should support PostgreSQL and MySQL.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n--- Day 1: Design decisions ---\n")
    agent.print_response(
        "Let's use Python with Click for the CLI. "
        "We'll store migration history in a metadata table.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Simulate time gap
    print("\n" + "-" * 40)
    print("⏰ One week later...")
    print("-" * 40)

    # Reconnect
    print("\n--- Day 8: Reconnect ---\n")
    agent.print_response(
        "Hey, I'm back. What was the status of our project?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Best Practices
# ============================================================================
def best_practices():
    """Print best practices for long conversations."""
    print("\n" + "=" * 60)
    print("Best Practices for Long Conversations")
    print("=" * 60)
    print("""
1. ALWAYS USE SESSION CONTEXT
   - Provides continuity
   - Survives message truncation
   - Low overhead

2. USE CONSISTENT SESSION IDs
   - Same session_id = same context
   - Use meaningful IDs: "project_X", "ticket_123"
   - Don't generate random IDs per message

3. ENABLE PLANNING FOR TASK SESSIONS
   - enable_planning=True for goal tracking
   - enable_planning=False for general chat

4. COMBINE WITH USER PROFILE
   - Session: What we're doing now
   - Profile: Who the user is (persistent)

5. CONSIDER PERIODIC SUMMARIES
   - For very long sessions, user can ask for summary
   - Helps both user and agent stay aligned

6. HANDLE SESSION ENDINGS
   - Let users "close" sessions
   - Archive context if needed
   - Start fresh sessions for new topics
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_long_conversation()
    demo_context_compression()
    demo_reconnection()
    best_practices()

    print("\n" + "=" * 60)
    print("✅ Session Context handles long conversations by:")
    print("   - Compressing info into summary")
    print("   - Persisting regardless of message count")
    print("   - Enabling reconnection after gaps")
    print("=" * 60)
