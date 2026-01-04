"""
LearningMachine — The Orchestrator
===================================
Deep dive into LearningMachine, the coordinator for all learning stores.

This cookbook demonstrates:
1. Three DX levels (Dead Simple → Pick What You Want → Full Control)
2. Lazy initialization
3. __repr__ for debugging
4. build_context() — Unified retrieval
5. get_tools() — Aggregated tools
6. process() — Unified extraction
7. recall() — Low-level access
8. was_updated — State tracking
9. Custom stores registration

Run this example:
    python cookbook/learning/03_learning_machine.py
"""

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearningsConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.stores.protocol import LearningStore
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType
from rich.pretty import pprint

# =============================================================================
# Setup
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o-mini")

# Knowledge base for learnings
knowledge = Knowledge(
    name="Learning Machine Test KB",
    vector_db=PgVector(
        db_url=db_url,
        table_name="learning_machine_test",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Test identifiers
TEST_USER = "lm_test_user@example.com"
TEST_SESSION = "lm_test_session_001"


# =============================================================================
# Test 1: DX Level 1 — Dead Simple
# =============================================================================


def test_dead_simple():
    """
    Level 1: Just provide knowledge, everything auto-configures.

    When you provide `knowledge`, LearningMachine automatically:
    - Enables UserProfileStore (BACKGROUND mode, tool enabled)
    - Enables SessionContextStore (summary only)
    - Enables LearningsStore (AGENTIC mode)
    """
    print("\n" + "=" * 60)
    print("TEST 1: DX Level 1 — Dead Simple")
    print("=" * 60)

    # This is ALL you need!
    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,  # Auto-enables learnings
    )

    print(f"\n📋 Stores enabled: {list(learning.stores.keys())}")
    print("\n📊 Full representation:")
    print(f"   {learning}")

    # Verify all three stores are enabled
    assert "user_profile" in learning.stores, "user_profile should be enabled"
    assert "session_context" in learning.stores, "session_context should be enabled"
    assert "learnings" in learning.stores, "learnings should be auto-enabled"

    print("\n✅ Dead simple setup works — just provide knowledge!")


# =============================================================================
# Test 2: DX Level 2 — Pick What You Want
# =============================================================================


def test_pick_what_you_want():
    """
    Level 2: Use boolean toggles to enable/disable specific stores.
    """
    print("\n" + "=" * 60)
    print("TEST 2: DX Level 2 — Pick What You Want")
    print("=" * 60)

    # Only user profiles
    learning_profiles = LearningMachine(
        db=db,
        model=model,
        user_profile=True,
        session_context=False,
        learnings=False,
    )
    print(f"\n📋 Profiles only: {list(learning_profiles.stores.keys())}")

    # Only session context
    learning_sessions = LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        session_context=True,
        learnings=False,
    )
    print(f"📋 Sessions only: {list(learning_sessions.stores.keys())}")

    # Profiles + Learnings (no session context)
    learning_no_session = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=True,
        session_context=False,
        learnings=True,
    )
    print(f"📋 No session context: {list(learning_no_session.stores.keys())}")

    print("\n✅ Boolean toggles work!")


# =============================================================================
# Test 3: DX Level 3 — Full Control
# =============================================================================


def test_full_control():
    """
    Level 3: Custom configs for fine-grained control over each store.
    """
    print("\n" + "=" * 60)
    print("TEST 3: DX Level 3 — Full Control")
    print("=" * 60)

    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        # User Profile: AGENTIC mode, tool enabled, custom instructions
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            enable_tool=True,
            enable_delete=False,  # Don't allow deletions
            instructions="Focus only on professional information.",
        ),
        # Session Context: Enable planning mode
        session_context=SessionContextConfig(
            enable_planning=True,  # Track goal, plan, progress
        ),
        # Learnings: PROPOSE mode
        learnings=LearningsConfig(
            mode=LearningMode.PROPOSE,
            enable_tool=True,
            enable_search=True,
        ),
    )

    print(f"\n📋 Stores: {list(learning.stores.keys())}")
    print("\n📊 Store configurations:")
    for name, store in learning.stores.items():
        print(f"   {name}: {store}")

    print("\n✅ Full control works!")


# =============================================================================
# Test 4: Lazy Initialization
# =============================================================================


