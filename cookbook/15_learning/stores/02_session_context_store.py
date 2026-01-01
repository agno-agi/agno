"""
Session Context Store Cookbook
==============================

"Context is everything." - Someone wise

This cookbook demonstrates the SessionContextStore - a system for capturing
what's happening RIGHT NOW in a session. Unlike UserProfileStore which
accumulates memories, SessionContextStore REPLACES state on each update.

Think of it like:
- UserProfile = What you know about a person (permanent)
- SessionContext = What's happening in this meeting (temporary)

Tests:
1. Basic summary extraction - The core use case
2. Planning mode - Track goals, plans, and progress
3. Summary vs Planning - When to use which
4. Context replacement - Each update replaces the previous
5. Delete and clear - Start fresh
6. Format for prompt - System prompt injection
7. Multi-session isolation - Sessions don't leak into each other
8. Media-only messages - Handle images/files gracefully
9. State tracking - Know when context changed
10. Long conversations - Summarize effectively
"""

from agno.db.postgres import PostgresDb
from agno.learn import SessionContextConfig, SessionContextStore
from agno.models.message import Message
from agno.models.openai import OpenAIResponses
from rich.pretty import pprint

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    learnings_table="agno_learnings",
)
model = OpenAIResponses(id="gpt-5.2")

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

# Setup logging (only needed when using store directly, not through LearningMachine)
summary_store.set_log_level()
planning_store.set_log_level()

# -----------------------------------------------------------------------------
# Test 1: Basic Summary Extraction
# -----------------------------------------------------------------------------


def test_basic_summary():
    """
    The simplest case: summarize what happened in a session.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Basic Summary Extraction")
    print("=" * 60)

    session_id = "summary_test_001"

    # A simple conversation
    messages = [
        Message(role="user", content="Hi, I need help debugging my Python code."),
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
            content="That's the issue - check if the key exists first with .get()",
        ),
    ]

    # Extract and save
    result = summary_store.extract_and_save(messages=messages, session_id=session_id)
    print(f"\n📝 Extraction result: {result}")
    print(f"🔄 Context updated: {summary_store.was_updated}")

    # Retrieve the context
    context = summary_store.get(session_id=session_id)
    print(f"\n📋 Session context:")
    if context:
        pprint(context.to_dict())
        assert context.summary, "Should have a summary"
        print(f"\n   Summary: {context.summary}")

    # Cleanup
    summary_store.delete(session_id=session_id)

    print("\n✅ Basic summary works")


# -----------------------------------------------------------------------------
# Test 2: Planning Mode
# -----------------------------------------------------------------------------


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
        Message(role="user", content="I want to deploy my app to production today."),
        Message(role="assistant", content="Let's make a plan. What kind of app is it?"),
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
    result = planning_store.extract_and_save(messages=messages, session_id=session_id)
    print(f"\n📝 Extraction result: {result}")

    # Retrieve
    context = planning_store.get(session_id=session_id)
    print(f"\n📋 Session context with planning:")
    if context:
        pprint(context.to_dict())

        print(f"\n   Summary: {context.summary}")
        print(f"   Goal: {context.goal}")
        print(f"   Plan: {context.plan}")
        print(f"   Progress: {context.progress}")

    # Cleanup
    planning_store.delete(session_id=session_id)

    print("\n✅ Planning mode works")


# -----------------------------------------------------------------------------
# Test 3: Summary vs Planning
# -----------------------------------------------------------------------------


def test_summary_vs_planning():
    """
    Compare output from the same conversation in both modes.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Summary vs Planning")
    print("=" * 60)

    session_summary = "compare_summary"
    session_planning = "compare_planning"

    # Same conversation
    messages = [
        Message(role="user", content="I need to migrate my database to a new schema."),
        Message(role="assistant", content="Alright, let's plan this carefully."),
        Message(
            role="user",
            content="The new schema adds a 'created_at' timestamp to all tables.",
        ),
        Message(
            role="assistant",
            content="Steps: 1) Backup database 2) Write migration script 3) Test on staging 4) Apply to production",
        ),
        Message(role="user", content="I've already done the backup."),
    ]

    # Extract with summary mode
    summary_store.extract_and_save(messages=messages, session_id=session_summary)
    ctx_summary = summary_store.get(session_id=session_summary)

    # Extract with planning mode
    planning_store.extract_and_save(messages=messages, session_id=session_planning)
    ctx_planning = planning_store.get(session_id=session_planning)

    print(f"\n📊 Summary Mode:")
    if ctx_summary:
        pprint(ctx_summary.to_dict())

    print(f"\n📊 Planning Mode:")
    if ctx_planning:
        pprint(ctx_planning.to_dict())

    # Cleanup
    summary_store.delete(session_id=session_summary)
    planning_store.delete(session_id=session_planning)

    print("\n✅ Both modes produce appropriate output")


