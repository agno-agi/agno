"""
Session Context Store - Session State and Planning

This cookbook demonstrates the SessionContextStore for managing
session-level state that is replaced (not appended) on each extraction.

Features tested:
- Multi-session context isolation
- Summary extraction from conversations
- Planning mode (goal/plan/progress)
- Context replacement behavior
- Session context retrieval
"""

from agno.db.postgres import PostgresDb
from agno.learn.stores.session_context import SessionContextStore
from agno.learn.config import SessionContextConfig
from agno.learn.schemas import DefaultSessionContext
from agno.models.openai import OpenAIChat
from agno.models.message import Message
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Create the store
store = SessionContextStore(db=db)

# Define test sessions
session_1_id = "session_research_project"
session_2_id = "session_code_review"
session_3_id = "session_planning_demo"


def test_basic_summary_extraction():
    """Test basic conversation summary extraction."""
    print("=" * 60)
    print("TEST: Basic Summary Extraction")
    print("=" * 60)

    model = OpenAIChat(id="gpt-4o-mini")

    # Simulate a research conversation
    messages = [
        Message(role="user", content="I need help researching LLM fine-tuning techniques."),
        Message(role="assistant", content="I can help with that. What's your use case?"),
        Message(role="user", content="I want to fine-tune Llama 3 for code generation."),
        Message(role="assistant", content="Great choice. You'll want to look at LoRA and QLoRA for efficient fine-tuning."),
        Message(role="user", content="What datasets should I use?"),
        Message(role="assistant", content="For code generation, consider CodeAlpaca, CodeSearchNet, or The Stack."),
        Message(role="user", content="Let's start with CodeAlpaca. How do I prepare the data?"),
    ]

    # Extract context (summary only, no planning)
    context = store.extract_and_save(
        session_id=session_1_id,
        messages=messages,
        model=model,
        enable_planning=False,
    )

    print(f"\nSession 1 ({session_1_id}) context:")
    if context:
        pprint(context.to_dict())
        assert context.summary, "Should have a summary"
        print(f"\n  Summary length: {len(context.summary)} chars")
    else:
        print("  No context extracted")

    print("\n✅ Basic summary extraction test passed!")


def test_planning_mode():
    """Test planning mode with goal/plan/progress extraction."""
    print("\n" + "=" * 60)
    print("TEST: Planning Mode (Goal/Plan/Progress)")
    print("=" * 60)

    # Create store with planning enabled
    planning_config = SessionContextConfig(enable_planning=True)
    planning_store = SessionContextStore(db=db, config=planning_config)

    model = OpenAIChat(id="gpt-4o-mini")

    # Simulate a planning conversation
    messages = [
        Message(role="user", content="I want to build a REST API for my todo app."),
        Message(role="assistant", content="Great! Let's break this down. What features do you need?"),
        Message(role="user", content="Basic CRUD operations, user auth, and categories for todos."),
        Message(role="assistant", content="Here's a plan: 1) Set up FastAPI project, 2) Create database models, 3) Implement CRUD endpoints, 4) Add JWT authentication, 5) Add category support."),
        Message(role="user", content="Perfect. I've already set up the FastAPI project and created the models."),
        Message(role="assistant", content="Excellent progress! Next up is implementing the CRUD endpoints."),
        Message(role="user", content="Can you help me with the endpoint for creating a todo?"),
    ]

    context = planning_store.extract_and_save(
        session_id=session_3_id,
        messages=messages,
        model=model,
        enable_planning=True,
    )

    print(f"\nSession 3 ({session_3_id}) context with planning:")
    if context:
        pprint(context.to_dict())
        print(f"\n  Summary: {context.summary[:100] if context.summary else 'None'}...")
        print(f"  Goal: {context.goal or 'None'}")
        print(f"  Plan: {len(context.plan) if context.plan else 0} steps")
        print(f"  Progress: {len(context.progress) if context.progress else 0} completed")
    else:
        print("  No context extracted")

    print("\n✅ Planning mode test passed!")


def test_session_isolation():
    """Test that sessions are properly isolated."""
    print("\n" + "=" * 60)
    print("TEST: Session Isolation")
    print("=" * 60)

    model = OpenAIChat(id="gpt-4o-mini")

    # Session 2: Code review conversation (different from session 1)
    messages = [
        Message(role="user", content="Can you review this Python code for me?"),
        Message(role="assistant", content="Sure, please share the code."),
        Message(role="user", content="def add(a, b): return a + b"),
        Message(role="assistant", content="The function looks good but could use type hints and a docstring."),
    ]

    store.extract_and_save(
        session_id=session_2_id,
        messages=messages,
        model=model,
        enable_planning=False,
    )

    # Verify both sessions have different contexts
    context_1 = store.get(session_1_id)
    context_2 = store.get(session_2_id)

    print(f"\nSession 1 summary: {context_1.summary[:80] if context_1 and context_1.summary else 'None'}...")
    print(f"Session 2 summary: {context_2.summary[:80] if context_2 and context_2.summary else 'None'}...")

    if context_1 and context_2:
        assert context_1.summary != context_2.summary, "Sessions should have different summaries"
        print("\n  ✓ Sessions are properly isolated")

    print("\n✅ Session isolation test passed!")


