"""
Session Context Store Cookbook
==============================

"The only way to make sense out of change is to plunge into it,
move with it, and join the dance." - Alan Watts

This cookbook demonstrates SessionContextStore - a system for capturing
the current state of a conversation. Unlike UserProfileStore which
accumulates memories, SessionContextStore REPLACES on each extraction.

Think of it as:
- UserProfile = your permanent memory of a person
- SessionContext = your notes from today's meeting

Tests:
1. Basic summary extraction - The essentials
2. Planning mode - Goals, plans, progress tracking
3. Session isolation - Your session, your context
4. Context replacement - Fresh state, not stale accumulation
5. Manual save - Sometimes you know best
6. Formatted output - Ready for prompts
7. State tracking - Know when things changed
8. Multi-turn evolution - Watch context grow across turns
"""

from agno.db.postgres import PostgresDb
from agno.learn.config import SessionContextConfig
from agno.learn.schemas import BaseSessionContext
from agno.learn.stores.session_context import SessionContextStore
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    learnings_table="agno_learnings",
)
model = OpenAIChat(id="gpt-4o-mini")

# Summary-only store (default)
store = SessionContextStore(
    config=SessionContextConfig(
        db=db,
        model=model,
        enable_planning=False,
    )
)

# Planning-enabled store
planning_store = SessionContextStore(
    config=SessionContextConfig(
        db=db,
        model=model,
        enable_planning=True,
    )
)

# Test sessions
SESSION_RESEARCH = "session_research_llm_finetuning"
SESSION_CODE = "session_code_review"
SESSION_PLANNING = "session_api_project"


# -----------------------------------------------------------------------------
# Test 1: Basic Summary Extraction
# -----------------------------------------------------------------------------


def test_basic_summary():
    """
    The simplest case: extract a summary from conversation.
    No goals, no plans - just "what happened here?"
    """
    print("\n" + "=" * 60)
    print("TEST 1: Basic Summary Extraction")
    print("=" * 60)

    messages = [
        Message(
            role="user", content="I need help researching LLM fine-tuning techniques."
        ),
        Message(
            role="assistant", content="I can help with that. What's your use case?"
        ),
        Message(
            role="user", content="I want to fine-tune Llama 3 for code generation."
        ),
        Message(
            role="assistant",
            content="Great choice. You'll want to look at LoRA and QLoRA for efficient fine-tuning.",
        ),
        Message(role="user", content="What datasets should I use?"),
        Message(
            role="assistant",
            content="For code generation, consider CodeAlpaca, CodeSearchNet, or The Stack.",
        ),
    ]

    response = store.extract_and_save(
        messages=messages,
        session_id=SESSION_RESEARCH,
    )

    print(f"\n📝 Extraction response: {response}")
    print(f"🔄 Context updated: {store.context_updated}")

    context = store.get(SESSION_RESEARCH)
    print(f"\n📋 Session context:")
    if context:
        pprint(context.to_dict())
        assert context.summary, "Should have a summary"

    print("\n✅ Basic summary works")


# -----------------------------------------------------------------------------
# Test 2: Planning Mode
# -----------------------------------------------------------------------------


def test_planning_mode():
    """
    Full planning mode: goal, plan, progress.
    For when users are working toward something specific.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Planning Mode")
    print("=" * 60)

    messages = [
        Message(role="user", content="I want to build a REST API for my todo app."),
        Message(
            role="assistant",
            content="Great! Let's break this down. What features do you need?",
        ),
        Message(
            role="user", content="Basic CRUD, user auth, and categories for todos."
        ),
        Message(
            role="assistant",
            content="Here's a plan: 1) Set up FastAPI, 2) Create models, 3) CRUD endpoints, 4) JWT auth, 5) Categories.",
        ),
        Message(role="user", content="Perfect. I've done steps 1 and 2 already."),
        Message(
            role="assistant",
            content="Excellent! Next up: CRUD endpoints. Want to start with creating todos?",
        ),
    ]

    response = planning_store.extract_and_save(
        messages=messages,
        session_id=SESSION_PLANNING,
    )

    print(f"\n📝 Extraction response: {response}")
    print(f"🔄 Context updated: {planning_store.context_updated}")

    context = planning_store.get(SESSION_PLANNING)
    print(f"\n🎯 Planning context:")
    if context:
        pprint(context.to_dict())

        print(f"\n   Summary: {context.summary[:80] if context.summary else 'None'}...")
        print(f"   Goal: {context.goal or 'Not identified'}")
        print(f"   Plan: {len(context.plan) if context.plan else 0} steps")
        print(
            f"   Progress: {len(context.progress) if context.progress else 0} completed"
        )

    print("\n✅ Planning mode works")


# -----------------------------------------------------------------------------
# Test 3: Session Isolation
# -----------------------------------------------------------------------------


def test_session_isolation():
    """
    Different sessions = different contexts.
    Research session shouldn't leak into code review.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Session Isolation")
    print("=" * 60)

    # Code review session (completely different from research)
    messages = [
        Message(role="user", content="Can you review this Python code?"),
        Message(role="assistant", content="Sure, share it."),
        Message(role="user", content="def add(a, b): return a + b"),
        Message(role="assistant", content="Works but needs type hints and docstring."),
    ]

    store.extract_and_save(
        messages=messages,
        session_id=SESSION_CODE,
    )

    # Get both contexts
    research_ctx = store.get(SESSION_RESEARCH)
    code_ctx = store.get(SESSION_CODE)

    print(f"\n🔬 Research session:")
    if research_ctx:
        print(f"   {research_ctx.summary[:70]}...")

    print(f"\n💻 Code review session:")
    if code_ctx:
        print(f"   {code_ctx.summary[:70]}...")

    # Verify isolation
    if research_ctx and code_ctx:
        assert research_ctx.summary != code_ctx.summary
        print("\n   ✓ Sessions properly isolated")

    print("\n✅ Isolation works")


