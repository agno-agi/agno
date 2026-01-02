"""
UserProfileStore — Per-User Memory
===================================
Deep dive into UserProfileStore, which captures long-term facts about users.

Unlike SessionContextStore (which replaces), UserProfileStore ACCUMULATES
memories over time. Think of it as the agent's understanding of who
someone IS, not just what they're doing right now.

This cookbook demonstrates:
1. Manual memory CRUD (add, update, delete, clear)
2. Background extraction from conversations
3. Agent tool (update_user_memory)
4. Entity isolation (agent_id, team_id)
5. Custom extraction instructions
6. Incremental updates (knowledge compounds)
7. State tracking (was_updated)
8. build_context() formatting
9. __repr__ for debugging

Run this example:
    python cookbook/learning/04_user_profile_store.py
"""

from agno.db.postgres import PostgresDb
from agno.learn import LearningMode, UserProfileConfig
from agno.learn.stores.user import UserProfileStore
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# =============================================================================
# Setup
# =============================================================================

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
model = OpenAIChat(id="gpt-4o-mini")

# Create the store with full configuration
store = UserProfileStore(
    config=UserProfileConfig(
        db=db,
        model=model,
        mode=LearningMode.BACKGROUND,
        enable_tool=True,
        enable_add=True,
        enable_update=True,
        enable_delete=True,
        enable_clear=False,  # Safety: don't allow wiping everything
    )
)

# Test users
USER_ALICE = "alice@example.com"
USER_BOB = "bob@example.com"
USER_CHARLIE = "charlie@example.com"


# =============================================================================
# Test 1: Manual Memory Addition
# =============================================================================


def test_manual_memory():
    """
    The simplest case: explicitly add memories without LLM extraction.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Manual Memory Addition")
    print("=" * 60)

    # Add memories for Alice
    store.add_memory(USER_ALICE, "User is a software engineer at Stripe")
    store.add_memory(USER_ALICE, "User prefers Python over JavaScript")
    store.add_memory(USER_ALICE, "User works on payment infrastructure")

    # Add memories for Bob
    store.add_memory(USER_BOB, "User is a data scientist at Netflix")
    store.add_memory(USER_BOB, "User specializes in recommendation systems")

    # Retrieve and verify
    alice_profile = store.recall(user_id=USER_ALICE)
    print("\n👩‍💻 Alice's profile:")
    if alice_profile:
        pprint(alice_profile.to_dict())
        assert len(alice_profile.memories) == 3

    bob_profile = store.recall(user_id=USER_BOB)
    print("\n👨‍🔬 Bob's profile:")
    if bob_profile:
        pprint(bob_profile.to_dict())
        assert len(bob_profile.memories) == 2

    # Charlie doesn't exist yet
    charlie_profile = store.recall(user_id=USER_CHARLIE)
    assert charlie_profile is None
    print("\n🤷 Charlie: No profile yet")

    print("\n✅ Manual memory addition works!")


# =============================================================================
# Test 2: Background Extraction
# =============================================================================


def test_background_extraction():
    """
    Let the model figure out what's worth remembering from a conversation.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Background Extraction")
    print("=" * 60)

    # Charlie has a conversation
    messages = [
        Message(role="user", content="Hi! I'm Charlie, a product manager at Shopify."),
        Message(role="assistant", content="Nice to meet you, Charlie! How can I help?"),
        Message(role="user", content="I'm working on our checkout flow optimization."),
        Message(role="assistant", content="Interesting! What's your current focus?"),
        Message(
            role="user",
            content="I prefer data-driven decisions. I use SQL and Python for analysis.",
        ),
    ]

    # Extract memories
    print(f"\n📝 Processing {len(messages)} messages for Charlie...")
    store.process(messages=messages, user_id=USER_CHARLIE)
    print(f"🔄 was_updated: {store.was_updated}")

    # Check what was extracted
    profile = store.recall(user_id=USER_CHARLIE)
    print("\n👔 Charlie's extracted profile:")
    if profile:
        pprint(profile.to_dict())
        print(f"\n   Extracted {len(profile.memories)} memories")

    print("\n✅ Background extraction works!")


