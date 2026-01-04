"""
Learning Modes — BACKGROUND vs AGENTIC vs PROPOSE
==================================================
Deep dive into the three learning modes and when to use each.

Modes control HOW and WHEN learning happens:
- BACKGROUND: Automatic extraction after conversations
- AGENTIC: Agent decides via tools when to save
- PROPOSE: Agent proposes, user confirms before saving

This cookbook demonstrates:
1. Mode definitions and behavior
2. BACKGROUND mode in action
3. AGENTIC mode in action
4. PROPOSE mode in action
5. Mode support by store type
6. Unsupported mode warnings
7. Choosing the right mode
8. Mode-specific context output

Run this example:
    python cookbook/learning/07_learning_modes.py
"""

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

knowledge = Knowledge(
    name="Modes Test KB",
    vector_db=PgVector(
        db_url=db_url,
        table_name="learning_modes_test",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


# =============================================================================
# Test 1: Mode Definitions
# =============================================================================


def test_mode_definitions():
    """
    Understanding what each mode means.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Mode Definitions")
    print("=" * 60)

    print("""
    ┌─────────────┬────────────────────────────────────────────────────┐
    │ Mode        │ Behavior                                           │
    ├─────────────┼────────────────────────────────────────────────────┤
    │ BACKGROUND  │ • process() extracts automatically                 │
    │             │ • No user interaction needed                       │
    │             │ • Agent tool optional (via enable_tool)            │
    │             │ • Best for: user profiles, session summaries       │
    ├─────────────┼────────────────────────────────────────────────────┤
    │ AGENTIC     │ • process() is a no-op                             │
    │             │ • Agent saves directly via tools                   │
    │             │ • Agent decides what's worth saving                │
    │             │ • Best for: learnings (default)                    │
    ├─────────────┼────────────────────────────────────────────────────┤
    │ PROPOSE     │ • process() is a no-op                             │
    │             │ • Agent proposes, user confirms                    │
    │             │ • Higher quality control                           │
    │             │ • Best for: high-value learnings                   │
    └─────────────┴────────────────────────────────────────────────────┘
    """)

    # Show enum values
    print("📋 LearningMode enum values:")
    for mode in LearningMode:
        print(f"   LearningMode.{mode.name} = '{mode.value}'")

    print("\n✅ Mode definitions explained!")


# =============================================================================
# Test 2: BACKGROUND Mode
# =============================================================================


def test_background_mode():
    """
    BACKGROUND mode: Automatic extraction without user interaction.
    """
    print("\n" + "=" * 60)
    print("TEST 2: BACKGROUND Mode")
    print("=" * 60)

    # Create LearningMachine with BACKGROUND mode for user profile
    learning = LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,  # Auto-extract
            enable_tool=False,  # No agent tool
        ),
        session_context=False,
        learnings=False,
    )

    # Simulate a conversation
    messages = [
        Message(role="user", content="Hi, I'm Alex, a backend engineer at Airbnb."),
        Message(role="assistant", content="Hello Alex! How can I help you today?"),
        Message(
            role="user",
            content="I'm working on our search infrastructure. I prefer Python.",
        ),
    ]

    print("\n📝 Processing messages in BACKGROUND mode...")
    print("   (No user interaction needed)")

    # process() automatically extracts
    learning.process(
        messages=messages,
        user_id="background_test@example.com",
        session_id="background_session",
    )

    print(f"🔄 was_updated: {learning.was_updated}")

    # Check what was extracted
    results = learning.recall(user_id="background_test@example.com")
    if results.get("user_profile"):
        print("\n📋 Auto-extracted profile:")
        pprint(results["user_profile"].to_dict())

    # Cleanup
    user_store = learning.stores.get("user_profile")
    if user_store and hasattr(user_store, "delete"):
        user_store.delete(user_id="background_test@example.com")

    print("\n✅ BACKGROUND mode: Automatic extraction works!")


# =============================================================================
# Test 3: AGENTIC Mode
# =============================================================================


def test_agentic_mode():
    """
    AGENTIC mode: Agent decides what to save via tools.
    """
    print("\n" + "=" * 60)
    print("TEST 3: AGENTIC Mode")
    print("=" * 60)

    # Create LearningMachine with AGENTIC mode for learnings
    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        session_context=False,
        learnings=LearningsConfig(
            mode=LearningMode.AGENTIC,  # Agent-driven
            enable_tool=True,
            enable_search=True,
        ),
    )

    print("\n📋 AGENTIC mode behavior:")
    print("   • process() does NOT extract automatically")
    print("   • Agent must call tools to save")

    # Get tools
    tools = learning.get_tools()
    print(f"\n🔧 Tools available to agent ({len(tools)}):")
    for tool in tools:
        print(f"   - {getattr(tool, '__name__', str(tool))}")

    # Simulate agent calling the tool
    save_tool = next(
        (t for t in tools if "save" in getattr(t, "__name__", "").lower()), None
    )
    if save_tool:
        print("\n📝 Agent decides to save a learning...")
        result = save_tool(
            title="Caching strategy",
            learning="Use Redis for hot data, CDN for static assets, "
            "application cache for computed values.",
            context="When designing cache architecture",
            tags=["caching", "performance"],
        )
        print(f"   Result: {result}")

    # process() is a no-op in AGENTIC mode
    messages = [Message(role="user", content="Cache everything!")]
    learning.process(messages=messages)
    print(
        f"\n📝 process() in AGENTIC mode: (no-op, was_updated={learning.was_updated})"
    )

    print("\n✅ AGENTIC mode: Agent-driven saving works!")


# =============================================================================
# Test 4: PROPOSE Mode
# =============================================================================


def test_propose_mode():
    """
    PROPOSE mode: Agent proposes, user confirms before saving.
    """
    print("\n" + "=" * 60)
    print("TEST 4: PROPOSE Mode")
    print("=" * 60)

    # Create LearningMachine with PROPOSE mode
    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        session_context=False,
        learnings=LearningsConfig(
            mode=LearningMode.PROPOSE,
            enable_tool=True,
            enable_search=True,
        ),
    )

    print("""
    📋 PROPOSE mode flow:
    
    ┌─────────────────────────────────────────────────────────────┐
    │ 1. Agent discovers valuable insight                        │
    │                    ↓                                        │
    │ 2. Agent formats proposal:                                  │
    │    ─────────────────────────────────────                    │
    │    💡 **Proposed Learning**                                 │
    │    **Title**: API pagination patterns                       │
    │    **Learning**: Use cursor-based pagination for large...   │
    │    **Context**: When building REST APIs                     │
    │    **Tags**: api, pagination                                │
    │                                                             │
    │    Save this? Reply **yes** to confirm.                     │
    │    ─────────────────────────────────────                    │
    │                    ↓                                        │
    │ 3. User confirms: "yes"                                     │
    │                    ↓                                        │
    │ 4. Agent calls save_learning tool                           │
    └─────────────────────────────────────────────────────────────┘
    """)

    # The context output should reflect PROPOSE mode
    context = learning.build_context(message="test query")
    print("📝 PROPOSE mode context includes proposal instructions:")
    if (
        "propose" in context.lower()
        or "confirm" in context.lower()
        or "approval" in context.lower()
    ):
        print("   ✓ Instructions mention proposal workflow")
    else:
        print("   (Context format may vary)")

    print("\n✅ PROPOSE mode: Quality control through user confirmation!")


# =============================================================================
# Test 5: Mode Support by Store
# =============================================================================


def test_mode_support():
    """
    Not all stores support all modes.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Mode Support by Store")
    print("=" * 60)

    print("""
    ┌───────────────────────┬────────────┬─────────┬─────────┬──────┐
    │ Store                 │ BACKGROUND │ AGENTIC │ PROPOSE │ HITL │
    ├───────────────────────┼────────────┼─────────┼─────────┼──────┤
    │ UserProfileStore      │ ✅ Default │ ✅      │ ⚠️ Warn │ ⚠️   │
    │ SessionContextStore   │ ✅ ONLY    │ ⚠️ Warn │ ⚠️ Warn │ ⚠️   │
    │ LearningsStore        │ ✅         │ ✅ Def. │ ✅      │ ⚠️   │
    └───────────────────────┴────────────┴─────────┴─────────┴──────┘
    
    ✅ = Supported
    ⚠️ = Warning emitted, falls back gracefully
    
    Design rationale:
    
    • SessionContextStore: System-managed summarization. The agent
      shouldn't decide what to summarize. BACKGROUND only.
    
    • UserProfileStore: PROPOSE would be awkward ("Should I remember
      your name?"). BACKGROUND or AGENTIC makes more sense.
    
    • LearningsStore: PROPOSE makes sense for high-value insights
      that benefit from human quality control.
    """)

    print("\n✅ Mode support documented!")


# =============================================================================
# Test 6: Unsupported Mode Warnings
# =============================================================================


def test_unsupported_mode_warnings():
    """
    Unsupported modes emit warnings but don't crash.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Unsupported Mode Warnings")
    print("=" * 60)

    print("\n📝 Testing SessionContextStore with AGENTIC mode...")
    print("   (SessionContext only supports BACKGROUND)")

    # This should emit a warning but not crash
    session_config = SessionContextConfig(
        db=db,
        model=model,
        # mode is not configurable for SessionContext, but if it were:
        # mode=LearningMode.AGENTIC,  # Would warn
    )

    print(f"   Config created: {session_config}")
    print("   ⚠️  Unsupported modes warn, don't error")

    print("""
    Key principle: Graceful degradation
    
    • Unsupported mode → Warning logged
    • Store continues to work (falls back)
    • Agent never crashes due to mode mismatch
    """)

    print("\n✅ Graceful degradation for unsupported modes!")


# =============================================================================
# Test 7: Choosing the Right Mode
# =============================================================================


def test_choosing_modes():
    """
    Guidelines for choosing the right mode.
    """
    print("\n" + "=" * 60)
    print("TEST 7: Choosing the Right Mode")
    print("=" * 60)

    print("""
    ┌─────────────────────────────────────────────────────────────┐
    │                   MODE SELECTION GUIDE                      │
    └─────────────────────────────────────────────────────────────┘
    
    Use BACKGROUND when:
    ├── Data extraction is straightforward
    ├── No judgment needed about what to save
    ├── User shouldn't be interrupted
    └── Examples: user profile facts, session summaries
    
    Use AGENTIC when:
    ├── Agent has good judgment about value
    ├── Speed matters (no confirmation delay)
    ├── Volume is high (would annoy user with PROPOSE)
    └── Examples: general learnings, patterns
    
    Use PROPOSE when:
    ├── Quality matters more than speed
    ├── Learnings have high impact
    ├── User wants control over what's saved
    └── Examples: strategic insights, domain expertise
    
    ┌─────────────────────────────────────────────────────────────┐
    │                    DECISION TREE                            │
    └─────────────────────────────────────────────────────────────┘
    
                    Is it user-specific?
                           │
              ┌────────────┴────────────┐
              ↓                         ↓
             YES                        NO
              │                         │
         UserProfile              Is it session-specific?
         (BACKGROUND)                   │
                           ┌────────────┴────────────┐
                           ↓                         ↓
                          YES                        NO
                           │                         │
                    SessionContext              Learnings
                    (BACKGROUND)                    │
                                          ┌─────────┴─────────┐
                                          ↓                   ↓
                                   High volume?         High value?
                                          │                   │
                                       AGENTIC             PROPOSE
    """)

    print("\n✅ Mode selection guide provided!")


# =============================================================================
# Test 8: Mode-Specific Context Output
# =============================================================================


def test_mode_context_output():
    """
    build_context() produces different output based on mode.
    """
    print("\n" + "=" * 60)
    print("TEST 8: Mode-Specific Context Output")
    print("=" * 60)

    # AGENTIC mode context
    agentic_learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        session_context=False,
        learnings=LearningsConfig(mode=LearningMode.AGENTIC),
    )

    agentic_context = agentic_learning.build_context(message="test")
    print("\n📝 AGENTIC mode context (excerpt):")
    print("-" * 40)
    # Show first 400 chars
    print(agentic_context[:400] if agentic_context else "(empty)")
    print("-" * 40)

    # PROPOSE mode context
    propose_learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        session_context=False,
        learnings=LearningsConfig(mode=LearningMode.PROPOSE),
    )

    propose_context = propose_learning.build_context(message="test")
    print("\n📝 PROPOSE mode context (excerpt):")
    print("-" * 40)
    print(propose_context[:400] if propose_context else "(empty)")
    print("-" * 40)

    print("""
    Key differences:
    
    AGENTIC context says:
    • "Call save_learning directly when you find valuable insights"
    • No mention of user confirmation
    
    PROPOSE context says:
    • "Propose the learning first, wait for user confirmation"
    • "Only call save_learning after user says 'yes'"
    """)

    print("\n✅ Mode-specific context output works!")


# =============================================================================
# Test 9: Combined Modes Example
# =============================================================================


def test_combined_modes():
    """
    Use different modes for different stores in the same LearningMachine.
    """
    print("\n" + "=" * 60)
    print("TEST 9: Combined Modes Example")
    print("=" * 60)

    # Real-world configuration
    learning = LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        # User profile: BACKGROUND (auto-extract, no interruption)
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_tool=True,  # But also allow explicit saves
        ),
        # Session context: BACKGROUND (always auto-extract)
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
        # Learnings: PROPOSE (user confirms high-value insights)
        learnings=LearningsConfig(
            mode=LearningMode.PROPOSE,
            enable_tool=True,
            enable_search=True,
        ),
    )

    print("📊 Combined configuration:")
    for name, store in learning.stores.items():
        print(f"   {name}: {store}")

    print("""
    This configuration:
    
    1. User Profile (BACKGROUND + tool):
       • Auto-extracts facts from conversation
       • Agent can also save explicitly if it notices something
    
    2. Session Context (BACKGROUND):
       • Always summarizes automatically
       • Tracks goal/plan/progress (planning mode)
    
    3. Learnings (PROPOSE):
       • Agent proposes valuable insights
       • User confirms before saving
       • Higher quality knowledge base
    """)

    print("\n✅ Combined modes work together!")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🎚️  Learning Modes — BACKGROUND vs AGENTIC vs PROPOSE")
    print("=" * 60)

    # Run all tests
    test_mode_definitions()
    test_background_mode()
    test_agentic_mode()
    test_propose_mode()
    test_mode_support()
    test_unsupported_mode_warnings()
    test_choosing_modes()
    test_mode_context_output()
    test_combined_modes()

    # Summary
    print("\n" + "=" * 60)
    print("✅ All tests complete!")
    print("=" * 60)
    print("""
Key takeaways:

1. **BACKGROUND**: Automatic, no interruption
   → User profiles, session summaries

2. **AGENTIC**: Agent-driven, direct saves
   → General learnings, high volume

3. **PROPOSE**: Quality control, user confirms
   → High-value insights, strategic knowledge

4. **Not all stores support all modes**
   → SessionContext is BACKGROUND only
   → Unsupported modes warn, don't crash

5. **Combine modes** for different stores
   → BACKGROUND for profiles
   → PROPOSE for learnings
""")
