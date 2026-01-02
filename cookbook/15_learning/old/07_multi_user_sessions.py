"""
Multi-User, Multi-Session Learning

This cookbook demonstrates a realistic scenario with multiple users
and sessions, showing how the learning system maintains proper isolation.

Similar to the memory multi-user example but using LearningMachine.

Scenario:
- User 1 (Alice): 2 sessions - project planning and code review
- User 2 (Bob): 1 session - debugging help
- User 3 (Carol): 1 session - architecture discussion

Each user should have isolated memories, and each session should
have its own context.
"""

from agno.db.postgres import PostgresDb
from agno.learn import (
    LearningMachine,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.message import Message
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Create the learning machine
learning = LearningMachine(
    db=db,
    user_profile=UserProfileConfig(enable_tool=True),
    session_context=SessionContextConfig(enable_planning=True),
    learned_knowledge=False,  # Keep it simple for this demo
)

model = OpenAIChat(id="gpt-4o-mini")

# User and session IDs
alice_id = "alice@example.com"
bob_id = "bob@example.com"
carol_id = "carol@example.com"

alice_session_1 = "alice_project_planning"
alice_session_2 = "alice_code_review"
bob_session_1 = "bob_debugging"
carol_session_1 = "carol_architecture"


def simulate_conversation(user_id: str, session_id: str, messages: list):
    """Simulate a conversation and run learning extraction."""
    print(f"\n  [{user_id}] Session: {session_id}")

    # Convert to Message objects
    msg_objects = [Message(role=m["role"], content=m["content"]) for m in messages]

    # Run extraction
    learning.process(
        user_id=user_id,
        session_id=session_id,
        messages=msg_objects,
        model=model,
    )

    # Show last message
    last_msg = messages[-1]["content"][:60]
    print(f"    Last message: {last_msg}...")


def run_conversations():
    """Run all the test conversations."""
    print("=" * 60)
    print("RUNNING CONVERSATIONS")
    print("=" * 60)

    # Alice - Session 1: Project Planning
    simulate_conversation(
        user_id=alice_id,
        session_id=alice_session_1,
        messages=[
            {
                "role": "user",
                "content": "Hi! I'm Alice, a senior engineer at Stripe. I need help planning a new payment gateway.",
            },
            {
                "role": "assistant",
                "content": "Hello Alice! I'd be happy to help with your payment gateway project. What are the key requirements?",
            },
            {
                "role": "user",
                "content": "We need to support multiple currencies, have sub-100ms latency, and handle 10k TPS.",
            },
            {
                "role": "assistant",
                "content": "Those are solid requirements. Let me suggest a phased approach...",
            },
            {
                "role": "user",
                "content": "I prefer working with Go for high-performance systems. Also, we use PostgreSQL for persistence.",
            },
        ],
    )

    # Alice - Session 2: Code Review
    simulate_conversation(
        user_id=alice_id,
        session_id=alice_session_2,
        messages=[
            {"role": "user", "content": "Can you review this error handling code?"},
            {"role": "assistant", "content": "Sure, please share the code."},
            {
                "role": "user",
                "content": "func handleError(err error) { if err != nil { log.Fatal(err) } }",
            },
            {
                "role": "assistant",
                "content": "Using log.Fatal in production code is usually not ideal. Consider returning errors instead.",
            },
        ],
    )

    # Bob - Session 1: Debugging
    simulate_conversation(
        user_id=bob_id,
        session_id=bob_session_1,
        messages=[
            {
                "role": "user",
                "content": "Hey, I'm Bob. I'm debugging a memory leak in our Node.js app.",
            },
            {
                "role": "assistant",
                "content": "Hi Bob! Memory leaks in Node can be tricky. What symptoms are you seeing?",
            },
            {
                "role": "user",
                "content": "The heap keeps growing even with low traffic. I've already checked for event listener leaks.",
            },
            {
                "role": "assistant",
                "content": "Good that you checked event listeners. Let's look at closures and global variables next.",
            },
            {
                "role": "user",
                "content": "I'm using VSCode with the built-in debugger. Any tips for heap snapshots?",
            },
        ],
    )

    # Carol - Session 1: Architecture Discussion
    simulate_conversation(
        user_id=carol_id,
        session_id=carol_session_1,
        messages=[
            {
                "role": "user",
                "content": "Hi, I'm Carol, the tech lead at a fintech startup.",
            },
            {"role": "assistant", "content": "Hello Carol! How can I help you today?"},
            {
                "role": "user",
                "content": "We're debating between microservices and a modular monolith.",
            },
            {
                "role": "assistant",
                "content": "Great question. For a startup, I often recommend starting with a modular monolith.",
            },
            {
                "role": "user",
                "content": "That makes sense. We're a small team of 5 engineers.",
            },
            {
                "role": "assistant",
                "content": "With 5 engineers, a monolith will definitely reduce operational overhead.",
            },
            {
                "role": "user",
                "content": "We're using Python with FastAPI. What about async patterns?",
            },
        ],
    )


def verify_user_isolation():
    """Verify that user profiles are properly isolated."""
    print("\n" + "=" * 60)
    print("VERIFYING USER ISOLATION")
    print("=" * 60)

    for user_id, name in [(alice_id, "Alice"), (bob_id, "Bob"), (carol_id, "Carol")]:
        profile = learning._user_profile_store.get(user_id)
        print(f"\n{name}'s Profile ({user_id}):")
        if profile:
            print(f"  Name: {profile.name or 'Not extracted'}")
            print(f"  Memories ({len(profile.memories)}):")
            for m in profile.memories:
                content = m.get("content", str(m))
                print(f"    - {content[:70]}{'...' if len(content) > 70 else ''}")
        else:
            print("  No profile yet")

    # Verify isolation - Alice's profile shouldn't mention Bob or Carol
    alice_profile = learning._user_profile_store.get(alice_id)
    if alice_profile:
        alice_text = str(alice_profile.to_dict()).lower()
        assert "bob" not in alice_text, "Alice's profile should not mention Bob"
        assert "carol" not in alice_text, "Alice's profile should not mention Carol"
        print("\n✓ User profiles are properly isolated")


def verify_session_isolation():
    """Verify that session contexts are properly isolated."""
    print("\n" + "=" * 60)
    print("VERIFYING SESSION ISOLATION")
    print("=" * 60)

    sessions = [
        (alice_session_1, "Alice's Planning Session"),
        (alice_session_2, "Alice's Code Review Session"),
        (bob_session_1, "Bob's Debugging Session"),
        (carol_session_1, "Carol's Architecture Session"),
    ]

    for session_id, description in sessions:
        context = learning._session_context_store.get(session_id)
        print(f"\n{description} ({session_id}):")
        if context:
            print(
                f"  Summary: {context.summary[:80] if context.summary else 'None'}..."
            )
            if context.goal:
                print(f"  Goal: {context.goal[:60]}...")
            if context.plan:
                print(f"  Plan steps: {len(context.plan)}")
        else:
            print("  No context yet")

    # Verify Alice's two sessions are different
    ctx_1 = learning._session_context_store.get(alice_session_1)
    ctx_2 = learning._session_context_store.get(alice_session_2)
    if ctx_1 and ctx_2:
        assert ctx_1.summary != ctx_2.summary, (
            "Sessions should have different summaries"
        )
        print("\n✓ Session contexts are properly isolated")


def test_recall_for_user():
    """Test that recall returns the right data for each user."""
    print("\n" + "=" * 60)
    print("TESTING RECALL PER USER")
    print("=" * 60)

    # Alice asks a follow-up question in session 1
    print("\nAlice asks: 'What should I consider for the database schema?'")
    alice_recall = learning.recall(
        user_id=alice_id,
        session_id=alice_session_1,
        message="What should I consider for the database schema?",
    )

    print("Recalled for Alice:")
    if alice_recall.get("user_profile"):
        print(f"  User profile: {alice_recall['user_profile'].memories[:2]}...")
    if alice_recall.get("session_context"):
        print(
            f"  Session context: {alice_recall['session_context'].summary[:60] if alice_recall['session_context'].summary else 'None'}..."
        )

    # Bob asks a question
    print("\nBob asks: 'How do I take a heap snapshot?'")
    bob_recall = learning.recall(
        user_id=bob_id,
        session_id=bob_session_1,
        message="How do I take a heap snapshot?",
    )

    print("Recalled for Bob:")
    if bob_recall.get("user_profile"):
        print(f"  User profile: {bob_recall['user_profile'].memories[:2]}...")
    if bob_recall.get("session_context"):
        print(
            f"  Session context: {bob_recall['session_context'].summary[:60] if bob_recall['session_context'].summary else 'None'}..."
        )

    # Verify correct data
    if alice_recall.get("user_profile") and bob_recall.get("user_profile"):
        alice_data = str(alice_recall["user_profile"].to_dict()).lower()
        bob_data = str(bob_recall["user_profile"].to_dict()).lower()

        # Alice's recall shouldn't have Node.js stuff
        assert "node" not in alice_data or "stripe" in alice_data, (
            "Alice's recall should be about her context"
        )

        print("\n✓ Recall returns correct data per user")


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    users = [alice_id, bob_id, carol_id]
    sessions = [alice_session_1, alice_session_2, bob_session_1, carol_session_1]

    for user_id in users:
        db.delete_learnings(learning_type="user_profile", user_id=user_id)

    for session_id in sessions:
        db.delete_learnings(learning_type="session_context", session_id=session_id)

    print("  Cleaned up all test data")


if __name__ == "__main__":
    print("=" * 60)
    print("MULTI-USER MULTI-SESSION LEARNING DEMO")
    print("=" * 60)

    # Run the demo
    run_conversations()
    verify_user_isolation()
    verify_session_isolation()
    test_recall_for_user()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print("""
    This demo showed:

    1. User Profile Isolation:
       - Alice, Bob, and Carol each have separate profiles
       - Each profile only contains info about that user

    2. Session Context Isolation:
       - Alice's 2 sessions have different contexts
       - Each user's session is independent

    3. Recall Returns Correct Data:
       - When Alice asks a question, she gets her context
       - When Bob asks, he gets his context

    This is the foundation for personalized, context-aware agents!
    """)

    # Uncomment to clean up
    # cleanup()

    print("\n" + "=" * 60)
    print("✅ Multi-user multi-session demo complete!")
    print("=" * 60)
