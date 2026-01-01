"""
Learning Machine Cookbook
=========================

"The whole is greater than the sum of its parts." - Aristotle

This cookbook demonstrates the LearningMachine - the orchestrator that
coordinates all learning types into a unified system.

Three DX Levels:
1. Dead Simple: Just works with sensible defaults
2. Pick What You Want: Enable/disable specific learning types
3. Full Control: Custom configs for each learning type

Tests:
1. Dead simple setup - Just db and model
2. Pick what you want - Boolean toggles
3. Full control - Custom configs
4. Recall from all stores - Unified retrieval
5. Process through all stores - Unified extraction
6. Get tools from all stores - Aggregated tools
7. System prompt injection - Formatted context
8. State tracking - Know what changed
9. Custom stores - Extend with your own
10. Lifecycle hooks - Start/end conversation
11. Store access - Direct access to individual stores
"""

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from agno.db.postgres import PostgresDb
from agno.knowledge.text import TextKnowledge
from agno.learn import (
    KnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
    create_learning_machine,
)
from agno.learn.stores.base import LearningStore
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType
from rich.pretty import pprint

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    learnings_table="agno_learnings",
)
model = OpenAIChat(id="gpt-4o-mini")

# Knowledge base for semantic search
vector_db = LanceDb(
    uri="/tmp/agno_learning_machine_test",
    table_name="learnings",
    search_type=SearchType.hybrid,
)
knowledge_base = TextKnowledge(vector_db=vector_db)

# Test identifiers
TEST_USER = "learning_machine_test@example.com"
TEST_SESSION = "lm_session_001"


# -----------------------------------------------------------------------------
# Test 1: Dead Simple Setup
# -----------------------------------------------------------------------------


def test_dead_simple():
    """
    Level 1: Just provide db and model, everything else is defaults.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Dead Simple Setup")
    print("=" * 60)

    # Just db and model - that's it!
    learning = LearningMachine(
        db=db,
        model=model,
    )

    print(f"\n📋 Stores enabled: {list(learning.stores.keys())}")
    print(f"   user_profile: {learning.user_profile_store is not None}")
    print(f"   session_context: {learning.session_context_store is not None}")
    print(f"   knowledge: {learning.knowledge_store is not None}")

    # Defaults: user_profile=True, session_context=True, learned_knowledge=False
    assert learning.user_profile_store is not None
    assert learning.session_context_store is not None
    assert learning.knowledge_store is None  # Off by default

    print("\n✅ Dead simple setup works")


# -----------------------------------------------------------------------------
# Test 2: Pick What You Want
# -----------------------------------------------------------------------------


def test_pick_what_you_want():
    """
    Level 2: Use boolean toggles to enable/disable features.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Pick What You Want")
    print("=" * 60)

    # Only user profiles, nothing else
    learning_profiles_only = LearningMachine(
        db=db,
        model=model,
        user_profile=True,
        session_context=False,
        learned_knowledge=False,
    )
    print(f"\n📋 Profiles only: {list(learning_profiles_only.stores.keys())}")

    # Only session context
    learning_sessions_only = LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        session_context=True,
        learned_knowledge=False,
    )
    print(f"📋 Sessions only: {list(learning_sessions_only.stores.keys())}")

    # Everything enabled
    learning_all = LearningMachine(
        db=db,
        model=model,
        user_profile=True,
        session_context=True,
        learned_knowledge=True,
    )
    print(f"📋 All enabled: {list(learning_all.stores.keys())}")

    print("\n✅ Pick what you want works")


# -----------------------------------------------------------------------------
# Test 3: Full Control
# -----------------------------------------------------------------------------