# -----------------------------------------------------------------------------
# Test 4: Context Replacement
# -----------------------------------------------------------------------------


def test_context_replacement():
    """
    Key difference from UserProfileStore:
    SessionContext REPLACES on each extraction, doesn't accumulate.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Context Replacement")
    print("=" * 60)

    test_session = "session_replacement_test"

    # First conversation: Python
    messages_1 = [
        Message(role="user", content="Let's talk about Python decorators."),
        Message(
            role="assistant", content="Decorators are functions that modify functions."
        ),
        Message(role="user", content="How do I write one?"),
    ]

    store.extract_and_save(messages=messages_1, session_id=test_session)
    ctx_1 = store.get(test_session)
    print(f"\n🐍 After Python discussion:")
    print(f"   {ctx_1.summary if ctx_1 else 'None'}")

    # Second conversation: Rust (completely different!)
    messages_2 = [
        Message(role="user", content="Actually, let's switch to Rust."),
        Message(role="assistant", content="Sure! What about Rust?"),
        Message(role="user", content="Tell me about ownership and borrowing."),
    ]

    store.extract_and_save(messages=messages_2, session_id=test_session)
    ctx_2 = store.get(test_session)
    print(f"\n🦀 After Rust discussion:")
    print(f"   {ctx_2.summary if ctx_2 else 'None'}")

    # Should be Rust now, not Python
    if ctx_2:
        print(f"\n   ✓ Context replaced (not accumulated)")

    # Cleanup
    store.delete(test_session)

    print("\n✅ Replacement works")


# -----------------------------------------------------------------------------
# Test 5: Manual Save
# -----------------------------------------------------------------------------


def test_manual_save():
    """
    Sometimes you want to set context directly,
    without running extraction.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Manual Save")
    print("=" * 60)

    test_session = "session_manual_test"

    # Create context directly
    context = BaseSessionContext(
        session_id=test_session,
        summary="User is deploying ML model to production.",
        goal="Get model running in Kubernetes",
        plan=[
            "Containerize model with Docker",
            "Write Kubernetes manifests",
            "Set up monitoring",
            "Configure autoscaling",
        ],
        progress=[
            "Containerize model with Docker",
        ],
    )

    # Save directly (no extraction)
    planning_store.save(test_session, context)

    # Retrieve
    retrieved = planning_store.get(test_session)
    print(f"\n💾 Manually saved context:")
    if retrieved:
        pprint(retrieved.to_dict())

        assert retrieved.goal == "Get model running in Kubernetes"
        assert len(retrieved.plan) == 4
        assert len(retrieved.progress) == 1

    # Cleanup
    planning_store.delete(test_session)

    print("\n✅ Manual save works")


# -----------------------------------------------------------------------------
# Test 6: Formatted Output
# -----------------------------------------------------------------------------


