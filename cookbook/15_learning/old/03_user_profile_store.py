"""
User Profile Store Cookbook
===========================

This cookbook demonstrates the UserProfileStore - a system for remembering
what matters about users across conversations. Not just facts, but patterns.
Not just data, but understanding.

This cookbook showcases:
1. Manual memory addition - The simplest path
2. Background extraction - Let the model find what matters
3. Agent tool - Give agents the power to remember
4. Direct update - Run updates without agent wrapper
5. Delete and clear - The right to be forgotten
6. Entity context - Different agents, different perspectives
7. Custom instructions - Shape what gets captured
8. Incremental updates - Knowledge compounds
9. State tracking - Know when things changed
10. Deep extraction - Values, style, expertise (the good stuff)
"""

from agno.db.postgres import PostgresDb
from agno.learn import UserProfileConfig, UserProfileStore
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

# Setup the store - where memories live
store = UserProfileStore(
    config=UserProfileConfig(
        db=db,
        model=model,
        enable_add=True,
        enable_update=True,
        enable_delete=True,
        enable_clear=False,  # Make them ask twice before nuking everything
    )
)

# Setup logging (only needed when using store directly, not through LearningMachine)
store.set_log_level()

# Our cast of characters
USER_ALICE = "alice@example.com"
USER_BOB = "bob@example.com"
USER_CHARLIE = "charlie@example.com"


# -----------------------------------------------------------------------------
# Test 1: Manual Memory Addition
# -----------------------------------------------------------------------------


def test_manual_memory_addition():
    """
    The simplest case: explicitly tell the system what to remember.
    No LLM needed. Just store.add_memory(user, fact).
    """
    print("\n" + "=" * 60)
    print("TEST 1: Manual Memory Addition")
    print("=" * 60)

    # Alice: the engineer
    store.add_memory(USER_ALICE, "User is a software engineer at Google")
    store.add_memory(USER_ALICE, "User prefers Python over JavaScript")
    store.add_memory(USER_ALICE, "User works on search infrastructure")

    # Bob: the data guy
    store.add_memory(USER_BOB, "User is a data scientist at Netflix")
    store.add_memory(USER_BOB, "User specializes in recommendation systems")

    # Verify Alice
    profile_alice = store.get(USER_ALICE)
    print(f"\n👩‍💻 Alice ({USER_ALICE}):")
    if profile_alice:
        pprint(profile_alice.to_dict())
        assert len(profile_alice.memories) == 3
    else:
        raise AssertionError("Alice should exist")

    # Verify Bob (isolated from Alice)
    profile_bob = store.get(USER_BOB)
    print(f"\n👨‍🔬 Bob ({USER_BOB}):")
    if profile_bob:
        pprint(profile_bob.to_dict())
        assert len(profile_bob.memories) == 2
    else:
        raise AssertionError("Bob should exist")

    # Charlie doesn't exist yet
    profile_charlie = store.get(USER_CHARLIE)
    assert profile_charlie is None, "Charlie hasn't said anything yet"
    print(f"\n🤷 Charlie ({USER_CHARLIE}): No profile yet")

    print("\n✅ Memories stored, users isolated")


# -----------------------------------------------------------------------------
# Test 2: Background Extraction
# -----------------------------------------------------------------------------


def test_background_extraction():
    """
    The magic: give the model a conversation, let it figure out
    what's worth remembering. No explicit "remember this" needed.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Background Extraction")
    print("=" * 60)

    # Charlie has a conversation...
    messages = [
        Message(role="user", content="Hi! I'm Charlie, a product manager at Stripe."),
        Message(role="assistant", content="Nice to meet you Charlie! How can I help?"),
        Message(role="user", content="I'm working on our payments API documentation."),
        Message(role="assistant", content="Happy to help with docs. What do you need?"),
        Message(
            role="user",
            content="I prefer concise explanations with code examples. I use TypeScript.",
        ),
    ]

    # Extract what matters
    response = store.extract_and_save(messages=messages, user_id=USER_CHARLIE)

    print(f"\n📝 Extraction response: {response}")
    print(f"🔄 Profile updated: {store.was_updated}")  # Protocol property

    # What did we learn?
    profile = store.get(USER_CHARLIE)
    print("\n👔 Charlie's extracted profile:")
    if profile:
        pprint(profile.to_dict())
        # Should have: name, job, company, preferences, language
        assert profile.memories, "Should have learned something"
        print(f"\n   Learned {len(profile.memories)} things about Charlie")

    print("\n✅ Extraction works")


# -----------------------------------------------------------------------------
# Test 3: Agent Tool
# -----------------------------------------------------------------------------


def test_agent_tool():
    """
    Give an agent a tool to update memories on the fly.
    The agent decides when to call it.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Agent Tool")
    print("=" * 60)

    test_user = "tool_test@example.com"

    # Get the tool (this is what you'd give to an agent)
    update_memory = store.get_agent_tool(user_id=test_user)

    # Inspect the tool
    print(f"\n🔧 Tool name: {update_memory.__name__}")
    print(f"   Tool doc: {update_memory.__doc__[:100]}...")

    # Agent calls the tool
    result = update_memory("User's favorite color is blue")
    print(f"\n🔧 Tool result: {result}")

    profile = store.get(test_user)
    print("\n📋 Profile after add:")
    if profile:
        pprint(profile.to_dict())

    # Agent updates (user changed their mind)
    result = update_memory("User now prefers green, not blue")
    print(f"\n🔧 Update result: {result}")

    profile = store.get(test_user)
    print("\n📋 Profile after update:")
    if profile:
        pprint(profile.to_dict())

    print("\n✅ Agent tool works")


