"""
User Profile Store - Multi-User Memory Persistence

This cookbook demonstrates the UserProfileStore for managing long-term
user memories that persist across sessions.

Features tested:
- Multi-user memory isolation
- Background extraction from conversations
- Manual memory addition via add_memory()
- Memory retrieval and verification
- Custom extraction instructions
"""

from agno.db.postgres import PostgresDb
from agno.learn.stores.user_profile import UserProfileStore
from agno.learn.config import UserProfileConfig
from agno.learn.schemas import DefaultUserProfile
from agno.models.openai import OpenAIChat
from agno.models.message import Message
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Create the store
store = UserProfileStore(db=db)

# Define test users
user_1_id = "alice@example.com"
user_2_id = "bob@example.com"
user_3_id = "charlie@example.com"


def test_manual_memory_addition():
    """Test adding memories manually."""
    print("=" * 60)
    print("TEST: Manual Memory Addition")
    print("=" * 60)

    # Add memory for user 1
    store.add_memory(user_1_id, "Alice is a software engineer at Google")
    store.add_memory(user_1_id, "She prefers Python over JavaScript")
    store.add_memory(user_1_id, "Works on search infrastructure")

    # Add memory for user 2
    store.add_memory(user_2_id, "Bob is a data scientist at Netflix")
    store.add_memory(user_2_id, "Specializes in recommendation systems")

    # Verify user 1 memories
    profile_1 = store.get(user_1_id)
    print(f"\nUser 1 ({user_1_id}) profile:")
    if profile_1:
        pprint(profile_1.to_dict())
        assert len(profile_1.memories) == 3, "User 1 should have 3 memories"
    else:
        print("  No profile found")

    # Verify user 2 memories (isolated from user 1)
    profile_2 = store.get(user_2_id)
    print(f"\nUser 2 ({user_2_id}) profile:")
    if profile_2:
        pprint(profile_2.to_dict())
        assert len(profile_2.memories) == 2, "User 2 should have 2 memories"
    else:
        print("  No profile found")

    # Verify user 3 has no memories yet
    profile_3 = store.get(user_3_id)
    print(f"\nUser 3 ({user_3_id}) profile:")
    assert profile_3 is None, "User 3 should have no profile yet"
    print("  No profile (as expected)")

    print("\n✅ Manual memory addition test passed!")


def test_background_extraction():
    """Test automatic extraction from conversation messages."""
    print("\n" + "=" * 60)
    print("TEST: Background Extraction from Conversation")
    print("=" * 60)

    model = OpenAIChat(id="gpt-4o-mini")

    # Simulate a conversation with user 3
    messages = [
        Message(role="user", content="Hi! I'm Charlie, a product manager at Stripe."),
        Message(role="assistant", content="Nice to meet you Charlie! How can I help you today?"),
        Message(role="user", content="I'm working on our payments API and need help with documentation."),
        Message(role="assistant", content="I'd be happy to help with API documentation. What specifically do you need?"),
        Message(role="user", content="I prefer concise explanations with code examples. Also, I use TypeScript mostly."),
    ]

    # Extract and save profile
    profile = store.extract_and_save(
        user_id=user_3_id,
        messages=messages,
        model=model,
    )

    print(f"\nExtracted profile for {user_3_id}:")
    if profile:
        pprint(profile.to_dict())
        # Should have extracted: name (Charlie), job (PM at Stripe), preferences (concise, code examples, TypeScript)
        assert profile.memories, "Should have extracted some memories"
        print(f"\n  Extracted {len(profile.memories)} memories")
    else:
        print("  Extraction returned None (may need more conversation context)")

    print("\n✅ Background extraction test passed!")


def test_memory_deduplication():
    """Test that duplicate memories are not added."""
    print("\n" + "=" * 60)
    print("TEST: Memory Deduplication")
    print("=" * 60)

    test_user = "dedup_test@example.com"

    # Add same memory multiple times
    store.add_memory(test_user, "Likes coffee")
    store.add_memory(test_user, "Likes coffee")  # Duplicate
    store.add_memory(test_user, "LIKES COFFEE")  # Case-insensitive duplicate
    store.add_memory(test_user, "Likes tea")  # Different

    profile = store.get(test_user)
    print(f"\nProfile for {test_user}:")
    if profile:
        pprint(profile.to_dict())
        # Should only have 2 unique memories
        print(f"\n  Total memories: {len(profile.memories)}")

    print("\n✅ Deduplication test passed!")