# -----------------------------------------------------------------------------
# Test 4: Context Replacement
# -----------------------------------------------------------------------------


def test_context_replacement():
    """
    Unlike UserProfileStore which accumulates, SessionContextStore REPLACES.
    Each extraction overwrites the previous context.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Context Replacement")
    print("=" * 60)

    session_id = "replacement_test"

    # First conversation chunk
    messages_1 = [
        Message(role="user", content="Let's talk about Python."),
        Message(role="assistant", content="Sure! What about Python?"),
        Message(role="user", content="I want to learn async programming."),
    ]

    summary_store.extract_and_save(messages=messages_1, session_id=session_id)
    ctx_1 = summary_store.get(session_id=session_id)
    print(f"\n📋 After first extraction:")
    if ctx_1:
        print(f"   Summary: {ctx_1.summary}")

    # Second conversation chunk (later in same session)
    messages_2 = [
        Message(role="user", content="Actually, let's switch to discussing databases."),
        Message(role="assistant", content="Sure! What database topics interest you?"),
        Message(
            role="user", content="I'm curious about PostgreSQL performance tuning."
        ),
    ]

    summary_store.extract_and_save(messages=messages_2, session_id=session_id)
    ctx_2 = summary_store.get(session_id=session_id)
    print(f"\n📋 After second extraction:")
    if ctx_2:
        print(f"   Summary: {ctx_2.summary}")

    # The summary should now be about databases, not async
    print("\n   Note: The context was REPLACED, not appended")

    # Cleanup
    summary_store.delete(session_id=session_id)

    print("\n✅ Context replacement works")


# -----------------------------------------------------------------------------
# Test 5: Delete and Clear
# -----------------------------------------------------------------------------


def test_delete_and_clear():
    """
    Clear = reset to empty context (session still "exists")
    Delete = remove entirely
    """
    print("\n" + "=" * 60)
    print("TEST 5: Delete and Clear")
    print("=" * 60)

    session_id = "lifecycle_test"

    # Create some context
    messages = [
        Message(role="user", content="We discussed important architecture decisions."),
        Message(role="assistant", content="Yes, we agreed on microservices."),
    ]

    summary_store.extract_and_save(messages=messages, session_id=session_id)
    ctx = summary_store.get(session_id=session_id)
    print(f"\n📋 Initial context:")
    if ctx:
        print(f"   Summary: {ctx.summary}")

    # Clear = empty but exists
    summary_store.clear(session_id=session_id)
    ctx_cleared = summary_store.get(session_id=session_id)
    print(f"\n🧹 After clear:")
    if ctx_cleared:
        print(f"   Summary: '{ctx_cleared.summary or 'empty'}'")
        print(f"   Context exists: True")

    # Delete = gone entirely
    summary_store.delete(session_id=session_id)
    ctx_deleted = summary_store.get(session_id=session_id)
    print(f"\n🗑️ After delete:")
    print(f"   Context exists: {ctx_deleted is not None}")

    print("\n✅ Delete and clear work")


# -----------------------------------------------------------------------------
# Test 6: Format for Prompt
# -----------------------------------------------------------------------------


def test_format_for_prompt():
    """
    Test the format_for_prompt method for system prompt injection.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Format for Prompt")
    print("=" * 60)

    session_id = "format_test"

    # Create context with planning
    messages = [
        Message(role="user", content="I want to build a CLI tool for file management."),
        Message(
            role="assistant",
            content="Great idea! Let's plan: 1) Design commands 2) Implement parser 3) Add tests",
        ),
        Message(role="user", content="I've finished designing the commands."),
    ]

    planning_store.extract_and_save(messages=messages, session_id=session_id)
    context = planning_store.get(session_id=session_id)

    # Format for injection
    formatted = planning_store.format_for_prompt(data=context)

    print(f"\n📝 Formatted for system prompt:")
    print("-" * 40)
    print(formatted)
    print("-" * 40)

    # Should be XML formatted
    assert "<session_context>" in formatted
    assert "</session_context>" in formatted

    # Cleanup
    planning_store.delete(session_id=session_id)

    print("\n✅ Format for prompt works")