def test_full_control():
    """
    Level 3: Custom configs for fine-grained control.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Full Control")
    print("=" * 60)

    learning = LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_tool=True,
            enable_add=True,
            enable_update=True,
            enable_delete=False,  # No deleting!
            instructions="Focus on technical preferences and expertise.",
        ),
        session_context=SessionContextConfig(
            enable_planning=True,  # Track goal/plan/progress
        ),
        learned_knowledge=KnowledgeConfig(
            knowledge=knowledge_base,
            mode=LearningMode.AGENTIC,
            enable_tool=True,
        ),
    )

    print(f"\n📋 Full control stores: {list(learning.stores.keys())}")

    # Verify configs were applied
    user_store = learning.user_profile_store
    if user_store:
        print(f"\n👤 User profile config:")
        print(f"   enable_tool: {user_store.config.enable_tool}")
        print(f"   enable_delete: {user_store.config.enable_delete}")

    session_store = learning.session_context_store
    if session_store:
        print(f"\n📋 Session context config:")
        print(f"   enable_planning: {session_store.config.enable_planning}")

    print("\n✅ Full control works")


# -----------------------------------------------------------------------------
# Test 4: Recall from All Stores
# -----------------------------------------------------------------------------


def test_recall():
    """
    Unified retrieval from all stores at once.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Recall from All Stores")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model)

    # Add some test data
    user_store = learning.user_profile_store
    if user_store:
        user_store.add_memory(user_id=TEST_USER, memory="User is a Python developer")
        user_store.add_memory(user_id=TEST_USER, memory="User works on ML projects")

    # Recall everything
    results = learning.recall(
        user_id=TEST_USER,
        session_id=TEST_SESSION,
        message="How do I optimize my code?",
    )

    print(f"\n📋 Recall results:")
    for name, data in results.items():
        print(f"   {name}: {type(data).__name__}")
        if hasattr(data, "to_dict"):
            pprint(data.to_dict())

    print("\n✅ Recall works")


# -----------------------------------------------------------------------------
# Test 5: Process Through All Stores
# -----------------------------------------------------------------------------


def test_process():
    """
    Unified extraction through all stores.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Process Through All Stores")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model)

    # Messages to process
    messages = [
        Message(role="user", content="Hi, I'm a backend engineer at Stripe."),
        Message(role="assistant", content="Nice to meet you! What can I help with?"),
        Message(role="user", content="I need to optimize our payment processing API."),
        Message(
            role="assistant",
            content="Let's work on that. What's the current bottleneck?",
        ),
    ]

    # Process through all stores
    learning.process(
        messages=messages,
        user_id=TEST_USER,
        session_id=TEST_SESSION,
    )

    print(f"\n📝 Processing complete")
    print(f"   profile_updated: {learning.profile_updated}")
    print(f"   context_updated: {learning.context_updated}")
    print(f"   was_updated: {learning.was_updated}")

    # Check what was extracted
    results = learning.recall(user_id=TEST_USER, session_id=TEST_SESSION)
    print(f"\n📋 After processing:")
    for name, data in results.items():
        print(f"\n   {name}:")
        if hasattr(data, "to_dict"):
            pprint(data.to_dict())

    print("\n✅ Process works")


# -----------------------------------------------------------------------------
# Test 6: Get Tools from All Stores
# -----------------------------------------------------------------------------


def test_get_tools():
    """
    Aggregate tools from all stores for agent use.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Get Tools from All Stores")
    print("=" * 60)

    learning = LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(enable_tool=True),
        session_context=True,  # Session has no tools
        learned_knowledge=KnowledgeConfig(
            knowledge=knowledge_base,
            enable_tool=True,
        ),
    )

    tools = learning.get_tools(user_id=TEST_USER)

    print(f"\n🔧 Tools available: {len(tools)}")
    for tool in tools:
        print(
            f"   - {tool.__name__}: {tool.__doc__[:50] if tool.__doc__ else 'No doc'}..."
        )

    # Should have: update_user_memory, save_learning
    # Session context has NO agent tools
    assert len(tools) >= 1  # At least user profile tool

    print("\n✅ Get tools works")