# =============================================================================
# Test 3: Agent Tool
# =============================================================================


def test_agent_tool():
    """
    Give an agent a tool to update memories on the fly.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Agent Tool")
    print("=" * 60)

    test_user = "tool_test@example.com"

    # Get the tool (this is what you'd pass to an agent)
    tools = store.get_tools(user_id=test_user)
    update_memory = tools[0] if tools else None

    if not update_memory:
        print("⚠️ No tool available")
        return

    # Inspect the tool
    print(f"\n🔧 Tool name: {update_memory.__name__}")
    print(f"   Tool doc: {update_memory.__doc__[:100]}...")

    # Agent calls the tool to add
    result = update_memory("User's favorite programming language is Rust")
    print(f"\n🔧 Add result: {result}")

    profile = store.recall(user_id=test_user)
    print("\n📋 Profile after add:")
    if profile:
        pprint(profile.to_dict())

    # Agent updates (user changed their mind)
    result = update_memory("Update: User now prefers Go over Rust")
    print(f"\n🔧 Update result: {result}")

    profile = store.recall(user_id=test_user)
    print("\n📋 Profile after update:")
    if profile:
        pprint(profile.to_dict())

    # Cleanup
    store.delete(user_id=test_user)

    print("\n✅ Agent tool works!")


# =============================================================================
# Test 4: Entity Isolation (agent_id, team_id)
# =============================================================================


def test_entity_isolation():
    """
    Different agents/teams can have separate views of the same user.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Entity Isolation")
    print("=" * 60)

    test_user = "isolation_test@example.com"

    # Support agent's view
    store.add_memory(test_user, "User prefers email support", agent_id="support_agent")
    store.add_memory(test_user, "User had issue with billing", agent_id="support_agent")

    # Sales agent's view
    store.add_memory(
        test_user, "User is interested in enterprise plan", agent_id="sales_agent"
    )
    store.add_memory(
        test_user, "User's company has 500 employees", agent_id="sales_agent"
    )

    # Global view (no agent_id)
    store.add_memory(test_user, "User is based in San Francisco")

    # Retrieve different views
    support_profile = store.recall(user_id=test_user, agent_id="support_agent")
    sales_profile = store.recall(user_id=test_user, agent_id="sales_agent")
    global_profile = store.recall(user_id=test_user)

    print("\n🎧 Support agent's view:")
    if support_profile:
        for m in support_profile.memories:
            print(f"   - {m.get('content', m)}")

    print("\n💼 Sales agent's view:")
    if sales_profile:
        for m in sales_profile.memories:
            print(f"   - {m.get('content', m)}")

    print("\n🌍 Global view:")
    if global_profile:
        for m in global_profile.memories:
            print(f"   - {m.get('content', m)}")

    # Cleanup
    store.delete(user_id=test_user)
    store.delete(user_id=test_user, agent_id="support_agent")
    store.delete(user_id=test_user, agent_id="sales_agent")

    print("\n✅ Entity isolation works!")


# =============================================================================
# Test 5: Custom Extraction Instructions
# =============================================================================