# -----------------------------------------------------------------------------
# Test 4: Direct Update
# -----------------------------------------------------------------------------


def test_direct_update():
    """
    Sometimes you want to run an update without the agent wrapper.
    Same power, direct access.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Direct Update")
    print("=" * 60)

    test_user = "direct_test@example.com"

    # Start with a fact
    store.add_memory(test_user, "User works at Meta")

    profile_before = store.get(test_user)
    print("\n📋 Profile before update:")
    if profile_before:
        pprint(profile_before.to_dict())

    # Life changes...
    result = store.run_user_profile_update(
        task="User has left Meta and joined Anthropic as a researcher",
        user_id=test_user,
    )

    print(f"\n📝 Update result: {result}")
    print(f"🔄 Profile updated: {store.was_updated}")

    profile_after = store.get(test_user)
    print("\n📋 Profile after career change:")
    if profile_after:
        pprint(profile_after.to_dict())

    print("\n✅ Direct update works")


# -----------------------------------------------------------------------------
# Test 5: Delete and Clear
# -----------------------------------------------------------------------------


def test_delete_and_clear():
    """
    The right to be forgotten. Sometimes you need to erase.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Delete and Clear")
    print("=" * 60)

    test_user = "ephemeral@example.com"

    # Build up some memories
    store.add_memory(test_user, "First memory")
    store.add_memory(test_user, "Second memory")
    store.add_memory(test_user, "Third memory")

    profile = store.get(test_user)
    print(f"\n📊 Before clear: {len(profile.memories)} memories")

    # Clear = reset to empty (profile still exists)
    store.clear(test_user)
    profile = store.get(test_user)
    print(f"🧹 After clear: {len(profile.memories) if profile else 0} memories")

    # Add something back
    store.add_memory(test_user, "Fresh start")
    profile = store.get(test_user)
    print(f"🌱 After fresh start: {len(profile.memories)} memories")

    # Delete = profile gone entirely
    deleted = store.delete(test_user)
    print(f"🗑️  Delete returned: {deleted}")

    profile = store.get(test_user)
    print(f"🗑️  After delete: {profile}")

    assert profile is None, "Should be truly gone"

    print("\n✅ Forgetting works")


# -----------------------------------------------------------------------------
# Test 6: Entity Context
# -----------------------------------------------------------------------------


