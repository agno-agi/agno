"""
Debugging LearningMachine
===========================================
How to inspect, troubleshoot, and debug learning issues.

Common problems:
- Memories not being saved
- Wrong data being extracted
- Learnings not being recalled
- Session context not updating

This cookbook shows how to diagnose and fix these issues.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="debug_learnings"),
)

# =============================================================================
# Create Agent with Debug Mode
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,
        user_profile=True,
        session_context=True,
        debug_mode=True,  # Enable debug logging!
    ),
    markdown=True,
    debug_mode=True,  # Agent-level debug too
)


# =============================================================================
# Debug Tool 1: Inspect LearningMachine State
# =============================================================================
def inspect_learning_machine():
    """Print the current state of LearningMachine."""
    print("=" * 60)
    print("LearningMachine State")
    print("=" * 60)

    lm = agent.learning

    # Basic info
    print(f"\nRepr: {lm}")

    # Stores
    print(f"\nStores: {list(lm.stores.keys())}")
    for name, store in lm.stores.items():
        print(f"  {name}: {store}")

    # Config
    print(f"\nDB: {lm.db}")
    print(f"Model: {lm.model}")
    print(f"Knowledge: {lm.knowledge}")


# =============================================================================
# Debug Tool 2: Inspect User Profile
# =============================================================================
def inspect_profile(user_id: str):
    """Deep inspection of a user profile."""
    print(f"\n{'=' * 60}")
    print(f"User Profile: {user_id}")
    print("=" * 60)

    store = agent.learning.stores.get("user_profile")
    if not store:
        print("❌ UserProfileStore not found!")
        return

    profile = store.get(user_id=user_id)

    if not profile:
        print(f"❌ No profile found for user_id={user_id}")
        print("\nPossible causes:")
        print("  - User hasn't interacted yet")
        print("  - Extraction failed")
        print("  - Wrong user_id")
        return

    print(f"\n✅ Profile found!")
    print(f"Type: {type(profile).__name__}")

    # Raw data
    if hasattr(profile, 'to_dict'):
        import json
        print(f"\nRaw data:\n{json.dumps(profile.to_dict(), indent=2, default=str)}")

    # Memories
    if hasattr(profile, 'memories'):
        print(f"\nMemories ({len(profile.memories)}):")
        for i, mem in enumerate(profile.memories):
            print(f"  {i+1}. {mem}")


# =============================================================================
# Debug Tool 3: Inspect Session Context
# =============================================================================
def inspect_session(session_id: str):
    """Deep inspection of session context."""
    print(f"\n{'=' * 60}")
    print(f"Session Context: {session_id}")
    print("=" * 60)

    store = agent.learning.stores.get("session_context")
    if not store:
        print("❌ SessionContextStore not found!")
        print("   Did you enable session_context=True?")
        return

    context = store.get(session_id=session_id)

    if not context:
        print(f"❌ No context found for session_id={session_id}")
        return

    print(f"\n✅ Context found!")
    print(f"Type: {type(context).__name__}")

    if hasattr(context, 'to_dict'):
        import json
        print(f"\nRaw data:\n{json.dumps(context.to_dict(), indent=2, default=str)}")


# =============================================================================
# Debug Tool 4: Inspect Learnings
# =============================================================================
def inspect_learnings(query: str = ""):
    """Inspect the learned knowledge store."""
    print(f"\n{'=' * 60}")
    print("Learned Knowledge Store")
    print("=" * 60)

    store = agent.learning.stores.get("learned_knowledge")
    if not store:
        print("❌ LearnedKnowledgeStore not found!")
        print("   Did you provide a knowledge base?")
        return

    print(f"\n✅ Store found: {store}")

    if query:
        print(f"\nSearching for: '{query}'")
        results = store.search(query=query, limit=10)
        print(f"Found: {len(results)} results")
        for i, r in enumerate(results):
            print(f"\n  {i+1}. {getattr(r, 'title', 'Untitled')}")
            print(f"     {getattr(r, 'learning', str(r))[:100]}...")


# =============================================================================
# Debug Tool 5: Test Extraction
# =============================================================================
def test_extraction(user_id: str, message: str):
    """Test if extraction is working."""
    print(f"\n{'=' * 60}")
    print("Testing Extraction")
    print("=" * 60)

    # Get profile before
    profile_before = agent.learning.stores["user_profile"].get(user_id=user_id)
    memories_before = len(profile_before.memories) if profile_before else 0

    print(f"Memories before: {memories_before}")
    print(f"Message: {message[:50]}...")

    # Send message
    agent.print_response(
        message,
        user_id=user_id,
        session_id="debug_session",
        stream=True,
    )

    # Get profile after
    profile_after = agent.learning.stores["user_profile"].get(user_id=user_id)
    memories_after = len(profile_after.memories) if profile_after else 0

    print(f"\nMemories after: {memories_after}")
    print(f"New memories: {memories_after - memories_before}")

    if memories_after > memories_before:
        print("✅ Extraction is working!")
        print("\nNew memories:")
        for mem in profile_after.memories[memories_before:]:
            print(f"  > {mem.get('content', mem)}")
    else:
        print("⚠️  No new memories extracted")
        print("\nPossible causes:")
        print("  - Message didn't contain extractable info")
        print("  - Mode is AGENTIC but agent didn't call tool")
        print("  - Extraction model failed")


# =============================================================================
# Debug Tool 6: Check Store Was Updated
# =============================================================================
def check_was_updated():
    """Check if last operation updated any stores."""
    print(f"\n{'=' * 60}")
    print("Update Check")
    print("=" * 60)

    lm = agent.learning

    print(f"\nLearningMachine.was_updated: {lm.was_updated}")

    for name, store in lm.stores.items():
        updated = getattr(store, 'was_updated', None)
        print(f"  {name}.was_updated: {updated}")


# =============================================================================
# Common Issues and Solutions
# =============================================================================
def show_troubleshooting_guide():
    """Print common issues and solutions."""
    print("""