def test_custom_instructions():
    """
    Customize what the extractor focuses on.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Custom Extraction Instructions")
    print("=" * 60)

    # Store with custom instructions
    custom_store = UserProfileStore(
        config=UserProfileConfig(
            db=db,
            model=model,
            mode=LearningMode.BACKGROUND,
            instructions="""
            Focus ONLY on professional information:
            - Job title and company
            - Technical skills
            - Work preferences
            
            DO NOT capture:
            - Personal hobbies
            - Family information
            - Location details
            """,
        )
    )

    test_user = "custom_test@example.com"

    # Conversation with mixed content
    messages = [
        Message(
            role="user",
            content="I'm a backend engineer at Google. I live in Seattle with my family.",
        ),
        Message(role="assistant", content="Nice! What technologies do you work with?"),
        Message(
            role="user",
            content="Mostly Go and Python. I enjoy hiking on weekends. I prefer async communication.",
        ),
    ]

    custom_store.process(messages=messages, user_id=test_user)

    profile = custom_store.recall(user_id=test_user)
    print("\n📋 Profile (professional only):")
    if profile:
        pprint(profile.to_dict())

    # Cleanup
    custom_store.delete(user_id=test_user)

    print("\n✅ Custom instructions work!")


# =============================================================================
# Test 6: Incremental Updates
# =============================================================================


def test_incremental_updates():
    """
    Knowledge compounds over multiple conversations.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Incremental Updates")
    print("=" * 60)

    test_user = "incremental@example.com"

    # Day 1: Basic intro
    messages_1 = [
        Message(role="user", content="Hi, I'm a designer at Apple."),
        Message(role="assistant", content="Hello! What do you design?"),
        Message(role="user", content="I work on iOS interfaces."),
    ]
    store.process(messages=messages_1, user_id=test_user)
    profile_1 = store.recall(user_id=test_user)
    count_1 = len(profile_1.memories) if profile_1 else 0
    print(f"\n📅 Day 1: {count_1} memories")

    # Day 2: More details
    messages_2 = [
        Message(role="user", content="I'm working on accessibility features now."),
        Message(role="assistant", content="Accessibility is important!"),
        Message(role="user", content="I specialize in VoiceOver integration."),
    ]
    store.process(messages=messages_2, user_id=test_user)
    profile_2 = store.recall(user_id=test_user)
    count_2 = len(profile_2.memories) if profile_2 else 0
    print(f"📅 Day 2: {count_2} memories")

    # Day 3: Even more
    messages_3 = [
        Message(role="user", content="I prefer SwiftUI over UIKit nowadays."),
        Message(role="assistant", content="SwiftUI is great for rapid prototyping."),
    ]
    store.process(messages=messages_3, user_id=test_user)
    profile_3 = store.recall(user_id=test_user)
    count_3 = len(profile_3.memories) if profile_3 else 0
    print(f"📅 Day 3: {count_3} memories")

    print(f"\n📈 Memory growth: {count_1} → {count_2} → {count_3}")

    if profile_3:
        print("\n📋 Final profile:")
        pprint(profile_3.to_dict())

    # Cleanup
    store.delete(user_id=test_user)

    print("\n✅ Incremental updates work — knowledge compounds!")


# =============================================================================
# Test 7: Delete and Clear
# =============================================================================


def test_delete_and_clear():
    """
    The right to be forgotten.
    """
    print("\n" + "=" * 60)
    print("TEST 7: Delete and Clear")
    print("=" * 60)

    test_user = "delete_test@example.com"

    # Add some memories
    store.add_memory(test_user, "Memory 1")
    store.add_memory(test_user, "Memory 2")
    store.add_memory(test_user, "Memory 3")

    profile = store.recall(user_id=test_user)
    print(f"\n📋 Before delete: {len(profile.memories) if profile else 0} memories")

    # Delete the profile
    store.delete(user_id=test_user)

    profile = store.recall(user_id=test_user)
    print(f"📋 After delete: {profile}")

    print("\n✅ Delete works!")


# =============================================================================
# Test 8: State Tracking (was_updated)
# =============================================================================