# -----------------------------------------------------------------------------
# Test 7: Multi-Session Isolation
# -----------------------------------------------------------------------------


def test_multi_session_isolation():
    """
    Different sessions should have completely isolated contexts.
    """
    print("\n" + "=" * 60)
    print("TEST 7: Multi-Session Isolation")
    print("=" * 60)

    session_alice = "alice_session"
    session_bob = "bob_session"

    # Alice's session
    messages_alice = [
        Message(role="user", content="I'm working on a mobile app for iOS."),
        Message(role="assistant", content="Swift or SwiftUI?"),
    ]

    # Bob's session
    messages_bob = [
        Message(role="user", content="I need to set up a data pipeline."),
        Message(role="assistant", content="What's your source data format?"),
    ]

    # Extract both
    summary_store.extract_and_save(messages=messages_alice, session_id=session_alice)
    summary_store.extract_and_save(messages=messages_bob, session_id=session_bob)

    # Retrieve and verify isolation
    ctx_alice = summary_store.get(session_id=session_alice)
    ctx_bob = summary_store.get(session_id=session_bob)

    print(f"\n👩 Alice's session:")
    if ctx_alice:
        print(f"   Summary: {ctx_alice.summary}")

    print(f"\n👨 Bob's session:")
    if ctx_bob:
        print(f"   Summary: {ctx_bob.summary}")

    # Verify they're different
    if ctx_alice and ctx_bob:
        assert ctx_alice.summary != ctx_bob.summary, "Sessions should be different"

    # Cleanup
    summary_store.delete(session_id=session_alice)
    summary_store.delete(session_id=session_bob)

    print("\n✅ Sessions are isolated")


# -----------------------------------------------------------------------------
# Test 8: Empty/Media-Only Messages
# -----------------------------------------------------------------------------


def test_empty_messages():
    """
    Handle conversations with no meaningful text content.
    """
    print("\n" + "=" * 60)
    print("TEST 8: Empty/Media-Only Messages")
    print("=" * 60)

    session_id = "empty_test"

    # Messages with no real content
    messages = [
        Message(role="user", content=""),
        Message(role="user", content="   "),
    ]

    result = summary_store.extract_and_save(messages=messages, session_id=session_id)
    print(f"\n📝 Result with empty messages: {result}")
    print(f"🔄 Context updated: {summary_store.was_updated}")

    # Should handle gracefully
    ctx = summary_store.get(session_id=session_id)
    print(f"📋 Context: {ctx}")

    print("\n✅ Empty messages handled gracefully")


# -----------------------------------------------------------------------------
# Test 9: State Tracking
# -----------------------------------------------------------------------------


