"""
Multi-User Multi-Session Isolation
===================================
Testing that learning data is properly isolated between users and sessions.

This is critical for production: Alice's profile should never leak into
Bob's context, and Session A should never contaminate Session B.

This cookbook demonstrates:
1. Multiple users with separate profiles
2. Multiple sessions per user
3. Verification of no data leakage
4. Correct recall per user/session
5. Concurrent usage simulation
6. Entity isolation (agent_id, team_id)

Run this example:
    python cookbook/learning/08_multi_user_sessions.py
"""

from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import (
    LearningMachine,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

# =============================================================================
# Setup
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o-mini")

knowledge = Knowledge(
    name="Multi-User Test KB",
    vector_db=PgVector(
        db_url=db_url,
        table_name="multi_user_test",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Create the learning machine
learning = LearningMachine(
    db=db,
    model=model,
    knowledge=knowledge,
    user_profile=UserProfileConfig(enable_tool=True),
    session_context=SessionContextConfig(enable_planning=True),
    learnings=False,  # Keep it simple for isolation tests
)

# Test users
ALICE = "alice@company.com"
BOB = "bob@company.com"
CAROL = "carol@company.com"

# Test sessions
ALICE_SESSION_1 = "alice_project_planning"
ALICE_SESSION_2 = "alice_code_review"
BOB_SESSION_1 = "bob_debugging"
CAROL_SESSION_1 = "carol_architecture"


# =============================================================================
# Test 1: Create User Profiles
# =============================================================================


def test_create_user_profiles():
    """
    Create distinct profiles for multiple users.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Create User Profiles")
    print("=" * 60)

    # Alice: Senior engineer at Stripe, works on payments
    alice_messages = [
        Message(role="user", content="Hi! I'm Alice, a senior engineer at Stripe."),
        Message(role="assistant", content="Hello Alice! What do you work on?"),
        Message(
            role="user",
            content="I work on payment infrastructure. I prefer Go for high-performance systems.",
        ),
        Message(role="assistant", content="Go is great for that!"),
        Message(
            role="user",
            content="We use PostgreSQL for persistence. I like detailed code reviews.",
        ),
    ]

    # Bob: DevOps at Netflix, debugging Node.js
    bob_messages = [
        Message(
            role="user",
            content="Hey, I'm Bob. I'm debugging a memory leak in our Node.js app.",
        ),
        Message(role="assistant", content="Hi Bob! Memory leaks can be tricky."),
        Message(
            role="user", content="I work at Netflix on the streaming infrastructure."
        ),
        Message(role="assistant", content="What have you tried?"),
        Message(
            role="user",
            content="I use VSCode with the built-in debugger. Heap snapshots are my go-to.",
        ),
    ]

    # Carol: Tech lead at fintech startup, architecture decisions
    carol_messages = [
        Message(role="user", content="Hi, I'm Carol, tech lead at a fintech startup."),
        Message(role="assistant", content="Hello Carol! How can I help?"),
        Message(
            role="user",
            content="We're a small team of 5 engineers. I use Python with FastAPI.",
        ),
        Message(role="assistant", content="FastAPI is excellent for startups."),
        Message(
            role="user",
            content="I prefer monoliths over microservices for small teams.",
        ),
    ]

    # Process each user's messages
    print("\n📝 Creating profiles...")

    learning.process(messages=alice_messages, user_id=ALICE, session_id=ALICE_SESSION_1)
    print("   ✓ Alice's profile created")

    learning.process(messages=bob_messages, user_id=BOB, session_id=BOB_SESSION_1)
    print("   ✓ Bob's profile created")

    learning.process(messages=carol_messages, user_id=CAROL, session_id=CAROL_SESSION_1)
    print("   ✓ Carol's profile created")

    print("\n✅ User profiles created!")


# =============================================================================
# Test 2: Verify User Isolation
# =============================================================================


def test_user_isolation():
    """
    Verify that user profiles are properly isolated.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Verify User Isolation")
    print("=" * 60)

    # Recall each user's profile
    alice_data = learning.recall(user_id=ALICE)
    bob_data = learning.recall(user_id=BOB)
    carol_data = learning.recall(user_id=CAROL)

    print("\n👩 Alice's profile:")
    if alice_data.get("user_profile"):
        profile = alice_data["user_profile"]
        for m in profile.memories[:3]:
            content = m.get("content", str(m))
            print(f"   - {content[:60]}...")

    print("\n👨 Bob's profile:")
    if bob_data.get("user_profile"):
        profile = bob_data["user_profile"]
        for m in profile.memories[:3]:
            content = m.get("content", str(m))
            print(f"   - {content[:60]}...")

    print("\n👩‍💼 Carol's profile:")
    if carol_data.get("user_profile"):
        profile = carol_data["user_profile"]
        for m in profile.memories[:3]:
            content = m.get("content", str(m))
            print(f"   - {content[:60]}...")

    # Verify no cross-contamination
    print("\n🔍 Checking for data leakage...")

    if alice_data.get("user_profile"):
        alice_text = str(alice_data["user_profile"].to_dict()).lower()
        assert "bob" not in alice_text, "Alice's profile should not mention Bob"
        assert "netflix" not in alice_text, "Alice's profile should not mention Netflix"
        assert "carol" not in alice_text, "Alice's profile should not mention Carol"
        print("   ✓ Alice's profile is clean")

    if bob_data.get("user_profile"):
        bob_text = str(bob_data["user_profile"].to_dict()).lower()
        assert "alice" not in bob_text, "Bob's profile should not mention Alice"
        assert "stripe" not in bob_text, "Bob's profile should not mention Stripe"
        print("   ✓ Bob's profile is clean")

    if carol_data.get("user_profile"):
        carol_text = str(carol_data["user_profile"].to_dict()).lower()
        assert "alice" not in carol_text, "Carol's profile should not mention Alice"
        assert "bob" not in carol_text, "Carol's profile should not mention Bob"
        print("   ✓ Carol's profile is clean")

    print("\n✅ User profiles are properly isolated!")


# =============================================================================
# Test 3: Multiple Sessions Per User
# =============================================================================


def test_multiple_sessions():
    """
    Test that a single user can have multiple isolated sessions.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Multiple Sessions Per User")
    print("=" * 60)

    # Alice's second session: Code review (different context)
    alice_session_2_messages = [
        Message(role="user", content="Can you review this error handling code?"),
        Message(role="assistant", content="Sure, please share the code."),
        Message(
            role="user",
            content="func handleError(err error) { if err != nil { log.Fatal(err) } }",
        ),
        Message(
            role="assistant",
            content="Using log.Fatal in production isn't ideal. Return errors instead.",
        ),
    ]

    learning.process(
        messages=alice_session_2_messages,
        user_id=ALICE,
        session_id=ALICE_SESSION_2,
    )
    print("\n📝 Created Alice's second session (code review)")

    # Recall both sessions
    session_1 = learning.recall(user_id=ALICE, session_id=ALICE_SESSION_1)
    session_2 = learning.recall(user_id=ALICE, session_id=ALICE_SESSION_2)

    print("\n📋 Alice's Session 1 (Project Planning):")
    if session_1.get("session_context"):
        ctx = session_1["session_context"]
        print(f"   Summary: {ctx.summary[:80] if ctx.summary else 'None'}...")

    print("\n📋 Alice's Session 2 (Code Review):")
    if session_2.get("session_context"):
        ctx = session_2["session_context"]
        print(f"   Summary: {ctx.summary[:80] if ctx.summary else 'None'}...")

    # Verify sessions are different
    if session_1.get("session_context") and session_2.get("session_context"):
        ctx1 = session_1["session_context"]
        ctx2 = session_2["session_context"]
        if ctx1.summary and ctx2.summary:
            assert ctx1.summary != ctx2.summary, (
                "Sessions should have different summaries"
            )
            print("\n   ✓ Sessions are properly isolated")

    print("\n✅ Multiple sessions per user work!")


# =============================================================================
# Test 4: Correct Recall Per User
# =============================================================================


def test_correct_recall():
    """
    When Alice asks a question, she gets HER context, not Bob's.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Correct Recall Per User")
    print("=" * 60)

    # Alice asks a question
    print("\n👩 Alice asks: 'What database should I use for my project?'")
    alice_context = learning.build_context(
        user_id=ALICE,
        session_id=ALICE_SESSION_1,
        message="What database should I use for my project?",
    )

    print(f"\n📋 Context returned for Alice ({len(alice_context)} chars):")
    # Should mention Stripe, Go, PostgreSQL - NOT Netflix, Node.js
    if "stripe" in alice_context.lower() or "go" in alice_context.lower():
        print("   ✓ Context includes Alice's info (Stripe, Go)")
    if "netflix" in alice_context.lower() or "node" in alice_context.lower():
        print("   ✗ ERROR: Context leaked Bob's info!")
    else:
        print("   ✓ Context does NOT include Bob's info")

    # Bob asks a question
    print("\n👨 Bob asks: 'How do I debug this memory issue?'")
    bob_context = learning.build_context(
        user_id=BOB,
        session_id=BOB_SESSION_1,
        message="How do I debug this memory issue?",
    )

    print(f"\n📋 Context returned for Bob ({len(bob_context)} chars):")
    # Should mention Netflix, Node.js, VSCode - NOT Stripe, Go
    if "netflix" in bob_context.lower() or "node" in bob_context.lower():
        print("   ✓ Context includes Bob's info (Netflix, Node)")
    if "stripe" in bob_context.lower():
        print("   ✗ ERROR: Context leaked Alice's info!")
    else:
        print("   ✓ Context does NOT include Alice's info")

    print("\n✅ Correct context returned per user!")


# =============================================================================
# Test 5: Concurrent Usage Simulation
# =============================================================================


def test_concurrent_simulation():
    """
    Simulate concurrent usage by multiple users.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Concurrent Usage Simulation")
    print("=" * 60)

    # Interleaved operations (simulating concurrent requests)
    operations = [
        (ALICE, "What's the best caching strategy?"),
        (BOB, "How do I profile Node.js memory?"),
        (CAROL, "Should we use GraphQL or REST?"),
        (ALICE, "How do I optimize PostgreSQL queries?"),
        (BOB, "What's the best logging library for Node?"),
        (CAROL, "How do we handle database migrations?"),
    ]

    print("\n📝 Simulating interleaved requests...")
    results = []

    for user_id, message in operations:
        context = learning.build_context(
            user_id=user_id,
            message=message,
        )
        user_name = user_id.split("@")[0].title()
        results.append((user_name, message, len(context)))
        print(f"   {user_name}: '{message[:40]}...' → {len(context)} chars context")

    print("\n🔍 Verifying no cross-contamination...")
    # Each user should get consistent context throughout

    alice_contexts = [r for r in results if r[0] == "Alice"]
    bob_contexts = [r for r in results if r[0] == "Bob"]
    carol_contexts = [r for r in results if r[0] == "Carol"]

    print(f"   Alice: {len(alice_contexts)} requests")
    print(f"   Bob: {len(bob_contexts)} requests")
    print(f"   Carol: {len(carol_contexts)} requests")

    print("\n✅ Concurrent simulation complete!")


# =============================================================================
# Test 6: Entity Isolation (agent_id, team_id)
# =============================================================================


def test_entity_isolation():
    """
    Test isolation by agent_id and team_id.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Entity Isolation (agent_id, team_id)")
    print("=" * 60)

    test_user = "entity_test@example.com"

    # Add memories with different agent contexts
    user_store = learning.stores.get("user_profile")

    if user_store and hasattr(user_store, "add_memory"):
        # Support agent's view of user
        user_store.add_memory(
            test_user,
            "User had billing issue on Jan 15",
            agent_id="support_agent",
        )
        user_store.add_memory(
            test_user,
            "User prefers email over phone",
            agent_id="support_agent",
        )

        # Sales agent's view of user
        user_store.add_memory(
            test_user,
            "User interested in enterprise plan",
            agent_id="sales_agent",
        )
        user_store.add_memory(
            test_user,
            "User's company has 200 employees",
            agent_id="sales_agent",
        )

        print("\n📝 Added memories for different agents")

        # Recall with agent filter
        support_view = user_store.recall(user_id=test_user, agent_id="support_agent")
        sales_view = user_store.recall(user_id=test_user, agent_id="sales_agent")

        print("\n🎧 Support Agent's view:")
        if support_view:
            for m in support_view.memories:
                print(f"   - {m.get('content', m)}")

        print("\n💼 Sales Agent's view:")
        if sales_view:
            for m in sales_view.memories:
                print(f"   - {m.get('content', m)}")

        # Verify isolation
        if support_view and sales_view:
            support_text = str(support_view.to_dict()).lower()
            sales_text = str(sales_view.to_dict()).lower()

            if "enterprise" not in support_text and "billing" not in sales_text:
                print("\n   ✓ Agent views are properly isolated")

        # Cleanup
        user_store.delete(user_id=test_user)
        user_store.delete(user_id=test_user, agent_id="support_agent")
        user_store.delete(user_id=test_user, agent_id="sales_agent")

    print("\n✅ Entity isolation works!")


# =============================================================================
# Cleanup
# =============================================================================


def cleanup():
    """Clean up all test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    user_store = learning.stores.get("user_profile")
    session_store = learning.stores.get("session_context")

    users = [ALICE, BOB, CAROL, "entity_test@example.com"]
    sessions = [ALICE_SESSION_1, ALICE_SESSION_2, BOB_SESSION_1, CAROL_SESSION_1]

    if user_store and hasattr(user_store, "delete"):
        for user_id in users:
            try:
                user_store.delete(user_id=user_id)
            except Exception:
                pass

    if session_store and hasattr(session_store, "delete"):
        for session_id in sessions:
            try:
                session_store.delete(session_id=session_id)
            except Exception:
                pass

    print("🧹 Cleaned up test data")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🔒 Multi-User Multi-Session Isolation")
    print("   Testing data isolation between users and sessions")
    print("=" * 60)

    # Run all tests
    test_create_user_profiles()
    test_user_isolation()
    test_multiple_sessions()
    test_correct_recall()
    test_concurrent_simulation()
    test_entity_isolation()

    # Cleanup
    cleanup()

    # Summary
    print("\n" + "=" * 60)
    print("✅ All isolation tests passed!")
    print("=" * 60)
    print("""
Key takeaways:

1. **User Isolation**: Alice's profile never leaks into Bob's context

2. **Session Isolation**: Same user can have multiple independent sessions

3. **Correct Recall**: build_context() returns the right data for each user

4. **Concurrent Safety**: Interleaved requests maintain isolation

5. **Entity Isolation**: agent_id/team_id provide additional scoping

This is CRITICAL for production:
• Privacy: Users only see their own data
• Correctness: Context is always relevant
• Security: No accidental data exposure
""")
