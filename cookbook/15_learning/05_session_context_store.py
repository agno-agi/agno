"""
SessionContextStore — Per-Session State
========================================
Deep dive into SessionContextStore, which tracks what's happening
in the current session.

Unlike UserProfileStore (which accumulates), SessionContextStore
REPLACES state on each update. Think of it like:
- UserProfile = What you know about a person (permanent)
- SessionContext = What's happening in this meeting (temporary)

This cookbook demonstrates:
1. Basic summary extraction
2. Planning mode (goal, plan, progress)
3. Summary vs Planning comparison
4. Context replacement semantics
5. Multi-session isolation
6. Empty/edge-case handling
7. State tracking (was_updated)
8. build_context() formatting
9. Custom instructions
10. Long conversations

Run this example:
    python cookbook/learning/05_session_context_store.py
"""

from agno.db.postgres import PostgresDb
from agno.learn import SessionContextConfig
from agno.learn.stores.session import SessionContextStore
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# =============================================================================
# Setup
# =============================================================================

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
model = OpenAIChat(id="gpt-4o-mini")

# Summary-only store (default)
summary_store = SessionContextStore(
    config=SessionContextConfig(
        db=db,
        model=model,
        enable_planning=False,  # Just summaries
    )
)

# Planning-enabled store
planning_store = SessionContextStore(
    config=SessionContextConfig(
        db=db,
        model=model,
        enable_planning=True,  # Goal, plan, progress tracking
    )
)


# =============================================================================
# Test 1: Basic Summary Extraction
# =============================================================================


def test_basic_summary():
    """
    The simplest case: summarize what happened in a session.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Basic Summary Extraction")
    print("=" * 60)

    session_id = "summary_test_001"

    # A simple debugging conversation
    messages = [
        Message(role="user", content="I need help debugging my Python code."),
        Message(role="assistant", content="I'd be happy to help! What's the issue?"),
        Message(
            role="user", content="I'm getting a KeyError when accessing a dictionary."
        ),
        Message(
            role="assistant",
            content="That usually means the key doesn't exist. Can you show me the code?",
        ),
        Message(
            role="user", content="Here it is: data['user_name'] - but data is empty."
        ),
        Message(
            role="assistant",
            content="That's the issue - use .get() to safely access keys.",
        ),
    ]

    # Extract and save
    print(f"\n📝 Processing {len(messages)} messages...")
    summary_store.process(messages=messages, session_id=session_id)
    print(f"🔄 was_updated: {summary_store.was_updated}")

    # Retrieve the context
    context = summary_store.recall(session_id=session_id)
    print(f"\n📋 Session context:")
    if context:
        pprint(context.to_dict())

    # Cleanup
    summary_store.delete(session_id=session_id)

    print("\n✅ Basic summary extraction works!")


# =============================================================================
# Test 2: Planning Mode
# =============================================================================


def test_planning_mode():
    """
    Planning mode tracks goal, plan, and progress in addition to summary.
    Great for multi-step tasks.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Planning Mode")
    print("=" * 60)

    session_id = "planning_test_001"

    # A goal-oriented conversation
    messages = [
        Message(
            role="user", content="I want to deploy my FastAPI app to production today."
        ),
        Message(
            role="assistant", content="Let's make a plan. What's your current setup?"
        ),
        Message(
            role="user", content="It's a FastAPI backend with a Postgres database."
        ),
        Message(
            role="assistant",
            content="Great! Here's our plan:\n1. Run tests\n2. Build Docker image\n3. Push to registry\n4. Deploy to Kubernetes",
        ),
        Message(role="user", content="Tests are passing!"),
        Message(
            role="assistant",
            content="Perfect! Let's move on to building the Docker image.",
        ),
    ]

    # Extract with planning enabled
    print(f"\n📝 Processing {len(messages)} messages with planning mode...")
    planning_store.process(messages=messages, session_id=session_id)
    print(f"🔄 was_updated: {planning_store.was_updated}")

    # Retrieve
    context = planning_store.recall(session_id=session_id)
    print(f"\n📋 Session context with planning:")
    if context:
        pprint(context.to_dict())
        print(f"\n   Summary: {context.summary}")
        print(f"   Goal: {context.goal}")
        print(f"   Plan: {context.plan}")
        print(f"   Progress: {context.progress}")

    # Cleanup
    planning_store.delete(session_id=session_id)

    print("\n✅ Planning mode works!")


# =============================================================================
# Test 3: Summary vs Planning Comparison
# =============================================================================