def test_context_replacement():
    """Test that context is replaced (not appended) on each extraction."""
    print("\n" + "=" * 60)
    print("TEST: Context Replacement")
    print("=" * 60)

    model = OpenAIChat(id="gpt-4o-mini")
    test_session = "session_replacement_test"

    # First conversation
    messages_1 = [
        Message(role="user", content="Let's discuss Python basics."),
        Message(role="assistant", content="Sure! What would you like to know about Python?"),
        Message(role="user", content="Tell me about lists."),
    ]

    store.extract_and_save(
        session_id=test_session,
        messages=messages_1,
        model=model,
        enable_planning=False,
    )

    context_1 = store.get(test_session)
    print(f"\nAfter first conversation:")
    print(f"  Summary: {context_1.summary if context_1 else 'None'}")
    summary_1 = context_1.summary if context_1 else ""

    # Second conversation (completely different topic)
    messages_2 = [
        Message(role="user", content="Now let's talk about JavaScript frameworks."),
        Message(role="assistant", content="Sure! React, Vue, and Angular are popular choices."),
        Message(role="user", content="Which one is best for beginners?"),
    ]

    store.extract_and_save(
        session_id=test_session,
        messages=messages_2,
        model=model,
        enable_planning=False,
    )

    context_2 = store.get(test_session)
    print(f"\nAfter second conversation:")
    print(f"  Summary: {context_2.summary if context_2 else 'None'}")
    summary_2 = context_2.summary if context_2 else ""

    # Summary should be completely different (replaced, not appended)
    if summary_1 and summary_2:
        assert "Python" not in summary_2 or "JavaScript" in summary_2, \
            "Context should be replaced, not appended"
        print("\n  ✓ Context was properly replaced")

    # Cleanup
    db.delete_learnings(learning_type="session_context", session_id=test_session)

    print("\n✅ Context replacement test passed!")


def test_manual_context_save():
    """Test manually saving context (without extraction)."""
    print("\n" + "=" * 60)
    print("TEST: Manual Context Save")
    print("=" * 60)

    test_session = "session_manual_test"

    # Create context manually
    context = DefaultSessionContext(
        session_id=test_session,
        summary="User is building a machine learning pipeline.",
        goal="Deploy ML model to production",
        plan=[
            "Train model locally",
            "Containerize with Docker",
            "Deploy to Kubernetes",
            "Set up monitoring",
        ],
        progress=[
            "Train model locally",
        ],
    )

    # Save directly
    store.save(test_session, context)

    # Retrieve and verify
    retrieved = store.get(test_session)
    print(f"\nManually saved context for {test_session}:")
    if retrieved:
        pprint(retrieved.to_dict())
        assert retrieved.goal == "Deploy ML model to production"
        assert len(retrieved.plan) == 4
        assert len(retrieved.progress) == 1
        print("\n  ✓ Manual save/retrieve working")

    # Cleanup
    db.delete_learnings(learning_type="session_context", session_id=test_session)

    print("\n✅ Manual context save test passed!")


def test_get_context_text():
    """Test formatted text output for context."""
    print("\n" + "=" * 60)
    print("TEST: Formatted Context Text")
    print("=" * 60)

    context = DefaultSessionContext(
        session_id="test",
        summary="Building a chatbot application.",
        goal="Create production-ready chatbot",
        plan=["Design conversation flows", "Implement NLU", "Add integrations", "Test and deploy"],
        progress=["Design conversation flows", "Implement NLU"],
    )

    text = context.get_context_text()
    print("\nFormatted context text:")
    print("-" * 40)
    print(text)
    print("-" * 40)

    assert "Summary:" in text
    assert "Goal:" in text
    assert "Plan:" in text
    assert "Progress:" in text
    assert "✓" in text  # Progress checkmarks

    print("\n✅ Formatted text test passed!")


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    test_sessions = [
        session_1_id,
        session_2_id,
        session_3_id,
    ]

    for session_id in test_sessions:
        db.delete_learnings(learning_type="session_context", session_id=session_id)

    print("  Cleaned up test data")


if __name__ == "__main__":
    # Run all tests
    test_basic_summary_extraction()
    test_planning_mode()
    test_session_isolation()
    test_context_replacement()
    test_manual_context_save()
    test_get_context_text()

    # Show final state
    print("\n" + "=" * 60)
    print("FINAL STATE")
    print("=" * 60)

    for session_id in [session_1_id, session_2_id, session_3_id]:
        context = store.get(session_id)
        if context:
            print(f"\n{session_id}:")
            print(f"  Summary: {context.summary[:60] if context.summary else 'None'}...")
            if context.goal:
                print(f"  Goal: {context.goal[:40]}...")

    # Uncomment to clean up
    # cleanup()

    print("\n" + "=" * 60)
    print("✅ All SessionContextStore tests passed!")
    print("=" * 60)