def test_formatted_output():
    """
    get_context_text() gives you prompt-ready formatted text.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Formatted Output")
    print("=" * 60)

    test_session = "session_format_test"

    context = BaseSessionContext(
        session_id=test_session,
        summary="Building a chatbot for customer support.",
        goal="Launch MVP by end of month",
        plan=[
            "Design conversation flows",
            "Train intent classifier",
            "Build response generation",
            "Integrate with Slack",
        ],
        progress=[
            "Design conversation flows",
            "Train intent classifier",
        ],
    )

    planning_store.save(test_session, context)

    # Get formatted text
    text = planning_store.get_context_text(test_session)
    print(f"\n📄 Formatted context text:")
    print("-" * 40)
    print(text)
    print("-" * 40)

    assert "Session Summary:" in text
    assert "Current Goal:" in text
    assert "Plan:" in text
    assert "✓" in text  # Progress checkmarks

    # Cleanup
    planning_store.delete(test_session)

    print("\n✅ Formatted output works")


# -----------------------------------------------------------------------------
# Test 7: State Tracking
# -----------------------------------------------------------------------------


def test_state_tracking():
    """
    Know when context actually changed vs. no-op.
    """
    print("\n" + "=" * 60)
    print("TEST 7: State Tracking")
    print("=" * 60)

    # Meaningful conversation
    messages_meaningful = [
        Message(
            role="user", content="I'm building a recommendation system for movies."
        ),
        Message(role="assistant", content="Collaborative filtering or content-based?"),
        Message(
            role="user",
            content="Hybrid approach. I have user ratings and movie metadata.",
        ),
    ]

    store.extract_and_save(messages=messages_meaningful, session_id="track_test_1")
    print(
        f"\n🎯 After meaningful conversation: context_updated = {store.context_updated}"
    )
    assert store.context_updated, "Should have updated"

    # Trivial conversation
    messages_trivial = [
        Message(role="user", content="Hi"),
        Message(role="assistant", content="Hello!"),
    ]

    store.extract_and_save(messages=messages_trivial, session_id="track_test_2")
    print(f"👋 After trivial exchange: context_updated = {store.context_updated}")

    # Cleanup
    store.delete("track_test_1")
    store.delete("track_test_2")

    print("\n✅ State tracking works")


# -----------------------------------------------------------------------------
# Test 8: Multi-Turn Evolution
# -----------------------------------------------------------------------------


def test_multi_turn_evolution():
    """
    Watch how context evolves across multiple conversation turns.
    Each extraction captures the current state.
    """
    print("\n" + "=" * 60)
    print("TEST 8: Multi-Turn Evolution")
    print("=" * 60)

    test_session = "session_evolution"
    all_messages = []

    # Turn 1: Initial ask
    messages_1 = [
        Message(role="user", content="Help me build a web scraper."),
        Message(role="assistant", content="Sure! What site and what data?"),
    ]
    all_messages.extend(messages_1)

    planning_store.extract_and_save(messages=all_messages, session_id=test_session)
    ctx_1 = planning_store.get(test_session)
    print(f"\n📍 Turn 1 - Initial:")
    if ctx_1:
        print(f"   Summary: {ctx_1.summary[:60]}...")
        print(f"   Goal: {ctx_1.goal or 'None yet'}")

    # Turn 2: More details
    messages_2 = [
        Message(role="user", content="I want to scrape job listings from LinkedIn."),
        Message(
            role="assistant",
            content="That's tricky - LinkedIn blocks scrapers. Let's use their API or try Selenium.",
        ),
    ]
    all_messages.extend(messages_2)

    planning_store.extract_and_save(messages=all_messages, session_id=test_session)
    ctx_2 = planning_store.get(test_session)
    print(f"\n📍 Turn 2 - Details emerge:")
    if ctx_2:
        print(f"   Summary: {ctx_2.summary[:60]}...")
        print(f"   Goal: {ctx_2.goal or 'None yet'}")

    # Turn 3: Decision made
    messages_3 = [
        Message(role="user", content="Let's use Selenium. What's the plan?"),
        Message(
            role="assistant",
            content="1) Set up Selenium, 2) Login flow, 3) Navigate to jobs, 4) Extract data, 5) Save to CSV.",
        ),
        Message(role="user", content="I've got Selenium installed."),
    ]
    all_messages.extend(messages_3)

    planning_store.extract_and_save(messages=all_messages, session_id=test_session)
    ctx_3 = planning_store.get(test_session)
    print(f"\n📍 Turn 3 - Plan formed:")
    if ctx_3:
        print(f"   Summary: {ctx_3.summary[:60]}...")
        print(f"   Goal: {ctx_3.goal or 'None'}")
        print(f"   Plan steps: {len(ctx_3.plan) if ctx_3.plan else 0}")
        print(f"   Progress: {len(ctx_3.progress) if ctx_3.progress else 0}")

    # Cleanup
    planning_store.delete(test_session)

    print("\n✅ Multi-turn evolution works")


# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------


def cleanup():
    """Wipe all test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    sessions = [
        SESSION_RESEARCH,
        SESSION_CODE,
        SESSION_PLANNING,
        "session_replacement_test",
        "session_manual_test",
        "session_format_test",
        "track_test_1",
        "track_test_2",
        "session_evolution",
    ]

    for session_id in sessions:
        try:
            store.delete(session_id)
            planning_store.delete(session_id)
        except Exception:
            pass

    print("🧹 Cleaned")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("📸 SessionContextStore Cookbook")
    print("   Capturing the now, not the forever")
    print("=" * 60)

    test_basic_summary()
    test_planning_mode()
    test_session_isolation()
    test_context_replacement()
    test_manual_save()
    test_formatted_output()
    test_state_tracking()
    test_multi_turn_evolution()

    # Final summary
    print("\n" + "=" * 60)
    print("📊 FINAL STATE")
    print("=" * 60)

    for session_id in [SESSION_RESEARCH, SESSION_CODE, SESSION_PLANNING]:
        ctx = store.get(session_id) or planning_store.get(session_id)
        if ctx:
            print(f"\n{session_id}:")
            print(f"  📝 {ctx.summary[:60] if ctx.summary else 'No summary'}...")
            if hasattr(ctx, "goal") and ctx.goal:
                print(f"  🎯 Goal: {ctx.goal[:40]}...")

    # cleanup()  # Uncomment to wipe

    print("\n" + "=" * 60)
    print("✅ All tests passed")
    print("   Remember: UserProfile accumulates.")
    print("   SessionContext captures the now.")
    print("=" * 60)