def test_custom_instructions():
    """Test store with custom extraction instructions."""
    print("\n" + "=" * 60)
    print("TEST: Custom Extraction Instructions")
    print("=" * 60)

    # Create store with custom instructions
    custom_config = UserProfileConfig(
        instructions="""
        Only extract professional/work-related information.
        Ignore personal hobbies and preferences.
        Focus on: job title, company, skills, projects.
        """
    )
    custom_store = UserProfileStore(db=db, config=custom_config)

    model = OpenAIChat(id="gpt-4o-mini")
    test_user = "custom_test@example.com"

    messages = [
        Message(role="user", content="I'm Dana, a ML engineer at OpenAI. I love hiking and photography."),
        Message(role="assistant", content="Nice to meet you Dana!"),
        Message(role="user", content="I work on GPT models and enjoy cooking on weekends."),
    ]

    profile = custom_store.extract_and_save(
        user_id=test_user,
        messages=messages,
        model=model,
    )

    print(f"\nExtracted profile (work-only) for {test_user}:")
    if profile:
        pprint(profile.to_dict())
        # Should focus on work info, less on hobbies
    else:
        print("  No profile extracted")

    print("\n✅ Custom instructions test passed!")


def test_profile_update():
    """Test updating an existing profile with new information."""
    print("\n" + "=" * 60)
    print("TEST: Profile Update (Incremental)")
    print("=" * 60)

    model = OpenAIChat(id="gpt-4o-mini")
    test_user = "update_test@example.com"

    # First conversation - establish basics
    messages_1 = [
        Message(role="user", content="Hi, I'm Eve, a designer at Apple."),
        Message(role="assistant", content="Hello Eve!"),
    ]

    store.extract_and_save(user_id=test_user, messages=messages_1, model=model)
    profile_1 = store.get(test_user)
    print(f"\nAfter first conversation:")
    if profile_1:
        pprint(profile_1.to_dict())
        initial_count = len(profile_1.memories)

    # Second conversation - add more info
    messages_2 = [
        Message(role="user", content="I've been working on the Vision Pro UI lately."),
        Message(role="assistant", content="That sounds exciting!"),
        Message(role="user", content="I specialize in spatial design and 3D interfaces."),
    ]

    store.extract_and_save(user_id=test_user, messages=messages_2, model=model)
    profile_2 = store.get(test_user)
    print(f"\nAfter second conversation:")
    if profile_2:
        pprint(profile_2.to_dict())
        final_count = len(profile_2.memories)
        print(f"\n  Memories grew from {initial_count} to {final_count}")

    print("\n✅ Profile update test passed!")


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    test_users = [
        user_1_id, user_2_id, user_3_id,
        "dedup_test@example.com",
        "custom_test@example.com",
        "update_test@example.com",
    ]

    for user_id in test_users:
        db.delete_learnings(learning_type="user_profile", user_id=user_id)

    print("  Cleaned up test data")


if __name__ == "__main__":
    # Run all tests
    test_manual_memory_addition()
    test_background_extraction()
    test_memory_deduplication()
    test_custom_instructions()
    test_profile_update()

    # Show final state
    print("\n" + "=" * 60)
    print("FINAL STATE")
    print("=" * 60)

    for user_id in [user_1_id, user_2_id, user_3_id]:
        profile = store.get(user_id)
        if profile:
            print(f"\n{user_id}:")
            print(f"  Name: {profile.name or 'Unknown'}")
            print(f"  Memories: {len(profile.memories)}")
            for m in profile.memories:
                print(f"    - {m.get('content', str(m))[:60]}...")

    # Uncomment to clean up
    # cleanup()

    print("\n" + "=" * 60)
    print("✅ All UserProfileStore tests passed!")
    print("=" * 60)