def test_lazy_initialization():
    """
    Stores are initialized on first access, not at construction.
    This avoids overhead when stores aren't used.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Lazy Initialization")
    print("=" * 60)

    # Create the LearningMachine
    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
    )

    # Check internal state BEFORE accessing stores
    print("\n📋 Before accessing stores:")
    print(f"   _stores is None: {learning._stores is None}")

    # Access stores (triggers initialization)
    stores = learning.stores

    # Check internal state AFTER accessing stores
    print("\n📋 After accessing stores:")
    print(f"   _stores is None: {learning._stores is None}")
    print(f"   Store count: {len(stores)}")

    print("\n✅ Lazy initialization works!")


# =============================================================================
# Test 5: __repr__ for Debugging
# =============================================================================


def test_repr():
    """
    All stores and LearningMachine have __repr__ for easy debugging.
    """
    print("\n" + "=" * 60)
    print("TEST 5: __repr__ for Debugging")
    print("=" * 60)

    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        session_context=SessionContextConfig(enable_planning=True),
        learnings=LearningsConfig(mode=LearningMode.PROPOSE),
    )

    print("\n📊 LearningMachine repr:")
    print(f"   {learning}")

    print("\n📊 Individual store reprs:")
    for name, store in learning.stores.items():
        print(f"   {name}: {store}")

    print("\n✅ __repr__ works for debugging!")


# =============================================================================
# Test 6: build_context() — Unified Retrieval
# =============================================================================


def test_build_context():
    """
    build_context() retrieves from all stores and formats for system prompt.
    """
    print("\n" + "=" * 60)
    print("TEST 6: build_context() — Unified Retrieval")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model, knowledge=knowledge)

    # Add some test data first
    user_store = learning.stores.get("user_profile")
    if user_store and hasattr(user_store, "add_memory"):
        user_store.add_memory(TEST_USER, "User is a Python developer")
        user_store.add_memory(TEST_USER, "User prefers concise answers")

    # Build context
    context = learning.build_context(
        user_id=TEST_USER,
        session_id=TEST_SESSION,
        message="How do I optimize a pandas DataFrame?",
    )

    print(f"\n📝 Built context ({len(context)} chars):")
    print("-" * 40)
    if context:
        # Show first 500 chars
        print(context[:500] + ("..." if len(context) > 500 else ""))
    else:
        print("(empty context)")
    print("-" * 40)

    print("\n✅ build_context() works!")


# =============================================================================
# Test 7: get_tools() — Aggregated Tools
# =============================================================================


def test_get_tools():
    """
    get_tools() aggregates tools from all stores.
    """
    print("\n" + "=" * 60)
    print("TEST 7: get_tools() — Aggregated Tools")
    print("=" * 60)

    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=UserProfileConfig(enable_tool=True),
        learnings=LearningsConfig(enable_tool=True, enable_search=True),
    )

    tools = learning.get_tools(user_id=TEST_USER)

    print(f"\n🔧 Tools available ({len(tools)}):")
    for tool in tools:
        name = getattr(tool, "__name__", str(tool))
        doc = getattr(tool, "__doc__", "")
        doc_preview = doc.split("\n")[0][:50] if doc else "No description"
        print(f"   - {name}: {doc_preview}...")

    print("\n✅ get_tools() works!")


# =============================================================================
# Test 8: process() — Unified Extraction
# =============================================================================


def test_process():
    """
    process() extracts and saves learnings from a conversation.
    """
    print("\n" + "=" * 60)
    print("TEST 8: process() — Unified Extraction")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model, knowledge=knowledge)

    # Simulate a conversation
    messages = [
        Message(role="user", content="Hi, I'm Alex, a DevOps engineer at Shopify."),
        Message(role="assistant", content="Nice to meet you, Alex! How can I help?"),
        Message(
            role="user",
            content="I'm optimizing our CI/CD pipeline. We use GitHub Actions.",
        ),
        Message(role="assistant", content="Great! What's the current bottleneck?"),
        Message(
            role="user",
            content="Docker builds are slow. I prefer parallel builds when possible.",
        ),
    ]

    print(f"\n📝 Processing {len(messages)} messages...")

    # Process through all stores
    learning.process(
        messages=messages,
        user_id="process_test@example.com",
        session_id="process_session",
    )

    print(f"🔄 was_updated: {learning.was_updated}")

    # Check what was extracted
    user_store = learning.stores.get("user_profile")
    if user_store:
        profile = user_store.recall(user_id="process_test@example.com")
        if profile:
            print("\n📋 Extracted user profile:")
            pprint(profile.to_dict() if hasattr(profile, "to_dict") else profile)

    print("\n✅ process() works!")


# =============================================================================
# Test 9: recall() — Low-Level Access
# =============================================================================


def test_recall():
    """
    recall() returns raw data from all stores (for debugging/advanced use).
    """
    print("\n" + "=" * 60)
    print("TEST 9: recall() — Low-Level Access")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model, knowledge=knowledge)

    # Add test data
    user_store = learning.stores.get("user_profile")
    if user_store and hasattr(user_store, "add_memory"):
        user_store.add_memory("recall_test@example.com", "User likes TypeScript")

    # Recall from all stores
    results = learning.recall(
        user_id="recall_test@example.com",
        session_id="recall_session",
        message="What's the best way to type APIs?",
    )

    print(f"\n📋 Recall results ({len(results)} stores):")
    for name, data in results.items():
        data_type = type(data).__name__
        print(f"   {name}: {data_type}")
        if hasattr(data, "to_dict"):
            pprint(data.to_dict())

    print("\n✅ recall() works!")


# =============================================================================
# Test 10: was_updated — State Tracking
# =============================================================================


def test_was_updated():
    """
    was_updated property tracks if any store changed.
    """
    print("\n" + "=" * 60)
    print("TEST 10: was_updated — State Tracking")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model, knowledge=knowledge)

    # Message with useful info
    messages_useful = [
        Message(role="user", content="I'm Grace, a mobile developer at Uber."),
        Message(role="assistant", content="Hi Grace! What are you working on?"),
    ]

    learning.process(
        messages=messages_useful,
        user_id="state_test@example.com",
        session_id="state_session",
    )
    print(f"\n📝 After useful messages: was_updated = {learning.was_updated}")

    # Message with nothing to extract
    messages_empty = [
        Message(role="user", content="What time is it?"),
        Message(role="assistant", content="I don't have access to the current time."),
    ]

    learning.process(
        messages=messages_empty,
        user_id="state_empty@example.com",
        session_id="state_session_2",
    )
    print(f"📝 After empty messages: was_updated = {learning.was_updated}")

    print("\n✅ was_updated works!")


# =============================================================================
# Test 11: Custom Stores
# =============================================================================


def test_custom_stores():
    """
    Register custom stores that implement the LearningStore protocol.
    """
    print("\n" + "=" * 60)
    print("TEST 11: Custom Stores")
    print("=" * 60)

    # Define a simple custom store
    @dataclass
    class ProjectContextStore(LearningStore):
        """Custom store for project-specific context."""

        project_data: dict = field(default_factory=dict)
        _updated: bool = field(default=False, init=False)

        @property
        def learning_type(self) -> str:
            return "project_context"

        def recall(self, project_id: Optional[str] = None, **kwargs) -> Optional[dict]:
            if project_id:
                return self.project_data.get(project_id)
            return None

        async def arecall(self, **kwargs) -> Optional[dict]:
            return self.recall(**kwargs)

        def process(self, **kwargs) -> None:
            pass

        async def aprocess(self, **kwargs) -> None:
            pass

        def build_context(self, data: Any) -> str:
            if not data:
                return ""
            return f"<project_context>\nProject: {data.get('name', 'Unknown')}\nStatus: {data.get('status', 'Unknown')}\n</project_context>"

        def get_tools(self, **kwargs) -> List[Callable]:
            return []

        async def aget_tools(self, **kwargs) -> List[Callable]:
            return []

        @property
        def was_updated(self) -> bool:
            return self._updated

        # Custom method
        def set_project(self, project_id: str, data: dict) -> None:
            self.project_data[project_id] = data
            self._updated = True

        def __repr__(self) -> str:
            return f"ProjectContextStore(projects={len(self.project_data)})"

    # Create and populate custom store
    project_store = ProjectContextStore()
    project_store.set_project("proj_123", {"name": "ML Pipeline", "status": "active"})
    project_store.set_project("proj_456", {"name": "Data Lake", "status": "planning"})

    # Register with LearningMachine
    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        custom_stores={"project": project_store},
    )

    print(f"\n📋 Stores (including custom): {list(learning.stores.keys())}")

    # Recall with custom parameter
    results = learning.recall(
        user_id=TEST_USER,
        project_id="proj_123",
    )

    print("\n📋 Recall with project_id:")
    for name, data in results.items():
        print(f"   {name}: {data}")

    # Build context includes custom store
    context = learning.build_context(
        user_id=TEST_USER,
        project_id="proj_123",
    )
    print("\n📝 Context includes project:")
    print(context[:300] if context else "(empty)")

    print("\n✅ Custom stores work!")


# =============================================================================
# Cleanup
# =============================================================================


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model)

    test_users = [
        TEST_USER,
        "process_test@example.com",
        "recall_test@example.com",
        "state_test@example.com",
        "state_empty@example.com",
    ]

    user_store = learning.stores.get("user_profile")
    session_store = learning.stores.get("session_context")

    if user_store and hasattr(user_store, "delete"):
        for user_id in test_users:
            try:
                user_store.delete(user_id=user_id)
            except Exception:
                pass

    if session_store and hasattr(session_store, "delete"):
        for session_id in [
            TEST_SESSION,
            "process_session",
            "recall_session",
            "state_session",
            "state_session_2",
        ]:
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
    print("🧠 LearningMachine — The Orchestrator")
    print("=" * 60)

    # Run all tests
    test_dead_simple()
    test_pick_what_you_want()
    test_full_control()
    test_lazy_initialization()
    test_repr()
    test_build_context()
    test_get_tools()
    test_process()
    test_recall()
    test_was_updated()
    test_custom_stores()

    # Cleanup
    cleanup()

    # Summary
    print("\n" + "=" * 60)
    print("✅ All tests complete!")
    print("=" * 60)
    print("""
Key takeaways:

1. **DX Level 1**: LearningMachine(knowledge=kb)
   → Auto-enables all stores

2. **DX Level 2**: user_profile=True, session_context=False
   → Boolean toggles

3. **DX Level 3**: UserProfileConfig(mode=AGENTIC, ...)
   → Full control

4. **Lazy Init**: Stores created on first access
   → No overhead if unused

5. **Main API**:
   → build_context() for system prompt
   → get_tools() for agent tools
   → process() for extraction
   → recall() for debugging
""")