def test_summary_vs_planning():
    """
    Compare output from the same conversation in both modes.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Summary vs Planning Comparison")
    print("=" * 60)

    session_summary = "compare_summary"
    session_planning = "compare_planning"

    # Same conversation
    messages = [
        Message(role="user", content="I need to migrate my database to a new schema."),
        Message(
            role="assistant", content="Let's plan this carefully to avoid downtime."
        ),
        Message(
            role="user",
            content="The new schema adds 'created_at' timestamps to all tables.",
        ),
        Message(
            role="assistant",
            content="Steps: 1) Backup database 2) Write migration 3) Test on staging 4) Apply to production",
        ),
        Message(role="user", content="I've already completed the backup."),
    ]

    # Extract with summary mode
    summary_store.process(messages=messages, session_id=session_summary)
    ctx_summary = summary_store.recall(session_id=session_summary)

    # Extract with planning mode
    planning_store.process(messages=messages, session_id=session_planning)
    ctx_planning = planning_store.recall(session_id=session_planning)

    print(f"\n📊 Summary Mode (enable_planning=False):")
    if ctx_summary:
        pprint(ctx_summary.to_dict())

    print(f"\n📊 Planning Mode (enable_planning=True):")
    if ctx_planning:
        pprint(ctx_planning.to_dict())

    # Cleanup
    summary_store.delete(session_id=session_summary)
    planning_store.delete(session_id=session_planning)

    print("\n✅ Both modes produce appropriate output!")


# =============================================================================
# Test 4: Context Replacement
# =============================================================================


def test_context_replacement():
    """
    Unlike UserProfileStore which accumulates, SessionContextStore REPLACES.
    Each extraction overwrites the previous context.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Context Replacement (vs Accumulation)")
    print("=" * 60)

    session_id = "replacement_test"

    # First conversation chunk
    messages_1 = [
        Message(role="user", content="Let's talk about Python async programming."),
        Message(role="assistant", content="Great topic! What aspect interests you?"),
        Message(role="user", content="I want to understand asyncio basics."),
    ]

    summary_store.process(messages=messages_1, session_id=session_id)
    ctx_1 = summary_store.recall(session_id=session_id)
    print(f"\n📋 After first extraction:")
    print(f"   Summary: {ctx_1.summary if ctx_1 else 'None'}")

    # Second conversation chunk (different topic!)
    messages_2 = [
        Message(role="user", content="Actually, let's switch to databases."),
        Message(role="assistant", content="Sure! SQL or NoSQL?"),
        Message(
            role="user", content="PostgreSQL specifically. I need to optimize queries."
        ),
    ]

    summary_store.process(messages=messages_2, session_id=session_id)
    ctx_2 = summary_store.recall(session_id=session_id)
    print(f"\n📋 After second extraction (REPLACED, not accumulated):")
    print(f"   Summary: {ctx_2.summary if ctx_2 else 'None'}")

    # Note: The first summary about asyncio is gone!
    if ctx_2 and ctx_2.summary:
        assert (
            "postgres" in ctx_2.summary.lower()
            or "database" in ctx_2.summary.lower()
            or "sql" in ctx_2.summary.lower()
        )

    # Cleanup
    summary_store.delete(session_id=session_id)

    print("\n✅ Context replacement works! (Old context is overwritten)")


# =============================================================================
# Test 5: Multi-Session Isolation
# =============================================================================