# -----------------------------------------------------------------------------
# Test 7: System Prompt Injection
# -----------------------------------------------------------------------------


def test_system_prompt_injection():
    """
    Get formatted learnings for system prompt injection.
    """
    print("\n" + "=" * 60)
    print("TEST 7: System Prompt Injection")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model)

    # Make sure we have some data
    user_store = learning.user_profile_store
    if user_store:
        user_store.add_memory(user_id=TEST_USER, memory="User prefers concise answers")

    # Get formatted injection
    injection = learning.get_system_prompt_injection(
        user_id=TEST_USER,
        session_id=TEST_SESSION,
        message="Help me with Python",
    )

    print(f"\n📝 System prompt injection:")
    print("-" * 40)
    print(injection if injection else "(empty)")
    print("-" * 40)

    if injection:
        # Should have XML tags
        assert "<user_profile>" in injection or "<session_context>" in injection

    print("\n✅ System prompt injection works")


# -----------------------------------------------------------------------------
# Test 8: State Tracking
# -----------------------------------------------------------------------------


def test_state_tracking():
    """
    Track what was updated across all stores.
    """
    print("\n" + "=" * 60)
    print("TEST 8: State Tracking")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model)

    # Process some messages
    messages = [
        Message(role="user", content="I'm learning Rust and enjoying it."),
    ]

    learning.process(
        messages=messages,
        user_id="state_test@example.com",
        session_id="state_session",
    )

    print(f"\n📊 State after processing:")
    print(f"   profile_updated: {learning.profile_updated}")
    print(f"   context_updated: {learning.context_updated}")
    print(f"   learning_saved: {learning.learning_saved}")
    print(f"   was_updated (any): {learning.was_updated}")

    # Cleanup
    if learning.user_profile_store:
        learning.user_profile_store.delete(user_id="state_test@example.com")
    if learning.session_context_store:
        learning.session_context_store.delete(session_id="state_session")

    print("\n✅ State tracking works")


# -----------------------------------------------------------------------------
# Test 9: Custom Stores
# -----------------------------------------------------------------------------


def test_custom_stores():
    """
    Extend with your own custom stores.
    """
    print("\n" + "=" * 60)
    print("TEST 9: Custom Stores")
    print("=" * 60)

    # Define a simple custom store
    @dataclass
    class ProjectContextStore(LearningStore):
        """Example custom store for project context."""

        project_data: dict = field(default_factory=dict)

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

        def format_for_prompt(self, data: Any) -> str:
            if not data:
                return ""
            return f"<project_context>\n{data}\n</project_context>"

        def get_tools(self, **kwargs) -> List[Callable]:
            return []

        async def aget_tools(self, **kwargs) -> List[Callable]:
            return []

        @property
        def was_updated(self) -> bool:
            return False

        # Custom method
        def set_project(self, project_id: str, data: dict) -> None:
            self.project_data[project_id] = data

    # Register at creation
    project_store = ProjectContextStore()
    project_store.set_project("proj_123", {"name": "ML Pipeline", "status": "active"})

    learning = LearningMachine(
        db=db,
        model=model,
        custom_stores={"project": project_store},
    )

    print(f"\n📋 Stores with custom: {list(learning.stores.keys())}")
    assert "project" in learning.stores

    # Or register dynamically
    another_store = ProjectContextStore()
    learning.register(name="another_project", store=another_store)
    print(f"📋 After dynamic register: {list(learning.stores.keys())}")

    # Recall includes custom stores
    results = learning.recall(
        user_id=TEST_USER,
        project_id="proj_123",  # Custom param for custom store
    )
    print(f"\n📋 Recall with custom store:")
    for name, data in results.items():
        print(f"   {name}: {data}")

    print("\n✅ Custom stores work")


# -----------------------------------------------------------------------------
# Test 10: Lifecycle Hooks
# -----------------------------------------------------------------------------