def test_entity_context():
    """
    Same user, different agents = different profiles.
    The support agent doesn't need to know what sales discussed.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Entity Context")
    print("=" * 60)

    test_user = "context_test@example.com"

    # Support agent learns one thing
    store.add_memory(
        test_user,
        "User frustrated with billing errors",
        agent_id="support_agent",
    )

    # Sales agent learns another
    store.add_memory(
        test_user,
        "User interested in enterprise plan upgrade",
        agent_id="sales_agent",
    )

    # Each agent sees only their context
    support_view = store.get(test_user, agent_id="support_agent")
    sales_view = store.get(test_user, agent_id="sales_agent")

    print("\n🎧 Support agent sees:")
    if support_view:
        pprint(support_view.to_dict())

    print("\n💼 Sales agent sees:")
    if sales_view:
        pprint(sales_view.to_dict())

    # Verify isolation
    assert support_view and len(support_view.memories) == 1
    assert sales_view and len(sales_view.memories) == 1
    assert support_view.memories[0]["content"] != sales_view.memories[0]["content"]

    print("\n✅ Contexts isolated")


# -----------------------------------------------------------------------------
# Test 7: Custom Instructions
# -----------------------------------------------------------------------------


def test_custom_instructions():
    """
    Shape what gets captured. Work-only? Personal-only? You decide.
    """
    print("\n" + "=" * 60)
    print("TEST 7: Custom Instructions")
    print("=" * 60)

    # A store that ONLY captures work stuff
    work_store = UserProfileStore(
        config=UserProfileConfig(
            db=db,
            model=model,
            instructions="""
            ONLY extract professional/work-related information.
            IGNORE: hobbies, food preferences, leisure activities, personal life.
            CAPTURE: job title, company, skills, projects, work preferences.
            """,
        )
    )

    test_user = "work_only@example.com"

    # User shares mix of work and personal
    messages = [
        Message(role="user", content="I'm Dana, ML engineer at OpenAI. I love hiking!"),
        Message(role="assistant", content="Nice to meet you!"),
        Message(role="user", content="I work on GPT. Sushi is my favorite food."),
    ]

    work_store.extract_and_save(messages=messages, user_id=test_user)

    profile = work_store.get(test_user)
    print("\n💼 Work-only profile:")
    if profile:
        pprint(profile.to_dict())

        # Verify no personal stuff leaked through
        for mem in profile.memories:
            content = mem.get("content", "").lower()
            assert "hiking" not in content, "No hiking!"
            assert "sushi" not in content, "No sushi!"

        print("\n   ✅ Personal info filtered out")

    print("\n✅ Custom instructions respected")


# -----------------------------------------------------------------------------
# Test 8: Incremental Update
# -----------------------------------------------------------------------------


def test_incremental_update():
    """
    Knowledge compounds. Each conversation adds to the picture.
    """
    print("\n" + "=" * 60)
    print("TEST 8: Incremental Update")
    print("=" * 60)

    test_user = "growing@example.com"

    # First conversation
    messages_1 = [
        Message(role="user", content="Hi, I'm Eve, a designer at Apple."),
        Message(role="assistant", content="Hello Eve!"),
    ]

    store.extract_and_save(messages=messages_1, user_id=test_user)
    profile_1 = store.get(test_user)
    count_1 = len(profile_1.memories) if profile_1 else 0
    print(f"\n📅 Day 1: {count_1} memories")
    if profile_1:
        pprint(profile_1.to_dict())

    # Second conversation - more depth
    messages_2 = [
        Message(role="user", content="I'm working on Vision Pro UI."),
        Message(role="assistant", content="Exciting!"),
        Message(
            role="user", content="I specialize in spatial design and 3D interfaces."
        ),
    ]

    store.extract_and_save(messages=messages_2, user_id=test_user)
    profile_2 = store.get(test_user)
    count_2 = len(profile_2.memories) if profile_2 else 0
    print(f"\n📅 Day 2: {count_2} memories")
    if profile_2:
        pprint(profile_2.to_dict())

    print(f"\n📈 Growth: {count_1} → {count_2}")
    assert count_2 >= count_1, "Knowledge should accumulate"

    print("\n✅ Knowledge compounds")


# -----------------------------------------------------------------------------
# Test 9: State Tracking
# -----------------------------------------------------------------------------


def test_state_tracking():
    """
    Know when the profile actually changed vs. when nothing happened.
    """
    print("\n" + "=" * 60)
    print("TEST 9: State Tracking")
    print("=" * 60)

    # Message with useful info
    messages_useful = [
        Message(role="user", content="I'm Grace, I work at SpaceX on Starship."),
    ]

    store.extract_and_save(messages=messages_useful, user_id="useful@example.com")
    print(f"\n🎯 After useful message: was_updated = {store.was_updated}")
    assert store.was_updated, "Should have updated"

    # Message with nothing to extract
    messages_empty = [
        Message(role="user", content="What's the weather like?"),
    ]

    store.extract_and_save(messages=messages_empty, user_id="empty@example.com")
    print(f"🌧️  After weather question: was_updated = {store.was_updated}")
    # This one is tricky - depends on model interpretation
    # Model might not call any tools, so was_updated could be False

    print("\n✅ State tracking works")


# -----------------------------------------------------------------------------
# Test 10: Deep Extraction (The Good Stuff)
# -----------------------------------------------------------------------------


def test_deep_extraction():
    """
    The real test: can it capture VALUES, STYLE, and EXPERTISE?
    Not just facts, but who someone IS.
    """
    print("\n" + "=" * 60)
    print("TEST 10: Deep Extraction")
    print("=" * 60)

    test_user = "deep@example.com"

    # A rich conversation revealing personality
    messages = [
        Message(
            role="user",
            content="I've been thinking about our AI safety work. I believe in being direct "
            "about risks, even when it's uncomfortable. Too many researchers hedge.",
        ),
        Message(
            role="assistant",
            content="That's a principled stance. What drives that view?",
        ),
        Message(
            role="user",
            content="I worked at DeepMind for 5 years. Saw too much 'we'll figure it out later.' "
            "Now I'm at Anthropic because they take alignment seriously. "
            "I'm a stickler for first-principles thinking.",
        ),
        Message(role="assistant", content="How do you approach problems?"),
        Message(
            role="user",
            content="I like to start from fundamentals, build up. I get frustrated when "
            "people skip steps or use jargon to hide confusion. "
            "Oh, and I prefer async communication - Slack over meetings any day.",
        ),
    ]

    store.extract_and_save(messages=messages, user_id=test_user)

    profile = store.get(test_user)
    print("\n🧠 Deep profile:")
    if profile:
        pprint(profile.to_dict())

        # What should we have captured?
        all_content = " ".join(m.get("content", "") for m in profile.memories).lower()

        checks = {
            "values": any(x in all_content for x in ["direct", "principled", "risks"]),
            "career": any(x in all_content for x in ["deepmind", "anthropic"]),
            "style": any(
                x in all_content for x in ["first-principles", "fundamentals"]
            ),
            "prefs": any(x in all_content for x in ["async", "slack"]),
            "frustrations": any(x in all_content for x in ["frustrated", "jargon"]),
        }

        print("\n📊 Extraction quality:")
        for aspect, found in checks.items():
            status = "✅" if found else "❌"
            print(f"   {status} {aspect}")

    print("\n✅ Deep extraction complete")


# -----------------------------------------------------------------------------
# Test 11: Format for Prompt
# -----------------------------------------------------------------------------


def test_format_for_prompt():
    """
    Test the format_for_prompt method for system prompt injection.
    """
    print("\n" + "=" * 60)
    print("TEST 11: Format for Prompt")
    print("=" * 60)

    test_user = "prompt_test@example.com"

    # Add some memories
    store.add_memory(test_user, "User is a backend engineer")
    store.add_memory(test_user, "User prefers detailed explanations")
    store.add_memory(test_user, "User uses Rust and Go")

    # Get profile and format it
    profile = store.get(test_user)
    formatted = store.format_for_prompt(profile)

    print("\n📝 Formatted for system prompt:")
    print("-" * 40)
    print(formatted)
    print("-" * 40)

    # Should be XML formatted
    assert "<user_profile>" in formatted
    assert "</user_profile>" in formatted
    assert "backend engineer" in formatted

    print("\n✅ Format for prompt works")


# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------


def cleanup():
    """Wipe all test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    test_users = [
        USER_ALICE,
        USER_BOB,
        USER_CHARLIE,
        "tool_test@example.com",
        "direct_test@example.com",
        "ephemeral@example.com",
        "context_test@example.com",
        "work_only@example.com",
        "growing@example.com",
        "useful@example.com",
        "empty@example.com",
        "deep@example.com",
        "prompt_test@example.com",
    ]

    for user_id in test_users:
        try:
            store.delete(user_id)
            store.delete(user_id, agent_id="support_agent")
            store.delete(user_id, agent_id="sales_agent")
        except Exception:
            pass

    print("🧹 Cleaned")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("🧠 UserProfileStore Cookbook")
    print("   Testing memory that matters")
    print("=" * 60)

    # Run the tests you want
    test_manual_memory_addition()
    test_background_extraction()
    test_agent_tool()
    test_direct_update()
    test_delete_and_clear()
    test_entity_context()
    test_custom_instructions()
    test_incremental_update()
    test_state_tracking()
    test_deep_extraction()
    test_format_for_prompt()

    # Final summary
    print("\n" + "=" * 60)
    print("📊 FINAL STATE")
    print("=" * 60)

    for user_id in [USER_ALICE, USER_BOB, USER_CHARLIE]:
        profile = store.get(user_id)
        if profile and profile.memories:
            print(f"\n{user_id}:")
            for m in profile.memories[:3]:
                content = m.get("content", str(m))
                print(f"  • {content[:60]}{'...' if len(content) > 60 else ''}")

    cleanup()

    print("\n" + "=" * 60)
    print("✅ All tests complete")
    print("   Remember: it's not about storing data.")
    print("   It's about understanding people.")
    print("=" * 60)