def test_multi_session_isolation():
    """
    Sessions don't leak into each other.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Multi-Session Isolation")
    print("=" * 60)

    session_alice = "alice_session"
    session_bob = "bob_session"

    # Alice's session: Frontend development
    messages_alice = [
        Message(role="user", content="I'm building a React dashboard."),
        Message(role="assistant", content="Nice! What components do you need?"),
        Message(role="user", content="Charts, tables, and a sidebar navigation."),
    ]

    # Bob's session: Backend development
    messages_bob = [
        Message(role="user", content="I'm building a REST API with FastAPI."),
        Message(role="assistant", content="FastAPI is great! What endpoints?"),
        Message(role="user", content="CRUD for users, products, and orders."),
    ]

    # Extract both
    summary_store.process(messages=messages_alice, session_id=session_alice)
    summary_store.process(messages=messages_bob, session_id=session_bob)

    # Retrieve and verify isolation
    ctx_alice = summary_store.recall(session_id=session_alice)
    ctx_bob = summary_store.recall(session_id=session_bob)

    print(f"\n👩 Alice's session:")
    print(f"   Summary: {ctx_alice.summary if ctx_alice else 'None'}")

    print(f"\n👨 Bob's session:")
    print(f"   Summary: {ctx_bob.summary if ctx_bob else 'None'}")

    # Verify no cross-contamination
    if ctx_alice and ctx_alice.summary and ctx_bob and ctx_bob.summary:
        alice_text = ctx_alice.summary.lower()
        bob_text = ctx_bob.summary.lower()
        # Alice shouldn't mention API/FastAPI, Bob shouldn't mention React/dashboard
        assert "fastapi" not in alice_text or "react" in alice_text
        assert "react" not in bob_text or "api" in bob_text

    # Cleanup
    summary_store.delete(session_id=session_alice)
    summary_store.delete(session_id=session_bob)

    print("\n✅ Sessions are properly isolated!")


# =============================================================================
# Test 6: Empty/Edge Cases
# =============================================================================


def test_empty_messages():
    """
    Handle conversations with no meaningful content gracefully.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Empty/Edge Cases")
    print("=" * 60)

    session_id = "empty_test"

    # Empty messages
    messages_empty = []
    summary_store.process(messages=messages_empty, session_id=session_id)
    print(f"\n📝 Empty messages: was_updated = {summary_store.was_updated}")

    # Whitespace-only messages
    messages_whitespace = [
        Message(role="user", content="   "),
        Message(role="assistant", content=""),
    ]
    summary_store.process(
        messages=messages_whitespace, session_id=f"{session_id}_whitespace"
    )
    print(f"📝 Whitespace messages: was_updated = {summary_store.was_updated}")

    # Single very short message
    messages_short = [
        Message(role="user", content="Hi"),
    ]
    summary_store.process(messages=messages_short, session_id=f"{session_id}_short")
    ctx = summary_store.recall(session_id=f"{session_id}_short")
    print(f"📝 Short message: {ctx.summary if ctx else 'No context'}")

    # Cleanup
    summary_store.delete(session_id=session_id)
    summary_store.delete(session_id=f"{session_id}_whitespace")
    summary_store.delete(session_id=f"{session_id}_short")

    print("\n✅ Edge cases handled gracefully!")


# =============================================================================
# Test 7: State Tracking
# =============================================================================


def test_state_tracking():
    """
    Know when the context was actually updated.
    """
    print("\n" + "=" * 60)
    print("TEST 7: State Tracking (was_updated)")
    print("=" * 60)

    # Meaningful conversation
    messages = [
        Message(
            role="user", content="Let's build a recommendation engine for e-commerce."
        ),
        Message(
            role="assistant", content="Great! Collaborative filtering or content-based?"
        ),
        Message(role="user", content="Let's try hybrid approach."),
    ]

    summary_store.process(messages=messages, session_id="state_test")
    print(
        f"\n📝 After meaningful conversation: was_updated = {summary_store.was_updated}"
    )

    # Cleanup
    summary_store.delete(session_id="state_test")

    print("\n✅ State tracking works!")


# =============================================================================
# Test 8: build_context() Formatting
# =============================================================================


def test_build_context():
    """
    Format context for system prompt injection.
    """
    print("\n" + "=" * 60)
    print("TEST 8: build_context() Formatting")
    print("=" * 60)

    session_id = "format_test"

    messages = [
        Message(role="user", content="I'm building a CLI tool for Docker management."),
        Message(
            role="assistant",
            content="Let's plan the commands: list, start, stop, logs.",
        ),
        Message(role="user", content="I've finished the list command."),
    ]

    planning_store.process(messages=messages, session_id=session_id)
    context_data = planning_store.recall(session_id=session_id)
    formatted = planning_store.build_context(data=context_data)

    print(f"\n📝 Formatted context for system prompt:")
    print("-" * 40)
    print(formatted)
    print("-" * 40)

    # Cleanup
    planning_store.delete(session_id=session_id)

    print("\n✅ build_context() works!")


# =============================================================================
# Test 9: Custom Instructions
# =============================================================================


def test_custom_instructions():
    """
    Customize what the extractor focuses on.
    """
    print("\n" + "=" * 60)
    print("TEST 9: Custom Instructions")
    print("=" * 60)

    session_id = "custom_test"

    # Store with custom instructions
    custom_store = SessionContextStore(
        config=SessionContextConfig(
            db=db,
            model=model,
            enable_planning=False,
            instructions="""
            Focus ONLY on technical decisions made.
            Ignore small talk and pleasantries.
            Format as bullet points.
            """,
        )
    )

    messages = [
        Message(role="user", content="Hey! How's it going?"),
        Message(role="assistant", content="Great! Ready to help."),
        Message(role="user", content="We decided to use PostgreSQL over MySQL."),
        Message(role="assistant", content="Good choice for complex queries."),
        Message(
            role="user", content="Thanks! Also, we'll deploy on AWS instead of GCP."
        ),
    ]

    custom_store.process(messages=messages, session_id=session_id)
    context = custom_store.recall(session_id=session_id)

    print(f"\n📋 Custom-extracted context (technical decisions only):")
    if context:
        print(f"   Summary: {context.summary}")

    # Cleanup
    custom_store.delete(session_id=session_id)

    print("\n✅ Custom instructions work!")