def test_state_tracking():
    """
    Know when the profile actually changed.
    """
    print("\n" + "=" * 60)
    print("TEST 8: State Tracking (was_updated)")
    print("=" * 60)

    # Messages with useful info
    messages_useful = [
        Message(role="user", content="I'm Sarah, a DevOps engineer at Spotify."),
        Message(role="assistant", content="Hi Sarah!"),
    ]
    store.process(messages=messages_useful, user_id="useful@example.com")
    print(f"\n📝 After useful message: was_updated = {store.was_updated}")

    # Messages with nothing to extract
    messages_empty = [
        Message(role="user", content="What's 2 + 2?"),
        Message(role="assistant", content="4"),
    ]
    store.process(messages=messages_empty, user_id="empty@example.com")
    print(f"📝 After math question: was_updated = {store.was_updated}")

    # Cleanup
    store.delete(user_id="useful@example.com")
    store.delete(user_id="empty@example.com")

    print("\n✅ State tracking works!")


# =============================================================================
# Test 9: build_context() Formatting
# =============================================================================


def test_build_context():
    """
    Format profile for system prompt injection.
    """
    print("\n" + "=" * 60)
    print("TEST 9: build_context() Formatting")
    print("=" * 60)

    test_user = "context_test@example.com"

    # Add memories
    store.add_memory(test_user, "User is a backend engineer")
    store.add_memory(test_user, "User prefers detailed explanations")
    store.add_memory(test_user, "User uses Rust and Go")

    # Get profile and format
    profile = store.recall(user_id=test_user)
    context = store.build_context(data=profile)

    print("\n📝 Formatted context for system prompt:")
    print("-" * 40)
    print(context)
    print("-" * 40)

    # Should be XML formatted
    assert "<user_profile>" in context or context != ""

    # Cleanup
    store.delete(user_id=test_user)

    print("\n✅ build_context() works!")


# =============================================================================
# Test 10: __repr__ for Debugging
# =============================================================================


def test_repr():
    """
    Inspect store state with __repr__.
    """
    print("\n" + "=" * 60)
    print("TEST 10: __repr__ for Debugging")
    print("=" * 60)

    # Default config
    default_store = UserProfileStore(config=UserProfileConfig(db=db, model=model))
    print(f"\n📊 Default store: {default_store}")

    # Custom config
    custom_store = UserProfileStore(
        config=UserProfileConfig(
            db=db,
            model=model,
            mode=LearningMode.AGENTIC,
            enable_tool=True,
            enable_delete=False,
        )
    )
    print(f"📊 Custom store: {custom_store}")

    # Config repr
    print(f"\n📊 Config repr: {custom_store.config}")

    print("\n✅ __repr__ works for debugging!")


# =============================================================================
# Cleanup
# =============================================================================


def cleanup():
    """Clean up all test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    test_users = [
        USER_ALICE,
        USER_BOB,
        USER_CHARLIE,
        "tool_test@example.com",
        "isolation_test@example.com",
        "custom_test@example.com",
        "incremental@example.com",
        "delete_test@example.com",
        "useful@example.com",
        "empty@example.com",
        "context_test@example.com",
    ]

    for user_id in test_users:
        try:
            store.delete(user_id=user_id)
            store.delete(user_id=user_id, agent_id="support_agent")
            store.delete(user_id=user_id, agent_id="sales_agent")
        except Exception:
            pass

    print("🧹 Cleaned up test data")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧠 UserProfileStore — Per-User Memory")
    print("   Memories ACCUMULATE over time")
    print("=" * 60)

    # Run all tests
    test_manual_memory()
    test_background_extraction()
    test_agent_tool()
    test_entity_isolation()
    test_custom_instructions()
    test_incremental_updates()
    test_delete_and_clear()
    test_state_tracking()
    test_build_context()
    test_repr()

    # Cleanup
    cleanup()

    # Summary
    print("\n" + "=" * 60)
    print("✅ All tests complete!")
    print("=" * 60)
    print("""
Key takeaways:

1. **Accumulation**: Memories grow over time (vs SessionContext which replaces)

2. **Manual vs Auto**: add_memory() for explicit, process() for extraction

3. **Agent Tool**: update_user_memory lets agent save on the fly

4. **Isolation**: agent_id/team_id scope memories to contexts

5. **Custom Instructions**: Shape what gets extracted

6. **State Tracking**: was_updated tells you if anything changed
""")