def test_lifecycle_hooks():
    """
    Hooks for conversation start/end.
    """
    print("\n" + "=" * 60)
    print("TEST 10: Lifecycle Hooks")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model)

    # Conversation start
    learning.on_conversation_start(
        user_id=TEST_USER,
        session_id=TEST_SESSION,
    )
    print("\n📍 on_conversation_start called")

    # ... conversation happens ...
    messages = [
        Message(role="user", content="Help me with my project"),
        Message(role="assistant", content="Sure! What's the project?"),
    ]

    # Conversation end
    learning.on_conversation_end(
        user_id=TEST_USER,
        session_id=TEST_SESSION,
        messages=messages,
    )
    print("📍 on_conversation_end called")

    print("\n✅ Lifecycle hooks work")


# -----------------------------------------------------------------------------
# Test 11: Store Access
# -----------------------------------------------------------------------------


def test_store_access():
    """
    Direct access to individual stores.
    """
    print("\n" + "=" * 60)
    print("TEST 11: Store Access")
    print("=" * 60)

    learning = LearningMachine(
        db=db,
        model=model,
        user_profile=True,
        session_context=True,
        learned_knowledge=KnowledgeConfig(knowledge=knowledge_base),
    )

    # Property access
    print(f"\n📋 Store access:")
    print(f"   user_profile_store: {type(learning.user_profile_store).__name__}")
    print(f"   session_context_store: {type(learning.session_context_store).__name__}")
    print(f"   knowledge_store: {type(learning.knowledge_store).__name__}")

    # Get by name
    user_store = learning.get_store("user_profile")
    print(f"\n📋 get_store('user_profile'): {type(user_store).__name__}")

    # Direct operations on stores
    if user_store:
        user_store.add_memory(
            user_id="direct_access@test.com", memory="Direct access test"
        )
        profile = user_store.get(user_id="direct_access@test.com")
        print(f"📋 Direct add_memory result: {profile.memories if profile else None}")

        # Cleanup
        user_store.delete(user_id="direct_access@test.com")

    print("\n✅ Store access works")


# -----------------------------------------------------------------------------
# Test 12: Factory Function
# -----------------------------------------------------------------------------


def test_factory_function():
    """
    Use the factory function for creation.
    """
    print("\n" + "=" * 60)
    print("TEST 12: Factory Function")
    print("=" * 60)

    # Factory function mirrors constructor
    learning = create_learning_machine(
        db=db,
        model=model,
        user_profile=True,
        session_context=True,
        learned_knowledge=False,
        debug_mode=False,
    )

    print(f"\n📋 Created via factory: {list(learning.stores.keys())}")
    assert isinstance(learning, LearningMachine)

    print("\n✅ Factory function works")


# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    learning = LearningMachine(db=db, model=model)

    # Clean user profiles
    if learning.user_profile_store:
        learning.user_profile_store.delete(user_id=TEST_USER)
        learning.user_profile_store.delete(user_id="state_test@example.com")

    # Clean session contexts
    if learning.session_context_store:
        learning.session_context_store.delete(session_id=TEST_SESSION)
        learning.session_context_store.delete(session_id="state_session")

    print("🧹 Cleaned")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("🧠 LearningMachine Cookbook")
    print("   The whole is greater than the sum of its parts")
    print("=" * 60)

    # Run tests
    test_dead_simple()
    test_pick_what_you_want()
    test_full_control()
    test_recall()
    test_process()
    test_get_tools()
    test_system_prompt_injection()
    test_state_tracking()
    test_custom_stores()
    test_lifecycle_hooks()
    test_store_access()
    test_factory_function()

    # Cleanup
    cleanup()

    print("\n" + "=" * 60)
    print("✅ All tests complete")
    print("   Three DX levels:")
    print("   1. Dead Simple: LearningMachine(db=db, model=model)")
    print("   2. Pick What You Want: user_profile=True, session_context=False")
    print("   3. Full Control: UserProfileConfig(enable_tool=True, ...)")
    print("=" * 60)