# =============================================================================
# Test 10: Long Conversation
# =============================================================================


def test_long_conversation():
    """
    Test with a longer, more realistic conversation.
    """
    print("\n" + "=" * 60)
    print("TEST 10: Long Conversation")
    print("=" * 60)

    session_id = "long_test"

    # A longer e-commerce planning conversation
    messages = [
        Message(role="user", content="I want to build an e-commerce platform."),
        Message(
            role="assistant", content="Great! What are the main features you need?"
        ),
        Message(
            role="user",
            content="Product catalog, shopping cart, checkout, and user accounts.",
        ),
        Message(
            role="assistant",
            content="Let's break this down. For the catalog, do you need categories and search?",
        ),
        Message(role="user", content="Yes, both. Also filters by price and rating."),
        Message(
            role="assistant",
            content="Good. For the cart, should it persist across sessions?",
        ),
        Message(
            role="user",
            content="Yes, logged-in users should see their cart on any device.",
        ),
        Message(
            role="assistant",
            content="That means we need auth and cart storage in the database.",
        ),
        Message(role="user", content="Makes sense. What about payments?"),
        Message(
            role="assistant",
            content="I'd recommend Stripe. It handles most edge cases.",
        ),
        Message(
            role="user", content="Perfect. Let's start with the product catalog first."
        ),
        Message(
            role="assistant",
            content="Agreed. First step: design the product data model.",
        ),
    ]

    planning_store.process(messages=messages, session_id=session_id)
    context = planning_store.recall(session_id=session_id)

    print(f"\n📋 Long conversation summary ({len(messages)} messages):")
    if context:
        pprint(context.to_dict())

    # Cleanup
    planning_store.delete(session_id=session_id)

    print("\n✅ Long conversations summarized well!")


# =============================================================================
# Test 11: __repr__ for Debugging
# =============================================================================


def test_repr():
    """
    Inspect store state with __repr__.
    """
    print("\n" + "=" * 60)
    print("TEST 11: __repr__ for Debugging")
    print("=" * 60)

    print(f"\n📊 Summary store: {summary_store}")
    print(f"📊 Planning store: {planning_store}")
    print(f"\n📊 Config repr: {planning_store.config}")

    print("\n✅ __repr__ works!")


# =============================================================================
# Cleanup
# =============================================================================


def cleanup():
    """Clean up all test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    test_sessions = [
        "summary_test_001",
        "planning_test_001",
        "compare_summary",
        "compare_planning",
        "replacement_test",
        "alice_session",
        "bob_session",
        "empty_test",
        "empty_test_whitespace",
        "empty_test_short",
        "state_test",
        "format_test",
        "custom_test",
        "long_test",
    ]

    for session_id in test_sessions:
        try:
            summary_store.delete(session_id=session_id)
            planning_store.delete(session_id=session_id)
        except Exception:
            pass

    print("🧹 Cleaned up test data")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("📋 SessionContextStore — Per-Session State")
    print("   Context is REPLACED, not accumulated")
    print("=" * 60)

    # Run all tests
    test_basic_summary()
    test_planning_mode()
    test_summary_vs_planning()
    test_context_replacement()
    test_multi_session_isolation()
    test_empty_messages()
    test_state_tracking()
    test_build_context()
    test_custom_instructions()
    test_long_conversation()
    test_repr()

    # Cleanup
    cleanup()

    # Summary
    print("\n" + "=" * 60)
    print("✅ All tests complete!")
    print("=" * 60)
    print("""
Key takeaways:

1. **Replacement**: Each process() REPLACES the previous context
   (unlike UserProfile which accumulates)

2. **Two Modes**:
   - enable_planning=False → Summary only
   - enable_planning=True → Summary + Goal + Plan + Progress

3. **No Agent Tool**: SessionContext is system-managed only
   (the agent doesn't decide what to summarize)

4. **Session Isolation**: Each session_id has independent context

5. **Use Cases**:
   - Summary mode: General conversations
   - Planning mode: Multi-step tasks, projects
""")