================================================================================
TROUBLESHOOTING GUIDE
================================================================================

ISSUE: Memories not being saved
─────────────────────────────────────────────────────────────────────
Causes:
  1. Mode is AGENTIC but agent didn't call the tool
  2. Extraction model is failing silently
  3. Database connection issue

Solutions:
  1. Check mode: UserProfileConfig(mode=LearningMode.BACKGROUND)
  2. Enable debug_mode=True to see extraction logs
  3. Test DB: db.get_learning(learning_type="user_profile", user_id="test")


ISSUE: Wrong data being extracted
─────────────────────────────────────────────────────────────────────
Causes:
  1. Default extraction instructions don't match your needs
  2. Cheap model for extraction is too weak

Solutions:
  1. Customize: UserProfileConfig(instructions="Focus on X, Y, Z")
  2. Use better model: UserProfileConfig(model=better_model)


ISSUE: Learnings not being recalled
─────────────────────────────────────────────────────────────────────
Causes:
  1. Agent not calling search_learnings tool
  2. Semantic search not finding matches
  3. Learnings stored with wrong format

Solutions:
  1. Check agent instructions mention searching learnings
  2. Test search directly: store.search("your query", limit=10)
  3. Inspect stored learnings: inspect_learnings("query")


ISSUE: Session context not updating
─────────────────────────────────────────────────────────────────────
Causes:
  1. session_context not enabled
  2. Wrong session_id being passed
  3. Context getting replaced (expected behavior)

Solutions:
  1. Enable: LearningMachine(session_context=True)
  2. Check session_id is consistent across messages
  3. Remember: context is replaced, not appended
    """)


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("LearningMachine Debugging Tools")
    print("=" * 60)

    # 1. Inspect the learning machine
    inspect_learning_machine()

    # 2. Test extraction
    test_extraction(
        user_id="debug_user@example.com",
        message="Hi, I'm a debug user. I work as a software engineer at TestCorp. "
                "I specialize in Python and distributed systems."
    )

    # 3. Inspect the profile
    inspect_profile("debug_user@example.com")

    # 4. Inspect session
    inspect_session("debug_session")

    # 5. Check if stores were updated
    check_was_updated()

    # 6. Inspect learnings
    inspect_learnings("software engineering")

    # 7. Show troubleshooting guide
    show_troubleshooting_guide()