def test_state_tracking():
    """
    Know when the context was actually updated.
    """
    print("\n" + "=" * 60)
    print("TEST 9: State Tracking")
    print("=" * 60)

    session_id = "state_test"

    # Meaningful conversation
    messages = [
        Message(role="user", content="Let's build a recommendation engine."),
        Message(role="assistant", content="What type of recommendations?"),
    ]

    summary_store.extract_and_save(messages=messages, session_id=session_id)
    print(f"\n📝 After meaningful messages: was_updated = {summary_store.was_updated}")

    # Cleanup
    summary_store.delete(session_id=session_id)

    print("\n✅ State tracking works")


# -----------------------------------------------------------------------------
# Test 10: Long Conversation
# -----------------------------------------------------------------------------


def test_long_conversation():
    """
    Test with a longer, more realistic conversation.
    """
    print("\n" + "=" * 60)
    print("TEST 10: Long Conversation")
    print("=" * 60)

    session_id = "long_test"

    # A longer conversation
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
            content="Let's break this down. For the product catalog, do you need categories and search?",
        ),
        Message(role="user", content="Yes, both. Also filters by price and rating."),
        Message(
            role="assistant",
            content="Good. For the shopping cart, should it persist across sessions?",
        ),
        Message(
            role="user",
            content="Yes, logged-in users should see their cart on any device.",
        ),
        Message(
            role="assistant",
            content="That means we need user authentication and cart storage in the database.",
        ),
        Message(role="user", content="Makes sense. What about payments?"),
        Message(
            role="assistant",
            content="I'd recommend Stripe for payments. It handles most edge cases.",
        ),
        Message(
            role="user", content="Perfect. Let's start with the product catalog first."
        ),
        Message(
            role="assistant",
            content="Agreed. First step: design the product data model.",
        ),
    ]

    planning_store.extract_and_save(messages=messages, session_id=session_id)
    context = planning_store.get(session_id=session_id)

    print(f"\n📋 Long conversation summary:")
    if context:
        pprint(context.to_dict())

    # Cleanup
    planning_store.delete(session_id=session_id)

    print("\n✅ Long conversations summarized well")


# -----------------------------------------------------------------------------
# Test 11: Custom Instructions
# -----------------------------------------------------------------------------


def test_custom_instructions():
    """
    Customize what the extractor focuses on.
    """
    print("\n" + "=" * 60)
    print("TEST 11: Custom Instructions")
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
            Use bullet points in the summary.
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

    custom_store.extract_and_save(messages=messages, session_id=session_id)
    context = custom_store.get(session_id=session_id)

    print(f"\n📋 Custom-extracted context:")
    if context:
        print(f"   Summary: {context.summary}")

    # Cleanup
    custom_store.delete(session_id=session_id)

    print("\n✅ Custom instructions work")


# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------


def cleanup():
    """Clean up any lingering test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    test_sessions = [
        "summary_test_001",
        "planning_test_001",
        "compare_summary",
        "compare_planning",
        "replacement_test",
        "lifecycle_test",
        "format_test",
        "alice_session",
        "bob_session",
        "empty_test",
        "state_test",
        "long_test",
        "custom_test",
    ]

    for session_id in test_sessions:
        try:
            summary_store.delete(session_id=session_id)
            planning_store.delete(session_id=session_id)
        except Exception:
            pass

    print("🧹 Cleaned")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("📋 SessionContextStore Cookbook")
    print("   Context is everything")
    print("=" * 60)

    # Run tests
    test_basic_summary()
    test_planning_mode()
    test_summary_vs_planning()
    test_context_replacement()
    test_delete_and_clear()
    test_format_for_prompt()
    test_multi_session_isolation()
    test_empty_messages()
    test_state_tracking()
    test_long_conversation()
    test_custom_instructions()

    # Cleanup
    cleanup()

    print("\n" + "=" * 60)
    print("✅ All tests complete")
    print("   Remember: SessionContext REPLACES, UserProfile ACCUMULATES")
    print("=" * 60)
